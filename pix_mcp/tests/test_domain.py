import pytest
from domain import (
    ChaveInvalida,
    TipoChave,
    candidatos_cpf,
    cpf_dv_valido,
    formatar_cpf,
    gerar_evp,
    hash_usuario,
    normalizar_chave,
    normalizar_cpf,
)

CPF_VALIDO = "52998224725"  # CPF de teste amplamente usado, com DV correto


# -----------------------------
# CPF
# -----------------------------


@pytest.mark.parametrize(
    "valor, esperado",
    [(CPF_VALIDO, True), ("52998224726", False), ("11111111111", False), ("123", False)],
)
def test_cpf_dv_valido(valor, esperado):
    assert cpf_dv_valido(valor) is esperado


def test_normalizar_cpf_remove_formatacao_e_exige_11_digitos():
    assert normalizar_cpf("529.982.247-25") == CPF_VALIDO
    with pytest.raises(ChaveInvalida):
        normalizar_cpf("123")


def test_candidatos_cpf_cobre_as_formas_gravadas_em_recursos():
    # recursos/db.json mistura CPF só com dígitos e CPF formatado
    assert candidatos_cpf(CPF_VALIDO) == [CPF_VALIDO, formatar_cpf(CPF_VALIDO)]
    assert candidatos_cpf("529.982.247-25") == [
        "529.982.247-25",
        CPF_VALIDO,
    ]
    assert candidatos_cpf("  123 ") == ["123"]


def test_hash_usuario_nao_vaza_cpf_e_depende_do_segredo():
    a = hash_usuario(CPF_VALIDO, "segredo-1")
    assert a == hash_usuario(CPF_VALIDO, "segredo-1")
    assert a != hash_usuario(CPF_VALIDO, "segredo-2")
    assert CPF_VALIDO not in a
    assert a.startswith("mdb-") and len(a) == 36  # cabe em VARCHAR(255) com folga


# -----------------------------
# Chaves
# -----------------------------


def test_chave_cpf_normaliza_e_valida_dv():
    assert normalizar_chave(TipoChave.CPF, "529.982.247-25") == CPF_VALIDO
    with pytest.raises(ChaveInvalida):
        normalizar_chave(TipoChave.CPF, "52998224726")
    # DV pode ser desligado (CPFs de demonstração)
    assert (
        normalizar_chave(TipoChave.CPF, "52998224726", validar_dv_cpf=False)
        == "52998224726"
    )


def test_chave_email_vai_para_minusculas_e_segue_a_regex_do_servidor():
    assert normalizar_chave(TipoChave.EMAIL, "  Joao.Silva+Pix@Example.COM ") == (
        "joao.silva+pix@example.com"
    )
    for ruim in ("sem-arroba", "a@b", "a@b.c", "a b@example.com"):
        with pytest.raises(ChaveInvalida):
            normalizar_chave(TipoChave.EMAIL, ruim)


@pytest.mark.parametrize(
    "entrada, esperado",
    [
        ("(11) 99999-8888", "11999998888"),
        ("11999998888", "11999998888"),
        ("1133334444", "1133334444"),
        # O pix-service rejeita o DDI (12 a 13 dígitos): ele precisa ser removido aqui.
        ("+55 11 99999-8888", "11999998888"),
        ("5511999998888", "11999998888"),
        ("+55 11 3333-4444", "1133334444"),
    ],
)
def test_chave_telefone_vira_ddd_mais_numero(entrada, esperado):
    assert normalizar_chave(TipoChave.PHONE, entrada) == esperado


@pytest.mark.parametrize(
    "ruim",
    ["123", "01999998888", "11899998888", "999999999", "551199999888877", ""],
)
def test_chave_telefone_invalida(ruim):
    with pytest.raises(ChaveInvalida):
        normalizar_chave(TipoChave.PHONE, ruim)


def test_evp_gerado_tem_36_caracteres_e_e_aceito_pela_normalizacao():
    evp = gerar_evp()
    assert len(evp) == 36
    assert normalizar_chave(TipoChave.EVP, evp.upper()) == evp
    with pytest.raises(ChaveInvalida):
        normalizar_chave(TipoChave.EVP, "nao-e-uuid")
