"""Correlation ID para rastrear uma mensagem entre frontend, supervisor, agentes, LLM e MCP.

Usa só a stdlib (exceto `mcp_http_client_factory`, que importa `mcp`/`httpx` sob demanda),
porque o mesmo arquivo é copiado para frontend/, recursos/ e agentes, cada um com seu requirements.
Mantenha as cópias idênticas: `scripts/check-correlation-sync.ps1` (ou `.sh`) verifica isso.

Dois IDs:
- correlation_id: um por turno/mensagem do usuário.
- conversation_id: um por conversa (substitui o session_id/thread_id fixo "123"/"1").
"""

import contextvars
import json
import logging
import os
import re
import sys
import time
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from typing import Any, Iterator, Optional

HEADER_CORRELATION = "X-Correlation-ID"
HEADER_CONVERSATION = "X-Conversation-ID"
META_CORRELATION = "correlation_id"
META_CONVERSATION = "conversation_id"

_ID_RE = re.compile(r"^[A-Za-z0-9._-]{8,64}$")
_CPF = re.compile(r"\b\d{3}\.?\d{3}\.?\d{3}-?\d{2}\b")
_CPF_MASK = "***.***.***-**"

_correlation_id: contextvars.ContextVar[Optional[str]] = contextvars.ContextVar(
    "correlation_id", default=None
)
_conversation_id: contextvars.ContextVar[Optional[str]] = contextvars.ContextVar(
    "conversation_id", default=None
)


# -----------------------------
# IDs
# -----------------------------


def new_id() -> str:
    return str(uuid.uuid4())


def valid_id(value: Any) -> bool:
    return isinstance(value, str) and bool(_ID_RE.match(value))


def get_correlation_id() -> Optional[str]:
    return _correlation_id.get()


def get_conversation_id() -> Optional[str]:
    return _conversation_id.get()


@contextmanager
def bind(
    correlation_id: Optional[str] = None, conversation_id: Optional[str] = None
) -> Iterator[None]:
    """Define os IDs para o bloco e restaura os valores anteriores ao sair.

    Use em corrotinas comuns. Para async generators (SSE), use `set_ids`.
    """
    tok_c = _correlation_id.set(correlation_id)
    tok_v = _conversation_id.set(conversation_id)
    try:
        yield
    finally:
        _correlation_id.reset(tok_c)
        _conversation_id.reset(tok_v)


def set_ids(
    correlation_id: Optional[str] = None, conversation_id: Optional[str] = None
) -> None:
    """Define os IDs sem restaurar depois.

    Reset de token pode falhar quando o generator é finalizado em outro contexto.
    """
    if correlation_id is not None:
        _correlation_id.set(correlation_id)
    if conversation_id is not None:
        _conversation_id.set(conversation_id)


def outbound_headers() -> dict[str, str]:
    """Headers HTTP para propagar a outro serviço."""
    headers = {}
    if get_correlation_id():
        headers[HEADER_CORRELATION] = get_correlation_id()
    if get_conversation_id():
        headers[HEADER_CONVERSATION] = get_conversation_id()
    return headers


def outbound_metadata() -> dict[str, str]:
    """Chaves para `Message.metadata` do A2A."""
    meta = {}
    if get_correlation_id():
        meta[META_CORRELATION] = get_correlation_id()
    if get_conversation_id():
        meta[META_CONVERSATION] = get_conversation_id()
    return meta


def resolve_ids(
    metadata: Optional[dict[str, Any]] = None,
    headers: Optional[dict[str, Any]] = None,
) -> tuple[str, Optional[str], str]:
    """IDs de uma requisição recebida (ex.: executor A2A).

    Ordem: metadata (corpo A2A) -> header HTTP -> contexto já ligado -> novo UUID.
    Retorna (correlation_id, conversation_id, origem), em que origem diz de onde veio o
    correlation_id; útil para verificar a propagação nos logs.
    """
    meta = metadata or {}
    hdrs = headers or {}

    correlation_id = None
    origem = "novo"
    for fonte, valor in (
        ("metadata", meta.get(META_CORRELATION)),
        ("header", hdrs.get(HEADER_CORRELATION.lower())),
        ("contexto", get_correlation_id()),
    ):
        if valid_id(valor):
            correlation_id, origem = valor, fonte
            break
    if correlation_id is None:
        correlation_id = new_id()

    conversation_id = None
    for valor in (
        meta.get(META_CONVERSATION),
        hdrs.get(HEADER_CONVERSATION.lower()),
        get_conversation_id(),
    ):
        if valid_id(valor):
            conversation_id = valor
            break

    return correlation_id, conversation_id, origem


# -----------------------------
# PAYLOAD SEGURO PARA LOG
# -----------------------------


def mask(data: Any) -> Any:
    """Mascara CPF em strings, dicts, listas e tuplas (mesma regra de observability.py)."""
    if isinstance(data, str):
        return _CPF.sub(_CPF_MASK, data)
    if isinstance(data, dict):
        return {k: mask(v) for k, v in data.items()}
    if isinstance(data, (list, tuple)):
        return [mask(v) for v in data]
    return data


def safe_payload(data: Any) -> Optional[str]:
    """Conteúdo para log, conforme LOG_PAYLOAD (off|truncated|full).

    Lê o ambiente a cada chamada: `load_dotenv()` roda depois do import em alguns serviços.
    """
    mode = os.getenv("LOG_PAYLOAD", "truncated").strip().lower()
    if mode == "off":
        return None
    if data is None:
        return None
    if isinstance(data, str):
        text = data
    else:
        text = json.dumps(data, ensure_ascii=False, default=str)
    text = mask(text)
    if mode == "full":
        return text
    try:
        limit = int(os.getenv("LOG_PAYLOAD_MAX_CHARS", "2000"))
    except ValueError:
        limit = 2000
    if len(text) > limit:
        return f"{text[:limit]}…(+{len(text) - limit} chars)"
    return text


# -----------------------------
# LOGGING JSON
# -----------------------------


class JsonFormatter(logging.Formatter):
    """Uma linha JSON por evento. Campos fixos + extras passados por `log_event`."""

    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "ts": datetime.fromtimestamp(record.created, tz=timezone.utc).isoformat(
                timespec="milliseconds"
            ),
            "level": record.levelname,
            "service": getattr(record, "service", None),
            "logger": record.name,
            "correlation_id": getattr(record, "correlation_id", None),
            "conversation_id": getattr(record, "conversation_id", None),
            "msg": record.getMessage(),
        }
        extra = getattr(record, "event_fields", None)
        if extra:
            payload.update(extra)
        if record.exc_info:
            payload["exc"] = self.formatException(record.exc_info)
        return json.dumps(payload, ensure_ascii=False, default=str)


_configured = False


def setup_logging(service: str) -> None:
    """Configura o root com JSON. Idempotente (Streamlit reexecuta o script a cada interação).

    Um LogRecordFactory injeta service e IDs em todo record, inclusive de loggers filhos
    como `a2a.*`. Filtro por logger não cobriria esses casos.
    """
    global _configured
    level_name = os.getenv("LOG_LEVEL", "INFO").upper()
    level = getattr(logging, level_name, logging.INFO)

    if not _configured:
        previous_factory = logging.getLogRecordFactory()

        def factory(*args: Any, **kwargs: Any) -> logging.LogRecord:
            record = previous_factory(*args, **kwargs)
            record.service = service
            record.correlation_id = get_correlation_id()
            record.conversation_id = get_conversation_id()
            return record

        logging.setLogRecordFactory(factory)
        _configured = True

    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(JsonFormatter())
    root = logging.getLogger()
    root.handlers = [handler]
    root.setLevel(level)


def log_event(
    logger: logging.Logger,
    integration: str,
    role: str,
    phase: str,
    **fields: Any,
) -> None:
    """Loga um evento de entrada/saída de integração.

    Mensagem = "<integration>.<phase>". Campos extras vão no JSON, com `payload` já tratado
    por `safe_payload` quando for conteúdo.
    """
    level = logging.ERROR if phase == "error" else logging.INFO
    event = {"integration": integration, "role": role, "phase": phase}
    event.update({k: v for k, v in fields.items() if v is not None})
    logger.log(level, f"{integration}.{phase}", extra={"event_fields": event})


# -----------------------------
# MIDDLEWARE HTTP (ASGI puro, sem BaseHTTPMiddleware: não quebra SSE)
# -----------------------------


class CorrelationMiddleware:
    """Lê/gera os IDs, faz `bind`, loga http.request/response e ecoa X-Correlation-ID."""

    def __init__(self, app: Any) -> None:
        self.app = app

    async def __call__(self, scope: dict, receive: Any, send: Any) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        raw = {
            k.decode("latin-1").lower(): v.decode("latin-1")
            for k, v in scope.get("headers", [])
        }
        correlation_id = raw.get(HEADER_CORRELATION.lower())
        if not valid_id(correlation_id):
            correlation_id = new_id()
        conversation_id = raw.get(HEADER_CONVERSATION.lower())
        if not valid_id(conversation_id):
            conversation_id = None

        logger = logging.getLogger("http")
        method = scope.get("method")
        path = scope.get("path")
        status_holder = {"status": None}
        started = time.perf_counter()

        async def send_wrapper(message: dict) -> None:
            if message["type"] == "http.response.start":
                status_holder["status"] = message["status"]
                # Lê o correlation_id no momento do envio: um endpoint pode tê-lo trocado
                # (ex.: POST / usa run_id do AG-UI).
                current = get_correlation_id() or correlation_id
                headers = list(message.get("headers", []))
                headers.append((HEADER_CORRELATION.lower().encode(), current.encode()))
                message = {**message, "headers": headers}
            await send(message)

        with bind(correlation_id, conversation_id):
            log_event(logger, "http", "server", "request", method=method, path=path)
            try:
                await self.app(scope, receive, send_wrapper)
            except Exception as exc:
                log_event(
                    logger,
                    "http",
                    "server",
                    "error",
                    method=method,
                    path=path,
                    error=f"{type(exc).__name__}: {exc}",
                    duration_ms=round((time.perf_counter() - started) * 1000, 1),
                )
                raise
            log_event(
                logger,
                "http",
                "server",
                "response",
                method=method,
                path=path,
                status=status_holder["status"],
                duration_ms=round((time.perf_counter() - started) * 1000, 1),
            )


# -----------------------------
# HTTPX / MCP (import sob demanda)
# -----------------------------


def mcp_http_client_factory(
    headers: Optional[dict[str, str]] = None,
    timeout: Any = None,
    auth: Any = None,
) -> Any:
    """Cria o httpx.AsyncClient do MCP injetando X-Correlation-ID/X-Conversation-ID em cada request.

    Cobre initialize, tools/list e tools/call. Os headers são lidos do ContextVar no momento
    do envio, então funcionam mesmo quando o cliente é reutilizado.
    """
    from mcp.shared._httpx_utils import create_mcp_http_client

    client = create_mcp_http_client(headers=headers, timeout=timeout, auth=auth)

    async def _inject_headers(request: Any) -> None:
        for key, value in outbound_headers().items():
            request.headers[key] = value

    client.event_hooks.setdefault("request", []).append(_inject_headers)
    return client
