"""RecursosContaGateway contra um servidor MCP real (HTTP), no formato de `recursos`.

Sobe um FastMCP com a tool `consultar_conta` numa thread/uvicorn local, como o container
`recursos` faz (`--path /mcp_gateway`). Cobre sessão HTTP, formato do retorno, variantes do CPF
e propagação dos headers de correlação, que um dublê não valida.
"""

import asyncio
import socket
import threading
import time

import pytest

pytest.importorskip("fastmcp")
uvicorn = pytest.importorskip("uvicorn")

from contas import ContaIndisponivel, RecursosContaGateway  # noqa: E402
from correlation import bind  # noqa: E402
from fastmcp import FastMCP  # noqa: E402
from fastmcp.server.dependencies import get_http_headers  # noqa: E402

CORR = "corr-aaaa-1111"
CONV = "conv-aaaa-1111"

# Como em recursos/db.json: chaves só com dígitos e formatadas convivem.
CONTAS = {"52998224725", "111.444.777-35"}
visto: dict = {"consultas": [], "headers": []}


def _porta_livre() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@pytest.fixture(scope="module")
def url():
    mcp = FastMCP("ContaFake")

    @mcp.tool
    async def consultar_conta(cpf: str):
        visto["consultas"].append(cpf)
        visto["headers"].append(get_http_headers(include_all=True))
        return {"existe": cpf in CONTAS}

    porta = _porta_livre()
    config = uvicorn.Config(
        mcp.http_app(path="/mcp_gateway"), host="127.0.0.1", port=porta, log_level="error"
    )
    server = uvicorn.Server(config)
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    for _ in range(100):
        if server.started:
            break
        time.sleep(0.05)
    assert server.started, "servidor MCP de teste não subiu"
    yield f"http://127.0.0.1:{porta}/mcp_gateway"
    server.should_exit = True
    thread.join(timeout=5)


@pytest.fixture(autouse=True)
def _limpa():
    visto["consultas"].clear()
    visto["headers"].clear()


def run(coro):
    return asyncio.run(coro)


def test_encontra_conta_gravada_so_com_digitos(url):
    assert run(RecursosContaGateway(url).existe("529.982.247-25")) is True
    # tentou a forma bruta (formatada) primeiro e achou a de dígitos na sequência
    assert visto["consultas"] == ["529.982.247-25", "52998224725"]


def test_encontra_conta_gravada_formatada_mesmo_recebendo_so_digitos(url):
    assert run(RecursosContaGateway(url).existe("11144477735")) is True
    assert visto["consultas"] == ["11144477735", "111.444.777-35"]


def test_para_na_primeira_variante_que_existe(url):
    assert run(RecursosContaGateway(url).existe("52998224725")) is True
    assert visto["consultas"] == ["52998224725"]


def test_cliente_sem_conta(url):
    assert run(RecursosContaGateway(url).existe("39053344705")) is False
    # todas as variantes tentadas (a bruta é igual aos dígitos aqui, então são 2)
    assert visto["consultas"] == ["39053344705", "390.533.447-05"]


def test_propaga_os_ids_de_correlacao_para_recursos(url):
    async def main():
        with bind(CORR, CONV):
            return await RecursosContaGateway(url).existe("52998224725")

    assert run(main()) is True
    headers = {k.lower(): v for k, v in visto["headers"][0].items()}
    assert headers["x-correlation-id"] == CORR
    assert headers["x-conversation-id"] == CONV


def test_recursos_fora_do_ar_vira_conta_indisponivel():
    gateway = RecursosContaGateway(f"http://127.0.0.1:{_porta_livre()}/mcp_gateway", timeout=1)
    with pytest.raises(ContaIndisponivel):
        run(gateway.existe("52998224725"))
