import logging
import os
from typing import List, Dict, Any

from dotenv import load_dotenv
from pydantic import BaseModel, Field

from langchain.agents import create_agent
from langchain.chat_models import init_chat_model
from langchain_core.messages import HumanMessage
from langchain_core.output_parsers import JsonOutputParser
from langgraph.checkpoint.memory import InMemorySaver

logger = logging.getLogger(__name__)
load_dotenv()

_llm = init_chat_model(
    model="gpt-4o",
    api_key=os.getenv("OPENAI_API_KEY"),
    temperature=0
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
- Auxiliar clientes na abertura de contas e emissão de cartões de forma rápida, segura e transparente.
- Garantir que cada cliente receba produtos financeiros adequados ao seu perfil.
- Fornecer informações claras sobre serviços, produtos e processos bancários.
- Evitar informações incorretas, inconsistentes ou inventadas.

Função do roteador:
- Identificar a intenção do cliente de forma precisa.
- Selecionar os agentes apropriados (cartao_credito, abrir_conta) com base no histórico do cliente e no contexto da conversa.
- Aplicar regras de negócios do MDBank de maneira consistente.

Agentes disponíveis:
- cartao_credito: responsável por gerenciar solicitações relacionadas a cartões de crédito.
- abrir_conta: responsável por auxiliar na abertura de contas correntes e digitais.

Regras IMPORTANTES:
1. Utilize sempre o contexto da conversa (memória) e histórico do cliente.
2. Se o cliente já possui conta, NÃO chame abrir_conta novamente.
3. Uma pergunta pode exigir mais de um agente.
4. Nunca invente informações ou dados de clientes.
5. Informe claramente se alguma ação não puder ser realizada (ex: cliente já possui conta, dados incompletos, requisitos não atendidos).
6. Ao lidar com solicitações sensíveis (dados de conta, informações financeiras pessoais), sempre oriente o cliente a acessar o aplicativo oficial ou entrar em contato com suporte seguro.
7. Mantenha linguagem profissional, educada, objetiva e empática, transmitindo confiança de banco real.
8. Para onboarding, forneça explicações sobre o motivo de abrir conta, benefícios do MDBank, e passos que o cliente precisa seguir, caso ele esteja iniciando a relação com o banco.


- JSON deve ser válido e conter apenas os agentes selecionados.
- Evite qualquer texto fora do JSON no output.

Exemplo de interpretação do prompt:
- Cliente pede cartão, mas não tem conta → selecione abrir_conta primeiro.
- Cliente já possui conta → selecione cartao_credito se aplicável.
- Cliente pergunta sobre benefícios do banco → selecione abrir_conta ou ambos se houver necessidade de interação com múltiplos agentes.

Responda SEMPRE em JSON no formato:
{parser.get_format_instructions()!r}
""",
        checkpointer=memory,
    )
    return agent


async def classifique_intencao_do_usuario(
    query: str,
    thread_id: str = "1"
) -> List[Dict[str, Any]]:
    agent = await build_router_agent()

    try:
        resultado = await agent.ainvoke(
            {
                "messages": [HumanMessage(content=query)]
            },
            {
                "configurable": {
                    "thread_id": thread_id
                }
            }
        )

        resposta_texto = resultado["messages"][-1].content

        parsed = parser.parse(resposta_texto)

        agentes = parsed.get("agents", [])

        logger.info(f"Agentes selecionados: {agentes}")

        return [
            {
                "query": query,
                "agent": agente
            }
            for agente in agentes
        ]

    except Exception as e:
        logger.error(f"Erro no router: {e}")
        return [
            {
                "query": query,
                "agent": "abrir_conta"
            }
        ]
