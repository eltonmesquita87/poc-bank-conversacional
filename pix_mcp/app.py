import os
from typing import Any, Dict, Optional

from dotenv import load_dotenv
from fastmcp import FastMCP
from starlette.requests import Request
from starlette.responses import JSONResponse

from client import PixServiceClient
from contas import RecursosContaGateway
from correlation import setup_logging
from mcp_logging import CorrelationMcpMiddleware
from service import PixService
from store import PixStore

load_dotenv()
setup_logging("pix_mcp")


def _exigir_env(nome: str) -> str:
    valor = os.getenv(nome, "").strip()
    if not valor:
        # Sem default de propósito: a porta do pix-service diverge entre README e código (D-10).
        raise RuntimeError(f"Variável de ambiente obrigatória ausente: {nome}")
    return valor


def build_service() -> PixService:
    return PixService(
        client=PixServiceClient(
            _exigir_env("PIX_SERVICE_URL"),
            timeout=float(os.getenv("PIX_HTTP_TIMEOUT", "5")),
        ),
        store=PixStore(os.getenv("PIX_DB_FILE", "/app/pix_db.json")),
        contas=RecursosContaGateway(
            os.getenv("RECURSOS_MCP_URL", "http://recursos:8000/mcp_gateway"),
            timeout=float(os.getenv("PIX_HTTP_TIMEOUT", "5")),
        ),
        segredo_user_id=os.getenv("PIX_USER_ID_SECRET", "mdbank-dev-nao-usar-em-producao"),
        max_chaves=int(os.getenv("PIX_MAX_CHAVES", "5")),
        validar_dv_cpf=os.getenv("PIX_VALIDAR_DV_CPF", "true").lower() != "false",
    )


mcp = FastMCP("PixService", middleware=[CorrelationMcpMiddleware()])
service = build_service()

# -------------------------
# TOOLS
# O agente só informa o CPF do cliente. O walletId é resolvido aqui e nunca sai do pix_mcp.
# -------------------------


@mcp.tool(
    description=(
        "Cria a carteira Pix do cliente a partir do CPF. Só funciona para quem já tem conta "
        "no MD Bank; se já existir carteira, devolve a existente."
    ),
    tags=set(["pix", "carteira", "conta", "criar"]),
    meta={"examples": [
            "quero usar o pix",
            "criar minha carteira pix",
            "ativar pix na minha conta",
        ]},
)
async def vincular_carteira_pix(cpf: str) -> Dict[str, Any]:
    return await service.vincular_carteira(cpf)


@mcp.tool(
    description="Consulta se o cliente tem carteira Pix e quais chaves já cadastrou.",
    tags=set(["pix", "carteira", "chaves", "consulta"]),
    meta={"examples": ["quais são minhas chaves pix?", "tenho pix ativo?"]},
)
async def consultar_carteira_pix(cpf: str) -> Dict[str, Any]:
    return await service.consultar_carteira(cpf)


@mcp.tool(
    description=(
        "Cadastra uma chave Pix na carteira do cliente. tipo: CPF, EMAIL, PHONE ou EVP. "
        "CPF só pode ser o do próprio titular (valor opcional). EVP (chave aleatória) é gerada "
        "pelo sistema: não informe valor. EMAIL e PHONE exigem o valor."
    ),
    tags=set(["pix", "chave", "cadastrar", "registrar"]),
    meta={"examples": [
            "cadastrar minha chave pix cpf",
            "registrar o email joao@exemplo.com como chave pix",
            "criar uma chave aleatória",
        ]},
)
async def registrar_chave_pix(
    cpf: str, tipo: str, valor: Optional[str] = None
) -> Dict[str, Any]:
    return await service.registrar_chave(cpf, tipo, valor)


@mcp.tool(
    description=(
        "Consulta o saldo Pix do cliente. Sem 'em', devolve o saldo atual. Com 'em' "
        "(AAAA-MM-DDTHH:MM:SS, sem fuso), devolve o saldo considerando só o que ocorreu antes."
    ),
    tags=set(["pix", "saldo", "consulta", "extrato"]),
    meta={"examples": [
            "qual meu saldo pix?",
            "quanto eu tinha ontem às 10h?",
            "ver saldo da carteira",
        ]},
)
async def consultar_saldo_pix(cpf: str, em: Optional[str] = None) -> Dict[str, Any]:
    return await service.consultar_saldo(cpf, em)


# -------------------------
# /tools (consumido pelo BFA). O inputSchema vem da própria tool, sem mapa manual
# (em recursos ele é escrito à mão e pode divergir da assinatura).
# -------------------------
@mcp.custom_route("/tools", methods=["GET"])
async def list_tools(request: Request) -> JSONResponse:
    try:
        tools = await mcp.list_tools()
        return JSONResponse(
            [
                {
                    "name": tool.name,
                    "description": tool.description or "",
                    "inputSchema": tool.parameters,
                    "annotations": {
                        "tags": sorted(tool.tags or []),
                        "examples": (tool.meta or {}).get("examples", []),
                    },
                }
                for tool in tools
            ]
        )
    except Exception as e:
        print("ERRO /tools:", e)
        return JSONResponse(
            {"error": "failed to list tools", "details": str(e)}, status_code=500
        )
