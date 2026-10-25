"""Regras de domínio do pix_mcp: identidade do titular e normalização de chaves Pix.

Sem I/O. O pix-service compara a chave por string exata e não normaliza nada (AC-14), então
a mesma normalização precisa valer no registro e na transferência. Contrato em
docs/pagamentos-pix.md (seção 3.1).
"""

import hashlib
import hmac
import re
import uuid
from enum import Enum
from typing import Optional


class TipoChave(str, Enum):
    CPF = "CPF"
    EMAIL = "EMAIL"
    PHONE = "PHONE"
    EVP = "EVP"


class ChaveInvalida(ValueError):
    """Valor que o pix-service rejeitaria (ou que aceitaria de forma insegura)."""


# Mesma regex do pix-service (PixKey.validate), para não descobrir o erro só pelo 400.
_EMAIL = re.compile(r"^[A-Za-z0-9+_.-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}$")
_EVP = re.compile(
    r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$", re.IGNORECASE
)


def somente_digitos(valor: str) -> str:
    return re.sub(r"\D", "", valor or "")


# -----------------------------
# CPF
# -----------------------------


def normalizar_cpf(valor: str) -> str:
    """Só dígitos; exige 11. Não valida os dígitos verificadores (ver `cpf_dv_valido`)."""
    digitos = somente_digitos(valor)
    if len(digitos) != 11:
        raise ChaveInvalida("O CPF deve ter 11 dígitos.")
    return digitos


def cpf_dv_valido(digitos: str) -> bool:
    """Dígitos verificadores do CPF (o pix-service não os valida, AC-14)."""
    if len(digitos) != 11 or not digitos.isdigit() or digitos == digitos[0] * 11:
        return False
    for tamanho in (9, 10):
        soma = sum(int(d) * (tamanho + 1 - i) for i, d in enumerate(digitos[:tamanho]))
        dv = (soma * 10) % 11 % 10
        if dv != int(digitos[tamanho]):
            return False
    return True


def formatar_cpf(digitos: str) -> str:
    return f"{digitos[:3]}.{digitos[3:6]}.{digitos[6:9]}-{digitos[9:]}"


def candidatos_cpf(valor: str) -> list[str]:
    """Formas sob as quais o CPF pode estar gravado em `recursos`.

    `recursos/db.json` mistura chaves só com dígitos e chaves formatadas (999.999.999-99), e
    `recursos` não normaliza: sem tentar as variantes, "sem conta" seria um falso negativo.
    """
    bruto = (valor or "").strip()
    candidatos = [bruto]
    digitos = somente_digitos(bruto)
    if len(digitos) == 11:
        candidatos += [digitos, formatar_cpf(digitos)]
    return list(dict.fromkeys(c for c in candidatos if c))


def hash_usuario(cpf_digitos: str, segredo: str) -> str:
    """`userId` enviado ao pix-service: HMAC do CPF, para não gravar PII lá (AC-07).

    O pix-service trata `userId` como texto livre, sem unicidade. HMAC (e não SHA puro) porque
    o espaço de CPFs é pequeno o bastante para ser enumerado.
    """
    digest = hmac.new(segredo.encode(), cpf_digitos.encode(), hashlib.sha256).hexdigest()
    return f"mdb-{digest[:32]}"


# -----------------------------
# Chaves Pix
# -----------------------------


def gerar_evp() -> str:
    """O pix-service aceita o EVP vindo do cliente (RN-12); aqui ele é sempre gerado."""
    return str(uuid.uuid4())


def normalizar_chave(
    tipo: TipoChave, valor: Optional[str], *, validar_dv_cpf: bool = True
) -> str:
    """Devolve a chave no formato canônico enviado ao pix-service, ou levanta `ChaveInvalida`."""
    texto = (valor or "").strip()

    if tipo is TipoChave.CPF:
        digitos = normalizar_cpf(texto)
        if validar_dv_cpf and not cpf_dv_valido(digitos):
            raise ChaveInvalida("O CPF informado não é válido.")
        return digitos

    if tipo is TipoChave.EMAIL:
        email = texto.lower()
        if not _EMAIL.match(email):
            raise ChaveInvalida("O e-mail informado não é válido.")
        return email

    if tipo is TipoChave.PHONE:
        # O pix-service aceita 10 a 11 dígitos (DDD + número) e rejeita o DDI: "+55…" tem 12 a
        # 13 dígitos. Por isso o DDI é removido aqui.
        digitos = somente_digitos(texto)
        if len(digitos) in (12, 13) and digitos.startswith("55"):
            digitos = digitos[2:]
        if len(digitos) not in (10, 11) or digitos[0] == "0":
            raise ChaveInvalida("O telefone deve ter DDD e número (10 ou 11 dígitos).")
        if len(digitos) == 11 and digitos[2] != "9":
            raise ChaveInvalida("O celular deve começar com 9 após o DDD.")
        return digitos

    if tipo is TipoChave.EVP:
        if not _EVP.match(texto):
            raise ChaveInvalida("A chave aleatória deve ser um UUID de 36 caracteres.")
        return texto.lower()

    raise ChaveInvalida("Tipo de chave desconhecido.")
