"""Deriva do registro de agentes.

Adicionar um agente exige mexer em vários lugares (supervisor: AGENTS, nó do grafo, prompt do
router; BFA: AGENT_ENDPOINTS; compose). Esses testes quebram quando um deles é esquecido
(docs/arquitetura.md, ponto de atenção 1).
"""

import ast
import os
import re
from pathlib import Path

import pytest

# init_chat_model exige uma chave no import; nenhum teste chama o LLM.
os.environ.setdefault("ANTHROPIC_API_KEY", "sk-ant-teste-nao-usada")

from src import services  # noqa: E402

RAIZ = Path(__file__).resolve().parents[2]


def _lista_de_urls(arquivo: Path, variavel: str) -> list[str]:
    arvore = ast.parse(arquivo.read_text(encoding="utf-8"))
    for no in ast.walk(arvore):
        if isinstance(no, ast.Assign) and any(
            isinstance(t, ast.Name) and t.id == variavel for t in no.targets
        ):
            return [e.value for e in no.value.elts]
    raise AssertionError(f"{variavel} não encontrada em {arquivo}")


def test_todo_agente_registrado_tem_no_no_grafo():
    nos = set(services.graph.get_graph().nodes) - {"__start__", "__end__"}
    assert nos == set(services.AGENTS)


def test_todo_agente_aparece_no_prompt_do_router():
    prompt = (RAIZ / "supervisor" / "src" / "agents.py").read_text(encoding="utf-8")
    for nome in services.AGENTS:
        assert re.search(rf"^- {nome}:", prompt, re.MULTILINE), (
            f"{nome} falta na lista 'Agentes disponíveis' do router"
        )


def test_todo_agente_e_descoberto_pelo_bfa():
    urls = set(_lista_de_urls(RAIZ / "bfa" / "discovery.py", "AGENT_ENDPOINTS"))
    assert urls == set(services.AGENTS.values())


def test_todo_agente_esta_no_compose():
    compose = (RAIZ / "docker-compose.yml").read_text(encoding="utf-8")
    for url in services.AGENTS.values():
        host = re.match(r"http://([^:/]+):", url).group(1)
        assert re.search(rf"^  {host}:", compose, re.MULTILINE), f"{host} falta no compose"


def test_servidores_mcp_do_compose_estao_no_bfa():
    urls = set(_lista_de_urls(RAIZ / "bfa" / "mcp_discovery.py", "MCP_ENDPOINTS"))
    assert {"http://recursos:8000", "http://pix_mcp:8000"} <= urls


def test_o_fallback_do_router_e_um_agente_conhecido_sem_acao_financeira():
    assert services.AGENTE_FALLBACK in services.AGENTS
    assert services.AGENTE_FALLBACK != "pagamentos_pix"


# -----------------------------
# Filtro de agentes inventados pelo router
# -----------------------------


def test_filtro_mantem_os_conhecidos_na_ordem():
    cls = [
        {"query": "q", "agent": "abrir_conta"},
        {"query": "q", "agent": "pagamentos_pix"},
    ]
    assert services.somente_agentes_conhecidos(cls, "q") == cls


def test_filtro_descarta_agente_inventado():
    cls = [{"query": "q", "agent": "agente_fantasma"}, {"query": "q", "agent": "pagamentos_pix"}]
    assert services.somente_agentes_conhecidos(cls, "q") == [cls[1]]


@pytest.mark.parametrize("cls", [[], [{"query": "q", "agent": "so_fantasma"}], [{"query": "q"}]])
def test_filtro_sem_nenhum_conhecido_cai_no_fallback(cls):
    assert services.somente_agentes_conhecidos(cls, "oi") == [
        {"query": "oi", "agent": services.AGENTE_FALLBACK}
    ]
