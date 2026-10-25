"""Logs de correlação do servidor MCP (recursos).

Fica só em recursos/ porque depende do fastmcp, então não entra na cópia sincronizada de
correlation.py. Os IDs chegam como headers HTTP (X-Correlation-ID/X-Conversation-ID) enviados
pelo cliente MCP dos agentes (mcp_http_client_factory).
"""

import logging
import time

from correlation import bind, log_event, resolve_ids, safe_payload
from fastmcp.server.dependencies import get_http_headers
from fastmcp.server.middleware import CallNext, Middleware, MiddlewareContext

logger = logging.getLogger(__name__)


class CorrelationMcpMiddleware(Middleware):
    """Liga os IDs de correlação a cada mensagem MCP e loga entrada/saída."""

    async def on_message(self, context: MiddlewareContext, call_next: CallNext):
        # include_all: get_http_headers por padrão remove alguns headers; os nossos passam,
        # mas deixamos explícito para não depender da lista de exclusão.
        headers = get_http_headers(include_all=True)
        correlation_id, conversation_id, origem = resolve_ids(None, headers)

        with bind(correlation_id, conversation_id):
            started = time.perf_counter()
            log_event(
                logger,
                "mcp",
                "server",
                "request",
                method=context.method,
                id_source=origem,
            )
            try:
                result = await call_next(context)
            except Exception as e:
                log_event(
                    logger,
                    "mcp",
                    "server",
                    "error",
                    method=context.method,
                    error=f"{type(e).__name__}: {e}",
                    duration_ms=round((time.perf_counter() - started) * 1000, 1),
                )
                raise

            log_event(
                logger,
                "mcp",
                "server",
                "response",
                method=context.method,
                duration_ms=round((time.perf_counter() - started) * 1000, 1),
            )
            return result

    async def on_call_tool(self, context: MiddlewareContext, call_next: CallNext):
        params = context.message
        tool = getattr(params, "name", None)
        started = time.perf_counter()
        log_event(
            logger,
            "tool",
            "server",
            "request",
            tool=tool,
            payload=safe_payload(getattr(params, "arguments", None)),
        )
        try:
            result = await call_next(context)
        except Exception as e:
            log_event(
                logger,
                "tool",
                "server",
                "error",
                tool=tool,
                error=f"{type(e).__name__}: {e}",
                duration_ms=round((time.perf_counter() - started) * 1000, 1),
            )
            raise

        log_event(
            logger,
            "tool",
            "server",
            "response",
            tool=tool,
            duration_ms=round((time.perf_counter() - started) * 1000, 1),
        )
        return result
