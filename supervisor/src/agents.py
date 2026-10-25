import logging
import os
import time
from typing import Any, Dict, List

from correlation import log_event, safe_payload
from dotenv import load_dotenv
from langchain.agents import create_agent
from langchain.chat_models import init_chat_model
from langchain_core.messages import HumanMessage
from langchain_core.output_parsers import JsonOutputParser
from langgraph.checkpoint.memory import InMemorySaver
from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)
load_dotenv()

_llm = init_chat_model(
    model="claude-haiku-5-5",
    model_provider="anthropic",
    api_key=os.getenv("ANTHROPIC_API_KEY"),
)

memory = InMemorySaver()


class RouterOutput(BaseModel):
    agents: List[str] = Field(
        description="Lista de agentes que devem responder a pergunta"
    )


parser = JsonOutputParser(pydantic_object=RouterOutput)


async def build_router_agent():
    agent = create_agent(
        _llm,
        tools=[],
        system_prompt=f"""
Você é o roteador de agentes do MDBank, um banco digital moderno, seguro e confiável, especializado em fornecer soluções financeiras personalizadas para cada cliente.

Objetivo do MDBank:
- Auxiliar clientes na abertura de contas, emissão de cartões e uso do Pix de forma rápida, segura e transparente.
- Garantir que cada cliente receba produtos financeiros adequados ao seu perfil.
- Fornecer informações claras sobre serviços, produtos e processos bancários.
- Evitar informações incorretas, inconsistentes ou inventadas.

Função do roteador:
- Identificar a intenção do cliente de forma precisa.
- Selecionar os agentes apropriados (cartao_credito, abrir_conta, pagamentos_pix) com base no histórico do cliente e no contexto da conversa.
- Aplicar regras de negócios do MDBank de maneira consistente.

Agentes disponíveis:
- cartao_credito: responsável por gerenciar solicitações relacionadas a cartões de crédito.
- abrir_conta: responsável por auxiliar na abertura de contas correntes e digitais.
- pagamentos_pix: responsável pelo Pix: ativar a carteira Pix, cadastrar chaves Pix e consultar o saldo Pix.

Regras IMPORTANTES:
1. Utilize sempre o contexto da conversa (memória) e histórico do cliente.
2. Se o cliente já possui conta, NÃO chame abrir_conta novamente.
3. Uma pergunta pode exigir mais de um agente.
4. Nunca invente informações ou dados de clientes.
5. Informe claramente se alguma ação não puder ser realizada (ex: cliente já possui conta, dados incompletos, requisitos não atendidos).
6. Ao lidar com solicitações sensíveis (dados de conta, informações financeiras pessoais), sempre oriente o cliente a acessar o aplicativo oficial ou entrar em contato com suporte seguro.
7. Mantenha linguagem profissional, educada, objetiva e empática, transmitindo confiança de banco real.
8. Para onboarding, forneça explicações sobre o motivo de abrir conta, benefícios do MDBank, e passos que o cliente precisa seguir, caso ele esteja iniciando a relação com o banco.
9. O Pix exige conta no MDBank. Se o cliente quer usar o Pix e ainda não tem conta, selecione SOMENTE abrir_conta neste turno; nunca selecione pagamentos_pix junto com abrir_conta.
10. Se o cliente está no meio de um assunto de Pix (por exemplo, respondendo o CPF, e-mail ou telefone que o agente pediu), mantenha pagamentos_pix.


- JSON deve ser válido e conter apenas os agentes selecionados.
- Evite qualquer texto fora do JSON no output.

Exemplo de interpretação do prompt:
- Cliente pede cartão, mas não tem conta → selecione abrir_conta primeiro.
- Cliente já possui conta → selecione cartao_credito se aplicável.
- Cliente quer saldo, chave ou carteira Pix e já possui conta → selecione pagamentos_pix.
- Cliente quer usar o Pix, mas não tem conta → selecione apenas abrir_conta.
- Cliente pergunta sobre benefícios do banco → selecione abrir_conta ou ambos se houver necessidade de interação com múltiplos agentes.

Responda SEMPRE em JSON no formato:
{parser.get_format_instructions()!r}
""",
        checkpointer=memory,
    )
    return agent


async def classifique_intencao_do_usuario(
    query: str, thread_id: str = "1", callbacks: Any = None
) -> List[Dict[str, Any]]:
    agent = await build_router_agent()
    started = time.perf_counter()
    log_event(logger, "router_llm", "client", "request", payload=safe_payload(query))

    try:
        resultado = await agent.ainvoke(
            {"messages": [HumanMessage(content=query)]},
            {"configurable": {"thread_id": thread_id}, "callbacks": callbacks},
        )

        resposta_texto = str(resultado["messages"][-1].text)

        parsed = parser.parse(resposta_texto)

        agentes = parsed.get("agents", [])

        log_event(
            logger,
            "router_llm",
            "client",
            "response",
            agents=agentes,
            payload=safe_payload(resposta_texto),
            duration_ms=round((time.perf_counter() - started) * 1000, 1),
        )

        return [{"query": query, "agent": agente} for agente in agentes]

    except Exception as e:
        # Falha de roteamento não derruba a requisição: cai no fallback para abrir_conta.
        log_event(
            logger,
            "router_llm",
            "client",
            "error",
            error=f"{type(e).__name__}: {e}",
            fallback="abrir_conta",
            duration_ms=round((time.perf_counter() - started) * 1000, 1),
        )
        return [{"query": query, "agent": "abrir_conta"}]
