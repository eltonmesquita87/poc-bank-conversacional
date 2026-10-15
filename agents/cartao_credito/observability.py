"""Observabilidade com Langfuse (SDK v3).

Sem LANGFUSE_PUBLIC_KEY/LANGFUSE_SECRET_KEY tudo vira no-op, então a aplicação
roda normalmente sem Langfuse. Mantenha este arquivo idêntico nos 3 serviços
(supervisor, abrir_conta, cartao_credito): cada um é um contexto Docker próprio.
"""

import logging
import os
import re
from contextlib import contextmanager
from typing import Any, Dict, Iterator, List, Optional

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


def callbacks() -> List[Any]:
    """Callbacks LangChain/LangGraph para passar em `config={"callbacks": ...}`."""
    if get_client() is None:
        return []
    from langfuse.langchain import CallbackHandler

    return [CallbackHandler()]


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
