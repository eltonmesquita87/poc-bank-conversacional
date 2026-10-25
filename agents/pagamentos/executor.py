import logging
import time

from a2a.server.agent_execution import AgentExecutor
from a2a.server.agent_execution.context import RequestContext
from a2a.server.events.event_queue import EventQueue
from a2a.utils import new_agent_text_message
from agent.pagamentos import run_agent
from correlation import bind, log_event, resolve_ids, safe_payload
from observability import span

logger = logging.getLogger("a2a")


class PagamentosExecutor(AgentExecutor):

    async def execute(self, context: RequestContext, event_queue: EventQueue):
        meta = (context.message.metadata if context.message else None) or {}
        headers = (
            context.call_context.state.get("headers") if context.call_context else None
        ) or {}
        correlation_id, conversation_id, origem = resolve_ids(meta, headers)

        with bind(correlation_id, conversation_id):
            started = time.perf_counter()
            user_text = context.get_user_input()
            log_event(
                logger,
                "a2a",
                "server",
                "request",
                id_source=origem,
                a2a_task_id=context.task_id,
                a2a_context_id=context.context_id,
                payload=safe_payload(user_text),
            )

            try:
                with span(
                    "agent.pagamentos_pix",
                    session_id=meta.get("langfuse_session_id"),
                    trace_id=meta.get("langfuse_trace_id"),
                    parent_span_id=meta.get("langfuse_parent_span_id"),
                    input=user_text,
                    metadata={
                        "correlation_id": correlation_id,
                        "conversation_id": conversation_id,
                    },
                ) as s:
                    # A memória do agente é por conversa. Sem conversation_id (não deveria
                    # ocorrer, o supervisor sempre envia), cai no ID do turno: sem memória
                    # entre turnos, mas também sem misturar clientes.
                    resposta = await run_agent(
                        mensagem=user_text, thread_id=conversation_id or correlation_id
                    )
                    if s is not None:
                        s.update(output=str(resposta))
            except Exception as e:
                log_event(
                    logger,
                    "a2a",
                    "server",
                    "error",
                    error=f"{type(e).__name__}: {e}",
                    duration_ms=round((time.perf_counter() - started) * 1000, 1),
                )
                raise

            log_event(
                logger,
                "a2a",
                "server",
                "response",
                payload=safe_payload(str(resposta)),
                duration_ms=round((time.perf_counter() - started) * 1000, 1),
            )

        await event_queue.enqueue_event(new_agent_text_message(str(resposta)))

    async def cancel(self, context: RequestContext, event_queue: EventQueue):
        logger.info("agent.cancel.pagamentos")
