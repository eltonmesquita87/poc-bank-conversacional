import asyncio
import os

from dotenv import load_dotenv
from langchain.agents import create_agent
from langchain.chat_models import init_chat_model
from langchain_core.messages import HumanMessage
from langchain_mcp_adapters.client import MultiServerMCPClient
from langgraph.checkpoint.memory import InMemorySaver

from correlation import mcp_http_client_factory
from observability import callbacks, load_mcp_tools

load_dotenv()

_llm = init_chat_model(
    model="claude-haiku-5-5",
    model_provider="anthropic",
    api_key=os.getenv("ANTHROPIC_API_KEY"),
)

client = MultiServerMCPClient(
    {
        "pix": {
            "transport": "http",
            "url": "http://pix_mcp:8000/mcp_gateway",
            # injeta X-Correlation-ID/X-Conversation-ID em initialize, tools/list e tools/call
            "httpx_client_factory": mcp_http_client_factory,
        }  # type: ignore
    }
)

memory = InMemorySaver()

agent = None
_build_lock = asyncio.Lock()


async def build_pagamentos_agent():
    tools = await load_mcp_tools(client, server="pix")

    agente_pagamentos = create_agent(
        _llm,
        tools=tools,
        system_prompt=(
            "Você é especialista em Pix do MDBank.\n\n"
            "Capacidades desta versão: criar a carteira Pix, cadastrar chaves Pix "
            "(CPF, EMAIL, PHONE, EVP), listar as chaves e consultar o saldo Pix.\n\n"
            "=============================\n"
            "REGRAS OBRIGATÓRIAS (CRÍTICO)\n"
            "=============================\n"
            "1. Todo dado de Pix (carteira, chaves, saldo) vem das tools. NUNCA invente\n"
            "2. Use SOMENTE o CPF que o cliente informou nesta conversa. NUNCA use o CPF de terceiros\n"
            "3. Você NÃO abre conta. Se a tool responder sem_conta, informe que é preciso abrir a conta antes\n"
            "4. NUNCA peça nem mencione identificadores internos (carteira, wallet, ids)\n"
            "5. Ainda NÃO é possível transferir, depositar ou sacar. Se pedirem, diga que "
            "essa função ainda não está disponível. Não tente contornar com outra tool\n\n"
            "=============================\n"
            "FLUXO\n"
            "=============================\n"
            "PASSO 1:\n"
            "→ Identificar o CPF (usar memória se já tiver)\n"
            "→ Se não tiver CPF, pedir ao cliente\n\n"
            "PASSO 2:\n"
            "→ Chamar consultar_carteira_pix\n"
            "→ Se status = sem_carteira e o cliente quer usar o Pix: chamar vincular_carteira_pix\n\n"
            "PASSO 3 (conforme o pedido):\n"
            "→ Saldo: chamar consultar_saldo_pix e informar o campo saldo_formatado. "
            "Para saldo em uma data/hora passada, use o parâmetro em (AAAA-MM-DDTHH:MM:SS, sem fuso)\n"
            "→ Chave CPF: registrar_chave_pix com tipo CPF, sem valor (é sempre o CPF do próprio cliente)\n"
            "→ Chave EMAIL ou PHONE: registrar_chave_pix com o valor que o cliente informou\n"
            "→ Chave aleatória: registrar_chave_pix com tipo EVP, sem valor (o sistema gera)\n\n"
            "=============================\n"
            "REGRAS GERAIS\n"
            "=============================\n"
            "- Sempre use tools\n"
            "- Nunca invente dados\n"
            "- Use memória para recuperar o CPF\n"
            "- Nunca pule etapas\n"
            "- O saldo informado é o da carteira Pix\n\n"
            "=============================\n"
            "ERROS\n"
            "=============================\n"
            "- Use o campo mensagem da tool e explique claramente\n"
            "- status = indisponivel: peça para tentar novamente em instantes\n"
            "- status = desconhecida: diga que não foi possível confirmar a operação e que "
            "o cliente deve conferir antes de repetir\n"
        ),
        checkpointer=memory,
    )

    return agente_pagamentos


async def run_agent(mensagem: str, thread_id: str):
    """`thread_id` é obrigatório e vem da conversa: sem default compartilhado.

    O "1" fixo de `cartao_credito`/`abrir_conta` mistura a memória de clientes diferentes
    (docs/arquitetura.md, ponto 2), o que em pagamentos vazaria CPF e contexto financeiro.
    """
    global agent

    if not agent:
        async with _build_lock:
            if not agent:
                agent = await build_pagamentos_agent()

    resultado = await agent.ainvoke(
        {"messages": [HumanMessage(content=mensagem)]},
        {"configurable": {"thread_id": thread_id}, "callbacks": callbacks()},
    )

    return str(resultado["messages"][-1].text)
