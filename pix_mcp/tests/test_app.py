"""Fumaça do app FastMCP: exige o fastmcp instalado (o venv do pix_mcp tem)."""

import asyncio
import os
import tempfile

import pytest

pytest.importorskip("fastmcp")

# build_service() lê o ambiente no import
os.environ.setdefault("PIX_SERVICE_URL", "http://pix-service.invalido:8089")
os.environ.setdefault(
    "PIX_DB_FILE", os.path.join(tempfile.mkdtemp(prefix="pixmcp-"), "pix_db.json")
)

import app  # noqa: E402
from starlette.testclient import TestClient  # noqa: E402

TOOLS = {
    "vincular_carteira_pix",
    "consultar_carteira_pix",
    "registrar_chave_pix",
    "consultar_saldo_pix",
}


def test_expoe_somente_as_tools_da_fase_2():
    tools = asyncio.run(app.mcp.list_tools())
    assert {t.name for t in tools} == TOOLS


def test_nenhuma_tool_aceita_wallet_id_do_llm():
    for tool in asyncio.run(app.mcp.list_tools()):
        campos = set(tool.parameters.get("properties", {}))
        assert "cpf" in campos
        assert not {c for c in campos if "wallet" in c.lower()}, tool.name


def test_rota_tools_para_o_bfa_deriva_o_schema_da_assinatura():
    cliente = TestClient(app.mcp.http_app(path="/mcp_gateway"))
    resposta = cliente.get("/tools")
    assert resposta.status_code == 200
    por_nome = {t["name"]: t for t in resposta.json()}
    assert set(por_nome) == TOOLS

    chave = por_nome["registrar_chave_pix"]
    assert set(chave["inputSchema"]["properties"]) == {"cpf", "tipo", "valor"}
    assert chave["inputSchema"]["required"] == ["cpf", "tipo"]
    # o BFA indexa tags e exemplos (BM25): precisam chegar preenchidos
    assert "pix" in chave["annotations"]["tags"]
    assert chave["annotations"]["examples"]


def test_exige_pix_service_url_sem_default(monkeypatch):
    monkeypatch.delenv("PIX_SERVICE_URL")
    with pytest.raises(RuntimeError, match="PIX_SERVICE_URL"):
        app.build_service()
