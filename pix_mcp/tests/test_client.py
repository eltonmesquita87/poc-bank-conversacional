import asyncio
import json
from datetime import datetime
from decimal import Decimal

import httpx
import pytest
from client import (
    A2_REGISTRAR_CHAVE,
    A3_DEPOSITAR,
    A4_SACAR,
    A5_SALDO,
    A6_TRANSFERIR,
    PixServiceClient,
    PixServiceError,
    classificar_erro,
)
from correlation import bind, setup_logging

CORR = "corr-aaaa-1111"
CONV = "conv-aaaa-1111"


def run(coro):
    return asyncio.run(coro)


def erro(status, error, message, path="/x"):
    return httpx.Response(
        status,
        json={
            "timestamp": "2026-10-24T10:00:00",
            "status": status,
            "error": error,
            "message": message,
            "path": path,
        },
    )


def cliente(handler, **kw):
    kw.setdefault("backoff", 0)
    return PixServiceClient(
        "http://pix:8089", transport=httpx.MockTransport(handler), **kw
    )


# -----------------------------
# Classificação (contrato: docs/pagamentos-pix.md seção 5 / doc 03 §2.2 e §4)
# -----------------------------


@pytest.mark.parametrize(
    "endpoint, status, error, message, esperado",
    [
        (A2_REGISTRAR_CHAVE, 404, "Not Found", "Wallet not found: 9", "carteira_inexistente"),
        (A2_REGISTRAR_CHAVE, 409, "Conflict", "Pix key already registered: a@b.com", "chave_ja_registrada"),
        (A2_REGISTRAR_CHAVE, 400, "Bad Request", "Invalid email format: abc", "chave_invalida"),
        (A2_REGISTRAR_CHAVE, 400, "Validation Failed", "Key type is required", "chave_invalida"),
        # D-01: depósito em carteira inexistente é 400 "Bad Request", não 404
        (A3_DEPOSITAR, 400, "Bad Request", "Wallet not found: 9", "carteira_inexistente"),
        (A3_DEPOSITAR, 400, "Validation Failed", "Amount must be greater than zero", "valor_invalido"),
        (A4_SACAR, 404, "Not Found", "Wallet not found: 9", "carteira_inexistente"),
        (A4_SACAR, 409, "Conflict", "Insufficient balance. Current: 50.00, Requested: 100.00", "saldo_insuficiente"),
        (A5_SALDO, 404, "Not Found", "Wallet not found: 9", "carteira_inexistente"),
        (A6_TRANSFERIR, 404, "Not Found", "Pix key not found: a@b.com", "chave_nao_encontrada"),
        (A6_TRANSFERIR, 404, "Not Found", "Source wallet not found: 9", "carteira_inexistente"),
        (A6_TRANSFERIR, 400, "Bad Request", "Cannot transfer to the same wallet", "mesma_carteira"),
        (A6_TRANSFERIR, 409, "Conflict", "Insufficient balance", "saldo_insuficiente"),
        (A6_TRANSFERIR, 409, "Conflict", "Duplicate request", "ja_enviada"),
        (A6_TRANSFERIR, 409, "Conflict", "Duplicate request detected", "ja_enviada"),
        (A6_TRANSFERIR, 400, "Validation Failed", "Amount must be greater than zero", "valor_invalido"),
        (A6_TRANSFERIR, 400, "Validation Failed", "From wallet ID is required", "requisicao_invalida"),
        # 500 em POST não é "falha segura": pode ter havido rollback, deadlock ou erro nosso
        (A6_TRANSFERIR, 500, "Internal Server Error", "An unexpected error occurred", "desconhecida"),
        (A3_DEPOSITAR, 503, "", "", "desconhecida"),
        (A5_SALDO, 500, "Internal Server Error", "An unexpected error occurred", "indisponivel"),
        # fora da tabela
        (A4_SACAR, 409, "Conflict", "Data integrity violation", "erro_desconhecido"),
        (A5_SALDO, 418, "", "", "erro_desconhecido"),
    ],
)
def test_classificar_erro(endpoint, status, error, message, esperado):
    assert classificar_erro(endpoint, status, error, message) == esperado


# -----------------------------
# Requisições
# -----------------------------


def test_criar_carteira_envia_user_id_e_propaga_correlation_id():
    vistos = []

    def handler(request: httpx.Request):
        vistos.append(request)
        return httpx.Response(201, json={"id": 7, "userId": "u", "balance": 0.00})

    async def main():
        c = cliente(handler)
        with bind(CORR, CONV):
            return await c.criar_carteira("mdb-abc")

    dados = run(main())
    assert dados["id"] == 7
    req = vistos[0]
    assert req.method == "POST" and req.url.path == "/wallets"
    assert json.loads(req.content) == {"userId": "mdb-abc"}
    assert req.headers["X-Correlation-ID"] == CORR
    assert req.headers["X-Conversation-ID"] == CONV


def test_registrar_chave_envia_tipo_e_valor():
    vistos = []

    def handler(request):
        vistos.append(request)
        return httpx.Response(
            201, json={"id": 1, "walletId": 7, "keyType": "EMAIL", "keyValue": "a@b.com"}
        )

    run(cliente(handler).registrar_chave(7, "EMAIL", "a@b.com"))
    assert vistos[0].url.path == "/wallets/7/pix-keys"
    assert json.loads(vistos[0].content) == {"keyType": "EMAIL", "keyValue": "a@b.com"}


def test_saldo_e_lido_como_decimal_nunca_float():
    def handler(request):
        return httpx.Response(
            200,
            content=b'{"walletId": 7, "balance": 350.10, "timestamp": "2026-10-24T10:15:30"}',
            headers={"content-type": "application/json"},
        )

    dados = run(cliente(handler).consultar_saldo(7))
    assert dados["balance"] == Decimal("350.10")
    assert isinstance(dados["balance"], Decimal)


def test_saldo_historico_envia_at_sem_fuso():
    vistos = []

    def handler(request):
        vistos.append(request)
        return httpx.Response(200, json={"walletId": 7, "balance": 1})

    from datetime import timedelta, timezone

    em = datetime(2025, 10, 15, 10, 0, 0, tzinfo=timezone(timedelta(hours=-3)))
    run(cliente(handler).consultar_saldo(7, em))
    assert vistos[0].url.params["at"] == "2025-10-15T10:00:00"  # offset descartado


def test_saldo_sem_at_nao_envia_parametro():
    vistos = []

    def handler(request):
        vistos.append(request)
        return httpx.Response(200, json={"walletId": 7, "balance": 1})

    run(cliente(handler).consultar_saldo(7))
    assert "at" not in vistos[0].url.params


def test_resposta_de_sucesso_sem_campo_esperado_vira_erro_desconhecido():
    def handler(request):
        return httpx.Response(201, json={"qualquer": "coisa"})

    with pytest.raises(PixServiceError) as exc:
        run(cliente(handler).criar_carteira("u"))
    assert exc.value.codigo == "erro_desconhecido"


# -----------------------------
# Retry e timeouts
# -----------------------------


def test_post_nunca_e_reenviado_em_timeout_de_leitura():
    chamadas = []

    def handler(request):
        chamadas.append(request)
        raise httpx.ReadTimeout("lento", request=request)

    with pytest.raises(PixServiceError) as exc:
        run(cliente(handler).criar_carteira("u"))
    assert exc.value.codigo == "desconhecida"  # pode ter gravado
    assert len(chamadas) == 1


def test_post_com_falha_de_conexao_e_indisponivel_sem_retry():
    chamadas = []

    def handler(request):
        chamadas.append(request)
        raise httpx.ConnectError("recusada", request=request)

    with pytest.raises(PixServiceError) as exc:
        run(cliente(handler).criar_carteira("u"))
    # Não chegou ao servidor: ao contrário do timeout de leitura, é seguro repetir depois.
    assert exc.value.codigo == "indisponivel"
    assert len(chamadas) == 1


def test_get_tem_retry_e_se_recupera():
    respostas = [
        erro(500, "Internal Server Error", "An unexpected error occurred"),
        httpx.Response(200, json={"walletId": 7, "balance": 5}),
    ]

    def handler(request):
        return respostas.pop(0)

    dados = run(cliente(handler).consultar_saldo(7))
    assert dados["balance"] == 5
    assert respostas == []


def test_get_esgota_tentativas_e_fica_indisponivel():
    chamadas = []

    def handler(request):
        chamadas.append(request)
        return erro(500, "Internal Server Error", "An unexpected error occurred")

    with pytest.raises(PixServiceError) as exc:
        run(cliente(handler, retries=2).consultar_saldo(7))
    assert exc.value.codigo == "indisponivel"
    assert len(chamadas) == 3


def test_get_404_nao_faz_retry():
    chamadas = []

    def handler(request):
        chamadas.append(request)
        return erro(404, "Not Found", "Wallet not found: 7")

    with pytest.raises(PixServiceError) as exc:
        run(cliente(handler).consultar_saldo(7))
    assert exc.value.codigo == "carteira_inexistente"
    assert len(chamadas) == 1


def test_corpo_de_erro_fora_do_envelope_nao_quebra():
    def handler(request):
        return httpx.Response(502, text="<html>bad gateway</html>")

    with pytest.raises(PixServiceError) as exc:
        run(cliente(handler).criar_carteira("u"))
    assert exc.value.codigo == "desconhecida"


# -----------------------------
# Privacidade dos logs
# -----------------------------


def test_logs_nao_contem_message_do_servidor_nem_a_chave(capsys, monkeypatch):
    # O message do pix-service traz a chave Pix (AC-07): ela não pode ir para o log.
    monkeypatch.setenv("LOG_PAYLOAD", "full")
    setup_logging("testsvc")

    def handler(request):
        return erro(409, "Conflict", "Pix key already registered: segredo.pessoal@example.com")

    with pytest.raises(PixServiceError):
        run(cliente(handler).registrar_chave(7, "EMAIL", "segredo.pessoal@example.com"))

    saida = capsys.readouterr().out
    assert "segredo.pessoal" not in saida
    eventos = [json.loads(l) for l in saida.splitlines() if l.startswith("{")]
    erros = [e for e in eventos if e.get("msg") == "pix.error"]
    assert erros and erros[0]["error_code"] == "chave_ja_registrada"
    assert erros[0]["http_status"] == 409
    assert erros[0]["endpoint"] == "POST /wallets/{id}/pix-keys"  # template, sem o id real
