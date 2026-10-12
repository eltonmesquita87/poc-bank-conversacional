import logging
import httpx
import uuid

from langgraph.graph import StateGraph, START, END
from langgraph.types import Send
from typing import TypedDict, Annotated
from operator import add

from a2a.client import A2ACardResolver, ClientFactory, ClientConfig
from a2a.types import Message, Part, Role, TextPart

from ag_ui.core import (
    EventType,
    TextMessageStartEvent,
    TextMessageContentEvent,
    TextMessageEndEvent
)
from pydantic import BaseModel

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
    "abrir_conta": "http://abrir_conta_agent:8000"
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


async def request_agent(message: str, agent_url: str) -> str:

    if agent_url not in CLIENT_CACHE:
        logger.info(f"Descobrindo AgentCard em {agent_url}")

        resolver = A2ACardResolver(
            httpx_client=HTTPX_CLIENT,
            base_url=agent_url,
        )

        agent_card = await resolver.get_agent_card()
        logger.info(f"Agent encontrado: {agent_card.name}")

        config = ClientConfig(
            httpx_client=HTTPX_CLIENT,
            streaming=False
        )
        factory = ClientFactory(config)
        CLIENT_CACHE[agent_url] = factory.create(agent_card)

    client = CLIENT_CACHE[agent_url]

    msg = Message(
        role=Role.user,
        message_id=str(uuid.uuid4()),
        parts=[Part(root=TextPart(text=message))],
    )

    logger.info(f"Enviando mensagem para agente: {message}")

    async for event in client.send_message(msg):
        if isinstance(event, Message):
            for part in event.parts:
                if part.root.kind == "text":
                    return part.root.text

    return "Sem resposta do agente."

# -----------------------------
# ROUTER
# -----------------------------


async def no_de_roteamento(state: State):
    query = state.get("query", "")
    classifications = await classifique_intencao_do_usuario(query)
    logger.info(f"Classificação: {classifications}")
    return [Send(c["agent"], {"query": c["query"]}) for c in classifications]

# -----------------------------
# NODE CARTAO
# -----------------------------


async def cartao_credito_node(state: State):
    query = state.get("query", "")
    logger.info("Executando agente CARTAO_CREDITO")
    resposta = await request_agent(query, AGENTS["cartao_credito"])
    return {"responses": [resposta]}

# -----------------------------
# NODE ABRIR CONTA
# -----------------------------


async def abrir_conta_node(state: State):
    query = state.get("query", "")
    logger.info("Executando agente ABRIR_CONTA")
    resposta = await request_agent(query, AGENTS["abrir_conta"])
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


async def executar_supervisor(texto_usuario: str):
    input_state: State = {"query": texto_usuario, "responses": []}
    result = await graph.ainvoke(input_state)
    return "\n\n".join(result["responses"])

# -----------------------------
# EXECUTOR DO SUPERVISOR (STREAMING COM STATE)
# -----------------------------


async def executar_supervisor_stream(input_data):
    """
    Retorna eventos para AG-UI, incluindo state compartilhado.
    """
    messages = input_data.messages
    if not messages:
        user_message = ""
    else:
        user_message = messages[-1].content

    assistant_id = str(uuid.uuid4())

    # Início da mensagem do assistant
    yield TextMessageStartEvent(
        type=EventType.TEXT_MESSAGE_START,
        message_id=assistant_id,
        role="assistant"
    )

    # Mensagem inicial
    yield TextMessageContentEvent(
        type=EventType.TEXT_MESSAGE_CONTENT,
        message_id=assistant_id,
        delta="Analisando sua solicitação...\n\n"
    )

    # Estado inicial
    state = {"user_query": user_message, "responses": []}
    yield StateUpdateEvent(state=state)

    # Classificação de agentes
    classifications = await classifique_intencao_do_usuario(user_message)
    agentes = [c["agent"] for c in classifications]
    yield TextMessageContentEvent(
        type=EventType.TEXT_MESSAGE_CONTENT,
        message_id=assistant_id,
        delta=f"Agentes selecionados: {', '.join(agentes)}\n\n"
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
            delta=f"Chamando agente: {agent_name}...\n"
        )

        resposta = await request_agent(c["query"], AGENTS[agent_name])
        respostas.append(resposta)

        yield TextMessageContentEvent(
            type=EventType.TEXT_MESSAGE_CONTENT,
            message_id=assistant_id,
            delta=f"{agent_name} respondeu\n\n"
        )

        # Atualiza state após cada agente
        state["responses"].append({agent_name: resposta})
        yield StateUpdateEvent(state=state)

    resposta_final = "\n\n".join(respostas)

    yield TextMessageContentEvent(
        type=EventType.TEXT_MESSAGE_CONTENT,
        message_id=assistant_id,
        delta=f"Resultado final:\n\n{resposta_final}"
    )

    # Fim da mensagem
    yield TextMessageEndEvent(
        type=EventType.TEXT_MESSAGE_END,
        message_id=assistant_id
    )
