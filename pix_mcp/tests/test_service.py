import asyncio
import json
from decimal import Decimal

import pytest
from client import PixServiceError
from contas import ContaIndisponivel
from domain import normalizar_chave, TipoChave
from service import PixService, formatar_brl
from store import PixStore

CPF = "52998224725"
CPF_FORMATADO = "529.982.247-25"
OUTRO_CPF = "11144477735"  # DV válido, diferente do titular


class FakeClient:
    """Dublê do PixServiceClient: grava as chamadas e devolve respostas programáveis."""

    def __init__(self):
        self.calls: list[tuple] = []
        self.proximo_id = 100
        self.erro_carteira: str | None = None
        self.erro_chave: str | None = None
        self.erro_saldo: str | None = None
        self.saldo = Decimal("1234.50")
        self.atraso = 0.0

    async def criar_carteira(self, user_id):
        self.calls.append(("criar_carteira", user_id))
        if self.atraso:
            await asyncio.sleep(self.atraso)
        if self.erro_carteira:
            raise PixServiceError(self.erro_carteira)
        self.proximo_id += 1
        return {"id": self.proximo_id, "userId": user_id, "balance": Decimal("0.00")}

    async def registrar_chave(self, wallet_id, tipo, valor):
        self.calls.append(("registrar_chave", wallet_id, tipo, valor))
        if self.erro_chave:
            raise PixServiceError(self.erro_chave)
        return {"id": 1, "walletId": wallet_id, "keyType": tipo, "keyValue": valor}

    async def consultar_saldo(self, wallet_id, em=None):
        self.calls.append(("consultar_saldo", wallet_id, em))
        if self.erro_saldo:
            raise PixServiceError(self.erro_saldo)
        return {"walletId": wallet_id, "balance": self.saldo}


class FakeContas:
    def __init__(self, existe=True):
        self._existe = existe
        self.consultados: list[str] = []
        self.indisponivel = False

    async def existe(self, cpf):
        self.consultados.append(cpf)
        if self.indisponivel:
            raise ContaIndisponivel("fora do ar")
        return self._existe


@pytest.fixture
def ctx(tmp_path):
    client, contas = FakeClient(), FakeContas()
    store = PixStore(str(tmp_path / "pix_db.json"))
    service = PixService(client, store, contas, segredo_user_id="seg", max_chaves=3)
    return service, client, contas, store


def run(coro):
    return asyncio.run(coro)


def vinculado(ctx):
    service, *_ = ctx
    assert run(service.vincular_carteira(CPF))["status"] == "criada"


# -----------------------------
# vincular_carteira
# -----------------------------


def test_vincular_sem_conta_nao_chama_o_pix_service(ctx):
    service, client, contas, _ = ctx
    contas._existe = False
    r = run(service.vincular_carteira(CPF))
    assert r["status"] == "sem_conta"
    assert client.calls == []


def test_vincular_cpf_invalido(ctx):
    service, client, *_ = ctx
    assert run(service.vincular_carteira("123"))["status"] == "cpf_invalido"
    assert client.calls == []


def test_vincular_conta_indisponivel_nao_cria_carteira(ctx):
    service, client, contas, _ = ctx
    contas.indisponivel = True
    assert run(service.vincular_carteira(CPF))["status"] == "indisponivel"
    assert client.calls == []


def test_vincular_cria_uma_vez_e_depois_devolve_a_existente(ctx):
    service, client, contas, _ = ctx
    r1 = run(service.vincular_carteira(CPF))
    r2 = run(service.vincular_carteira(CPF_FORMATADO))  # mesmo CPF, outra formatação
    assert (r1["status"], r2["status"]) == ("criada", "existente")
    assert [c[0] for c in client.calls] == ["criar_carteira"]
    assert len(contas.consultados) == 1  # o segundo nem precisa consultar a conta


def test_vincular_concorrente_cria_uma_unica_carteira(ctx):
    service, client, *_ = ctx
    client.atraso = 0.02

    async def main():
        return await asyncio.gather(*(service.vincular_carteira(CPF) for _ in range(5)))

    status = sorted(r["status"] for r in run(main()))
    assert status == ["criada"] + ["existente"] * 4
    assert len(client.calls) == 1


def test_user_id_enviado_e_hash_sem_pii_e_resposta_nao_expoe_wallet_id(ctx):
    service, client, *_ = ctx
    r = run(service.vincular_carteira(CPF))
    user_id = client.calls[0][1]
    assert user_id.startswith("mdb-") and CPF not in user_id
    texto = json.dumps(r)
    assert "wallet_id" not in texto and user_id not in texto and "101" not in texto


def test_vincular_propaga_erro_do_pix_service_sem_gravar(ctx):
    service, client, _, store = ctx
    client.erro_carteira = "desconhecida"
    assert run(service.vincular_carteira(CPF))["status"] == "desconhecida"
    assert store.carteira(CPF) is None


def test_vinculo_sobrevive_a_reinicio(ctx, tmp_path):
    service, client, contas, store = ctx
    vinculado(ctx)
    novo = PixService(
        client, PixStore(str(tmp_path / "pix_db.json")), contas, segredo_user_id="seg"
    )
    assert run(novo.consultar_carteira(CPF))["status"] == "ok"


# -----------------------------
# registrar_chave
# -----------------------------


def test_chave_exige_carteira(ctx):
    service, client, *_ = ctx
    assert run(service.registrar_chave(CPF, "EMAIL", "a@b.com"))["status"] == "sem_carteira"
    assert client.calls == []


def test_chave_tipo_invalido(ctx):
    vinculado(ctx)
    assert run(ctx[0].registrar_chave(CPF, "CNPJ", "x"))["status"] == "tipo_invalido"
    assert [c for c in ctx[1].calls if c[0] == "registrar_chave"] == []


def test_chave_cpf_do_titular_com_ou_sem_valor(ctx):
    service, client, *_ = ctx
    vinculado(ctx)
    r = run(service.registrar_chave(CPF_FORMATADO, "cpf"))  # tipo em minúsculas, sem valor
    assert r["status"] == "ok" and r["chave"] == {"tipo": "CPF", "valor": CPF}
    assert client.calls[-1] == ("registrar_chave", 101, "CPF", CPF)  # só dígitos, wallet interna


def test_chave_cpf_de_terceiro_e_recusada_na_tool(ctx):
    service, client, *_ = ctx
    vinculado(ctx)
    r = run(service.registrar_chave(CPF, "CPF", OUTRO_CPF))
    assert r["status"] == "chave_cpf_de_terceiro"
    assert [c for c in client.calls if c[0] == "registrar_chave"] == []


def test_chave_email_e_normalizado_antes_de_enviar(ctx):
    service, client, *_ = ctx
    vinculado(ctx)
    r = run(service.registrar_chave(CPF, "EMAIL", "  Ana@Example.COM "))
    assert r["status"] == "ok"
    assert client.calls[-1][2:] == ("EMAIL", "ana@example.com")


def test_chave_email_ou_telefone_exigem_valor(ctx):
    vinculado(ctx)
    assert run(ctx[0].registrar_chave(CPF, "EMAIL"))["status"] == "valor_obrigatorio"
    assert run(ctx[0].registrar_chave(CPF, "PHONE", "  "))["status"] == "valor_obrigatorio"


def test_chave_telefone_com_ddi_e_enviada_sem_ddi(ctx):
    service, client, *_ = ctx
    vinculado(ctx)
    run(service.registrar_chave(CPF, "PHONE", "+55 (11) 99999-8888"))
    assert client.calls[-1][2:] == ("PHONE", "11999998888")


def test_chave_invalida_nao_chega_ao_pix_service(ctx):
    service, client, *_ = ctx
    vinculado(ctx)
    r = run(service.registrar_chave(CPF, "EMAIL", "nao-e-email"))
    assert r["status"] == "chave_invalida"
    assert [c for c in client.calls if c[0] == "registrar_chave"] == []


def test_evp_e_sempre_gerado_e_ignora_o_valor_recebido(ctx):
    service, client, *_ = ctx
    vinculado(ctx)
    r = run(service.registrar_chave(CPF, "EVP", "valor-malicioso-do-llm"))
    assert r["status"] == "ok"
    gerado = r["chave"]["valor"]
    assert gerado != "valor-malicioso-do-llm"
    assert normalizar_chave(TipoChave.EVP, gerado) == gerado
    assert client.calls[-1][2:] == ("EVP", gerado)


def test_chave_repetida_nesta_carteira_nao_chama_de_novo(ctx):
    service, client, *_ = ctx
    vinculado(ctx)
    run(service.registrar_chave(CPF, "EMAIL", "ana@example.com"))
    r = run(service.registrar_chave(CPF, "EMAIL", "ANA@example.com"))
    assert r["status"] == "existente"
    assert len([c for c in client.calls if c[0] == "registrar_chave"]) == 1


def test_limite_de_chaves_por_carteira(ctx):
    service, client, *_ = ctx
    vinculado(ctx)
    for i in range(3):
        assert run(service.registrar_chave(CPF, "EMAIL", f"a{i}@example.com"))["status"] == "ok"
    assert run(service.registrar_chave(CPF, "EMAIL", "a9@example.com"))["status"] == "limite_de_chaves"
    assert len([c for c in client.calls if c[0] == "registrar_chave"]) == 3


@pytest.mark.parametrize("codigo", ["chave_ja_registrada", "desconhecida", "indisponivel"])
def test_falha_ao_registrar_nao_grava_a_chave_localmente(ctx, codigo):
    service, client, _, store = ctx
    vinculado(ctx)
    client.erro_chave = codigo
    assert run(service.registrar_chave(CPF, "EMAIL", "ana@example.com"))["status"] == codigo
    assert store.carteira(CPF)["chaves"] == []


def test_resposta_de_chave_nao_expoe_wallet_id(ctx):
    vinculado(ctx)
    r = run(ctx[0].registrar_chave(CPF, "EMAIL", "ana@example.com"))
    assert "wallet" not in json.dumps(r).lower()


# -----------------------------
# consultar_carteira / consultar_saldo
# -----------------------------


def test_consultar_carteira_sem_vinculo(ctx):
    assert run(ctx[0].consultar_carteira(CPF))["status"] == "sem_carteira"


def test_consultar_carteira_lista_chaves(ctx):
    vinculado(ctx)
    run(ctx[0].registrar_chave(CPF, "EMAIL", "ana@example.com"))
    r = run(ctx[0].consultar_carteira(CPF))
    assert r["carteira"]["chaves"] == [{"tipo": "EMAIL", "valor": "ana@example.com"}]


def test_saldo_exige_carteira(ctx):
    assert run(ctx[0].consultar_saldo(CPF))["status"] == "sem_carteira"


def test_saldo_atual_formatado_em_decimal(ctx):
    service, client, *_ = ctx
    vinculado(ctx)
    r = run(service.consultar_saldo(CPF))
    assert r["status"] == "ok" and r["consulta"] == "atual" and "em" not in r
    assert r["saldo"] == "1234.50"
    assert r["saldo_formatado"] == "R$ 1.234,50"
    assert client.calls[-1] == ("consultar_saldo", 101, None)


def test_saldo_arredonda_half_up(ctx):
    vinculado(ctx)
    ctx[1].saldo = Decimal("0.125")
    assert run(ctx[0].consultar_saldo(CPF))["saldo"] == "0.13"


def test_saldo_historico_passa_data_sem_fuso(ctx):
    service, client, *_ = ctx
    vinculado(ctx)
    r = run(service.consultar_saldo(CPF, "2025-10-15T10:00:00"))
    assert r["consulta"] == "historico" and r["em"] == "2025-10-15T10:00:00"
    assert client.calls[-1][2].isoformat() == "2025-10-15T10:00:00"


def test_saldo_historico_so_com_data_vira_meia_noite(ctx):
    vinculado(ctx)
    r = run(ctx[0].consultar_saldo(CPF, "2025-10-15"))  # o pix-service daria 500
    assert r["em"] == "2025-10-15T00:00:00"


@pytest.mark.parametrize("em", ["2025-10-15T10:00:00-03:00", "2025-10-15T10:00:00Z", "ontem", "15/10/2025"])
def test_saldo_historico_rejeita_fuso_e_formato_invalido(ctx, em):
    service, client, *_ = ctx
    vinculado(ctx)
    assert run(service.consultar_saldo(CPF, em))["status"] == "em_invalido"
    assert [c for c in client.calls if c[0] == "consultar_saldo"] == []


@pytest.mark.parametrize("codigo", ["carteira_inexistente", "indisponivel", "erro_desconhecido"])
def test_saldo_propaga_o_status_do_cliente(ctx, codigo):
    vinculado(ctx)
    ctx[1].erro_saldo = codigo
    assert run(ctx[0].consultar_saldo(CPF))["status"] == codigo


# -----------------------------
# Todas as respostas seguem o padrão {"status", "mensagem"} e são serializáveis
# -----------------------------


def test_toda_resposta_tem_status_e_mensagem_e_e_json(ctx):
    service, client, *_ = ctx
    respostas = [
        run(service.vincular_carteira("1")),
        run(service.vincular_carteira(CPF)),
        run(service.registrar_chave(CPF, "EMAIL", "ana@example.com")),
        run(service.consultar_carteira(CPF)),
        run(service.consultar_saldo(CPF)),
    ]
    for r in respostas:
        assert r["status"] and r["mensagem"]
        json.dumps(r)  # nada de Decimal cru no retorno ao LLM


def test_formatar_brl():
    assert formatar_brl(Decimal("0")) == "R$ 0,00"
    assert formatar_brl(Decimal("1234567.8")) == "R$ 1.234.567,80"
