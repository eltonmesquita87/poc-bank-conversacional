import logging
import time
import uuid
from operator import add
from typing import Annotated, TypedDict

import httpx
from a2a.client import A2ACardResolver, ClientConfig, ClientFactory
from a2a.client.middleware import ClientCallContext
from a2a.types import Message, Part, Role, TextPart
from ag_ui.core import (
    EventType,
    TextMessageContentEvent,
    TextMessageEndEvent,
    TextMessageStartEvent,
)
from langchain_core.runnables import RunnableConfig
from langgraph.graph import END, START, StateGraph
from langgraph.types import Send
from pydantic import BaseModel

from correlation import (
    get_conversation_id,
    log_event,
    outbound_headers,
    outbound_metadata,
    safe_payload,
)
from observability import callbacks, current_context, span
from src.agents import classifique_intencao_do_usuario

logger = logging.getLogger(__name__)

# -----------------------------
# HTTP CLIENT GLOBAL
# -----------------------------
HTTPX_CLIENT = httpx.AsyncClient(timeout=30)

# -----------------------------
# REGISTRY DE AGENTES
# -----------------------------
AGENTS = {
    "cartao_credito": "http://cartao_credito_agent:8000",
    "abrir_conta": "http://abrir_conta_agent:8000",
}

# Cache de clientes A2A
CLIENT_CACHE = {}

# -----------------------------
# STATE DO LANGGRAPH
# -----------------------------


class State(TypedDict):
    query: str
    responses: Annotated[list[str], add]


# -----------------------------
# EVENTO PARA STATE UPDATE
# -----------------------------


class StateUpdateEvent(BaseModel):
    type: str = "STATE_UPDATE"
    state: dict


# -----------------------------
# CHAMADA PARA AGENTE A2A
# -----------------------------


async def request_agent(
    message: str, agent_url: str, session_id: str | None = None
) -> str:
    with span(
        "a2a.request_agent",
        input=message,
        metadata={"agent_url": agent_url, **outbound_metadata()},
    ) as s:
        resposta = await _request_agent(message, agent_url, session_id)
        if s is not None:
            s.update(output=resposta)
        return resposta


async def _request_agent(message: str, agent_url: str, session_id: str | None) -> str:

    if agent_url not in CLIENT_CACHE:
        logger.info(f"Descobrindo AgentCard em {agent_url}")

        resolver = A2ACardResolver(
            httpx_client=HTTPX_CLIENT,
            base_url=agent_url,
        )

        agent_card = await resolver.get_agent_card()
        logger.info(f"Agent encontrado: {agent_card.name}")

        config = ClientConfig(httpx_client=HTTPX_CLIENT, streaming=False)
        factory = ClientFactory(config)
        CLIENT_CACHE[agent_url] = factory.create(agent_card)

    client = CLIENT_CACHE[agent_url]

    msg = Message(
        role=Role.user,
        message_id=str(uuid.uuid4()),
        parts=[Part(root=TextPart(text=message))],
        # propaga o trace Langfuse e os IDs de correlação no corpo A2A (metadata)
        metadata={**current_context(session_id), **outbound_metadata()} or None,
    )

    # Os mesmos IDs também vão como headers HTTP, por chamada (http_kwargs do cliente A2A)
    ctx = ClientCallContext(state={"http_kwargs": {"headers": outbound_headers()}})

    started = time.perf_counter()
    log_event(
        logger,
        "a2a",
        "client",
        "request",
        agent_url=agent_url,
        a2a_message_id=msg.message_id,
        payload=safe_payload(message),
    )

    try:
        resposta = None
        async for event in client.send_message(msg, context=ctx):
            if isinstance(event, Message):
                for part in event.parts:
                    if part.root.kind == "text":
                        resposta = part.root.text
                        break
            if resposta is not None:
                break
    except Exception as e:
        log_event(
            logger,
            "a2a",
            "client",
            "error",
            agent_url=agent_url,
            error=f"{type(e).__name__}: {e}",
            duration_ms=round((time.perf_counter() - started) * 1000, 1),
        )
        raise

    if resposta is None:
        resposta = "Sem resposta do agente."

    log_event(
        logger,
        "a2a",
        "client",
        "response",
        agent_url=agent_url,
        payload=safe_payload(resposta),
        duration_ms=round((time.perf_counter() - started) * 1000, 1),
    )
    return resposta


# -----------------------------
# ROUTER
# -----------------------------


async def no_de_roteamento(state: State, config: RunnableConfig):
    query = state.get("query", "")
    classifications = await classifique_intencao_do_usuario(
        query, callbacks=config.get("callbacks")
    )
    # Só os agentes: o texto da query pode conter CPF e já sai mascarado em log_event
    logger.info(f"Classificação: {[c['agent'] for c in classifications]}")
    return [Send(c["agent"], {"query": c["query"]}) for c in classifications]


# -----------------------------
# NODE CARTAO
# -----------------------------


async def cartao_credito_node(state: State, config: RunnableConfig):
    query = state.get("query", "")
    logger.info("Executando agente CARTAO_CREDITO")
    session_id = config.get("metadata", {}).get("langfuse_session_id")
    resposta = await request_agent(query, AGENTS["cartao_credito"], session_id)
    return {"responses": [resposta]}


# -----------------------------
# NODE ABRIR CONTA
# -----------------------------


async def abrir_conta_node(state: State, config: RunnableConfig):
    query = state.get("query", "")
    logger.info("Executando agente ABRIR_CONTA")
    session_id = config.get("metadata", {}).get("langfuse_session_id")
    resposta = await request_agent(query, AGENTS["abrir_conta"], session_id)
    return {"responses": [resposta]}


# -----------------------------
# BUILD DO GRAFO
# -----------------------------
builder = StateGraph(State)
builder.add_node("cartao_credito", cartao_credito_node)
builder.add_node("abrir_conta", abrir_conta_node)
builder.add_conditional_edges(START, no_de_roteamento)
builder.add_edge("cartao_credito", END)
builder.add_edge("abrir_conta", END)
graph = builder.compile()

# -----------------------------
# EXECUTOR DO SUPERVISOR (NORMAL)
# -----------------------------


async def executar_supervisor(texto_usuario: str, session_id: str | None = None):
    session_id = session_id or get_conversation_id() or str(uuid.uuid4())
    input_state: State = {"query": texto_usuario, "responses": []}
    with span(
        "supervisor.chat",
        session_id=session_id,
        input=texto_usuario,
        metadata=outbound_metadata(),
    ) as s:
        result = await graph.ainvoke(
            input_state,
            {
                "callbacks": callbacks(),
                # os IDs também ficam em config.metadata, usados fora do ContextVar
                "metadata": {"langfuse_session_id": session_id, **outbound_metadata()},
            },
        )
        resposta = "\n\n".join(result["responses"])
        if s is not None:
            s.update(output=resposta)
        return resposta


# -----------------------------
# EXECUTOR DO SUPERVISOR (STREAMING COM STATE)
# -----------------------------


async def executar_supervisor_stream(input_data):
    """
    Retorna eventos para AG-UI, incluindo state compartilhado.
    Envolve o stream num span raiz do Langfuse (session = conversation_id).
    """
    session_id = (
        get_conversation_id()
        or getattr(input_data, "thread_id", None)
        or str(uuid.uuid4())
    )
    messages = input_data.messages
    user_message = messages[-1].content if messages else ""

    with span(
        "supervisor.stream",
        session_id=session_id,
        input=user_message,
        metadata=outbound_metadata(),
    ):
        async for event in _executar_supervisor_stream(input_data, session_id):
            yield event


async def _executar_supervisor_stream(input_data, session_id: str):
    messages = input_data.messages
    if not messages:
        user_message = ""
    else:
        user_message = messages[-1].content

    assistant_id = str(uuid.uuid4())

    # Início da mensagem do assistant
    yield TextMessageStartEvent(
        type=EventType.TEXT_MESSAGE_START, message_id=assistant_id, role="assistant"
    )

    # Mensagem inicial
    yield TextMessageContentEvent(
        type=EventType.TEXT_MESSAGE_CONTENT,
        message_id=assistant_id,
        delta="Analisando sua solicitação...\n\n",
    )

    # Estado inicial
    state = {"user_query": user_message, "responses": []}
    yield StateUpdateEvent(state=state)

    # Classificação de agentes
    classifications = await classifique_intencao_do_usuario(
        user_message, callbacks=callbacks()
    )
    agentes = [c["agent"] for c in classifications]
    yield TextMessageContentEvent(
        type=EventType.TEXT_MESSAGE_CONTENT,
        message_id=assistant_id,
        delta=f"Agentes selecionados: {', '.join(agentes)}\n\n",
    )

    # Atualiza state
    state["agents"] = agentes
    yield StateUpdateEvent(state=state)

    respostas = []
    for c in classifications:
        agent_name = c["agent"]

        yield TextMessageContentEvent(
            type=EventType.TEXT_MESSAGE_CONTENT,
            message_id=assistant_id,
            delta=f"Chamando agente: {agent_name}...\n",
        )

        resposta = await request_agent(c["query"], AGENTS[agent_name], session_id)
        respostas.append(resposta)

        yield TextMessageContentEvent(
            type=EventType.TEXT_MESSAGE_CONTENT,
            message_id=assistant_id,
            delta=f"{agent_name} respondeu\n\n",
        )

        # Atualiza state após cada agente
        state["responses"].append({agent_name: resposta})
        yield StateUpdateEvent(state=state)

    resposta_final = "\n\n".join(respostas)

    yield TextMessageContentEvent(
        type=EventType.TEXT_MESSAGE_CONTENT,
        message_id=assistant_id,
        delta=f"Resultado final:\n\n{resposta_final}",
    )

    # Fim da mensagem
    yield TextMessageEndEvent(type=EventType.TEXT_MESSAGE_END, message_id=assistant_id)
