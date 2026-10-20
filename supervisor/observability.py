"""Observabilidade: logs de correlação + Langfuse (SDK v3).

- Logs de entrada/saída de LLM e tools (`CorrelationLogHandler`) sempre ativos.
- Langfuse só entra se LANGFUSE_PUBLIC_KEY/LANGFUSE_SECRET_KEY existirem; sem elas é no-op.

Mantenha este arquivo idêntico nos 3 serviços (supervisor, abrir_conta, cartao_credito):
cada um é um contexto Docker próprio. `scripts/check-correlation-sync.*` verifica isso.
"""

import logging
import os
import re
import time
from contextlib import contextmanager
from functools import wraps
from typing import Any, Dict, Iterator, List, Optional

from correlation import (
    get_conversation_id,
    get_correlation_id,
    log_event,
    safe_payload,
)
from langchain_core.callbacks import AsyncCallbackHandler

logger = logging.getLogger(__name__)

_CPF = re.compile(r"\b\d{3}\.?\d{3}\.?\d{3}-?\d{2}\b")

_client: Any = None
_initialized = False


def enabled() -> bool:
    return bool(os.getenv("LANGFUSE_PUBLIC_KEY") and os.getenv("LANGFUSE_SECRET_KEY"))


def _mask(data: Any, **_: Any) -> Any:
    """Mascara CPF antes de enviar input/output ao Langfuse."""
    if isinstance(data, str):
        return _CPF.sub("***.***.***-**", data)
    if isinstance(data, dict):
        return {k: _mask(v) for k, v in data.items()}
    if isinstance(data, (list, tuple)):
        return [_mask(v) for v in data]
    return data


def get_client() -> Any:
    global _client, _initialized
    if _initialized:
        return _client
    _initialized = True
    if not enabled():
        logger.info("Langfuse desabilitado (chaves ausentes)")
        return None
    try:
        from langfuse import Langfuse

        _client = Langfuse(mask=_mask)
        logger.info("Langfuse habilitado")
    except Exception:
        logger.exception("Falha ao iniciar Langfuse; seguindo sem observabilidade")
        _client = None
    return _client


def _quiet(fn):
    """Logging nunca pode derrubar a chamada ao LLM/tool."""

    @wraps(fn)
    async def wrapper(self, *args, **kwargs):
        try:
            return await fn(self, *args, **kwargs)
        except Exception:
            logger.debug("Falha ao registrar evento de callback", exc_info=True)

    return wrapper


def _ids(metadata: Optional[Dict[str, Any]]) -> Dict[str, Optional[str]]:
    """IDs do ContextVar; se ausentes, usa os que o LangGraph carregou em config.metadata."""
    meta = metadata or {}
    return {
        "correlation_id": get_correlation_id() or meta.get("correlation_id"),
        "conversation_id": get_conversation_id() or meta.get("conversation_id"),
    }


def _text(message: Any) -> str:
    return getattr(message, "text", None) or str(getattr(message, "content", ""))


class CorrelationLogHandler(AsyncCallbackHandler):
    """Loga entrada/saída de LLM (llm.*) e tools (tool.*) com os IDs de correlação."""

    def __init__(self) -> None:
        super().__init__()
        self._started: Dict[str, float] = {}

    def _elapsed(self, run_id: Any) -> Optional[float]:
        started = self._started.pop(str(run_id), None)
        if started is None:
            return None
        return round((time.perf_counter() - started) * 1000, 1)

    @_quiet
    async def on_chat_model_start(
        self, serialized, messages, *, run_id, metadata=None, **kwargs
    ):
        self._started[str(run_id)] = time.perf_counter()
        params = kwargs.get("invocation_params") or {}
        model = params.get("model") or (metadata or {}).get("ls_model_name")
        # System prompt é grande e se repete em toda chamada: não o logamos.
        conversa = [
            {"role": m.type, "content": _text(m)}
            for batch in messages
            for m in batch
            if getattr(m, "type", "") != "system"
        ]
        log_event(
            logger,
            "llm",
            "client",
            "request",
            model=model,
            payload=safe_payload(conversa),
            **_ids(metadata),
        )

    @_quiet
    async def on_llm_end(self, response, *, run_id, metadata=None, **kwargs):
        gen = response.generations[0][0]
        usage = getattr(getattr(gen, "message", None), "usage_metadata", None)
        log_event(
            logger,
            "llm",
            "client",
            "response",
            payload=safe_payload(gen.text),
            usage=usage,
            duration_ms=self._elapsed(run_id),
            **_ids(metadata),
        )

    @_quiet
    async def on_llm_error(self, error, *, run_id, metadata=None, **kwargs):
        log_event(
            logger,
            "llm",
            "client",
            "error",
            error=f"{type(error).__name__}: {error}",
            duration_ms=self._elapsed(run_id),
            **_ids(metadata),
        )

    @_quiet
    async def on_tool_start(
        self, serialized, input_str, *, run_id, metadata=None, **kwargs
    ):
        self._started[str(run_id)] = time.perf_counter()
        name = (serialized or {}).get("name") or kwargs.get("name")
        log_event(
            logger,
            "tool",
            "client",
            "request",
            tool=name,
            payload=safe_payload(input_str),
            **_ids(metadata),
        )

    @_quiet
    async def on_tool_end(self, output, *, run_id, metadata=None, **kwargs):
        log_event(
            logger,
            "tool",
            "client",
            "response",
            tool=kwargs.get("name"),
            payload=safe_payload(getattr(output, "content", output)),
            duration_ms=self._elapsed(run_id),
            **_ids(metadata),
        )

    @_quiet
    async def on_tool_error(self, error, *, run_id, metadata=None, **kwargs):
        log_event(
            logger,
            "tool",
            "client",
            "error",
            tool=kwargs.get("name"),
            error=f"{type(error).__name__}: {error}",
            duration_ms=self._elapsed(run_id),
            **_ids(metadata),
        )


def callbacks() -> List[Any]:
    """Callbacks LangChain/LangGraph para passar em `config={"callbacks": ...}`.

    Sempre inclui o handler de log; o do Langfuse só entra se estiver habilitado.
    """
    handlers: List[Any] = [CorrelationLogHandler()]
    if get_client() is None:
        return handlers
    from langfuse.langchain import CallbackHandler

    handlers.append(CallbackHandler())
    return handlers


async def load_mcp_tools(client: Any, server: str = "conta") -> List[Any]:
    """Carrega as tools do MultiServerMCPClient, com eventos mcp.request/response."""
    started = time.perf_counter()
    log_event(logger, "mcp", "client", "request", operation="list_tools", server=server)
    try:
        tools = await client.get_tools()
    except Exception as e:
        log_event(
            logger,
            "mcp",
            "client",
            "error",
            operation="list_tools",
            server=server,
            error=f"{type(e).__name__}: {e}",
            duration_ms=round((time.perf_counter() - started) * 1000, 1),
        )
        raise
    log_event(
        logger,
        "mcp",
        "client",
        "response",
        operation="list_tools",
        server=server,
        tools=[getattr(t, "name", str(t)) for t in tools],
        duration_ms=round((time.perf_counter() - started) * 1000, 1),
    )
    return tools


@contextmanager
def span(
    name: str,
    *,
    session_id: Optional[str] = None,
    trace_id: Optional[str] = None,
    parent_span_id: Optional[str] = None,
    input: Any = None,
    metadata: Optional[Dict[str, Any]] = None,
) -> Iterator[Any]:
    """Abre um span (raiz ou filho). Com trace_id/parent_span_id, entra num trace existente."""
    client = get_client()
    if client is None:
        yield None
        return

    from langfuse import propagate_attributes

    trace_context = None
    if trace_id:
        trace_context = {"trace_id": trace_id}
        if parent_span_id:
            trace_context["parent_span_id"] = parent_span_id

    with client.start_as_current_span(
        name=name, trace_context=trace_context, input=input, metadata=metadata
    ) as s:
        if session_id:
            with propagate_attributes(session_id=session_id):
                yield s
        else:
            yield s


def current_context(session_id: Optional[str] = None) -> Dict[str, str]:
    """Contexto do span atual, para propagar a outro serviço (ex.: Message.metadata A2A)."""
    client = get_client()
    if client is None:
        return {}
    ctx = {
        "langfuse_trace_id": client.get_current_trace_id(),
        "langfuse_parent_span_id": client.get_current_observation_id(),
        "langfuse_session_id": session_id,
    }
    return {k: v for k, v in ctx.items() if v}


def flush() -> None:
    client = get_client()
    if client is not None:
        client.flush()
