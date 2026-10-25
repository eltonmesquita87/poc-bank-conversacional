import asyncio
from types import SimpleNamespace

import executor
from a2a.types import TextPart

CORR = "corr-aaaa-1111"
CONV_A = "conv-aaaa-1111"
CONV_B = "conv-bbbb-2222"


class FakeQueue:
    def __init__(self):
        self.eventos = []

    async def enqueue_event(self, evento):
        self.eventos.append(evento)


def contexto(texto, *, correlation=CORR, conversation=CONV_A):
    meta = {}
    if correlation:
        meta["correlation_id"] = correlation
    if conversation:
        meta["conversation_id"] = conversation
    return SimpleNamespace(
        message=SimpleNamespace(metadata=meta),
        call_context=None,
        task_id="t1",
        context_id="c1",
        get_user_input=lambda: texto,
    )


def executa(monkeypatch, ctx):
    chamadas = []

    async def run_agent_falso(mensagem, thread_id):
        chamadas.append({"mensagem": mensagem, "thread_id": thread_id})
        return "ok"

    monkeypatch.setattr(executor, "run_agent", run_agent_falso)
    fila = FakeQueue()
    asyncio.run(executor.PagamentosExecutor().execute(ctx, fila))
    return chamadas, fila


def test_memoria_do_agente_e_por_conversa(monkeypatch):
    # Em cartao_credito/abrir_conta o thread_id cai no default "1" e mistura clientes.
    chamadas_a, _ = executa(monkeypatch, contexto("meu saldo", conversation=CONV_A))
    chamadas_b, _ = executa(monkeypatch, contexto("meu saldo", conversation=CONV_B))
    assert chamadas_a[0]["thread_id"] == CONV_A
    assert chamadas_b[0]["thread_id"] == CONV_B
    assert "1" not in (chamadas_a[0]["thread_id"], chamadas_b[0]["thread_id"])


def test_sem_conversation_id_usa_o_id_do_turno_e_nunca_um_valor_compartilhado(monkeypatch):
    chamadas, _ = executa(monkeypatch, contexto("oi", conversation=None))
    assert chamadas[0]["thread_id"] == CORR


def test_responde_com_o_texto_do_agente(monkeypatch):
    _, fila = executa(monkeypatch, contexto("oi"))
    assert len(fila.eventos) == 1
    parte = fila.eventos[0].parts[0].root
    assert isinstance(parte, TextPart) and parte.text == "ok"
