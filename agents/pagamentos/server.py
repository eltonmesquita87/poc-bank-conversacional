import atexit
from a2a.server.apps import A2AStarletteApplication
from a2a.server.request_handlers import DefaultRequestHandler
from a2a.server.tasks import InMemoryTaskStore
from a2a.types import AgentCapabilities, AgentCard, AgentSkill
from correlation import CorrelationMiddleware, setup_logging
from observability import flush
from executor import PagamentosExecutor

setup_logging("pagamentos_agent")

# -----------------------
# Definição do skill
# -----------------------
skill = AgentSkill(
    id="pagamentos_pix",
    name="Pagamentos Pix MDBank",
    description="Ajuda clientes com a carteira Pix: ativar o Pix, cadastrar chaves e consultar o saldo.",
    tags=["pix", "carteira", "chave", "saldo", "pagamento"],
    examples=[
        "quero usar o pix",
        "cadastrar minha chave pix cpf",
        "registrar o email joao@exemplo.com como chave pix",
        "qual é o meu saldo pix?",
        "quais são as minhas chaves pix?",
    ],
)

# -----------------------
# Agent Card
# -----------------------
agent_card = AgentCard(
    name="Agente de Pagamentos MDBank",
    description="Especialista em Pix do MDBank: carteira, chaves e saldo.",
    url="http://pagamentos_agent:8000/",
    default_input_modes=["text"],
    default_output_modes=["text"],
    skills=[skill],
    version="1.0.0",
    capabilities=AgentCapabilities(),
)
# -----------------------
# Request Handler
# -----------------------
handler = DefaultRequestHandler(
    agent_executor=PagamentosExecutor(),
    task_store=InMemoryTaskStore(),
)

# -----------------------
# A2A Application
# -----------------------
server = A2AStarletteApplication(
    http_handler=handler,
    agent_card=agent_card,
)

# EXPOSIÇÃO DO APP PARA O UVICORN
app = server.build()
# Adicionado por último = mais externo: loga http.* e propaga X-Correlation-ID.
app.add_middleware(CorrelationMiddleware)
atexit.register(flush)  # envia traces pendentes ao Langfuse ao encerrar
