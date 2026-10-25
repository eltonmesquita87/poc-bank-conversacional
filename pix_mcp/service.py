"""Casos de uso do pix_mcp. As tools de `app.py` só delegam para cá.

Regras impostas aqui, e não no prompt do agente:
- o LLM só fala em `cpf`; o `walletId` nunca sai daqui (o pix-service não verifica titularidade);
- carteira só para quem tem conta em `recursos`;
- chave CPF só para o próprio titular; EVP sempre gerado aqui; formato normalizado antes de enviar;
- toda resposta é um dict `{"status", "mensagem", ...}`: nada de exceção para o LLM.
"""

import logging
from datetime import datetime, timezone
from decimal import ROUND_HALF_UP, Decimal
from typing import Any, Optional

from client import PixServiceClient, PixServiceError
from contas import ContaGateway, ContaIndisponivel
from domain import (
    ChaveInvalida,
    TipoChave,
    gerar_evp,
    hash_usuario,
    normalizar_chave,
    normalizar_cpf,
)
from store import PixStore

logger = logging.getLogger("pix_service")

# Mensagens para o cliente final. O texto do pix-service nunca é repassado (contém a chave).
MENSAGENS = {
    "ok": "Operação realizada.",
    "criada": "Carteira Pix criada.",
    "existente": "O cliente já possui carteira Pix.",
    "cpf_invalido": "O CPF informado deve ter 11 dígitos.",
    "sem_conta": "O cliente não possui conta no MD Bank. É preciso abrir a conta antes.",
    "sem_carteira": "O cliente ainda não possui carteira Pix. É preciso criá-la antes.",
    "tipo_invalido": "Tipo de chave inválido. Use CPF, EMAIL, PHONE ou EVP.",
    "valor_obrigatorio": "Informe o valor da chave (e-mail ou telefone).",
    "chave_invalida": "A chave Pix informada não é válida para o tipo escolhido.",
    "chave_cpf_de_terceiro": "A chave CPF só pode ser o CPF do próprio titular da conta.",
    "limite_de_chaves": "O cliente atingiu o limite de chaves Pix por carteira.",
    "chave_ja_registrada": (
        "Essa chave Pix já está registrada (nesta ou em outra conta) e não pode ser "
        "cadastrada de novo."
    ),
    "em_invalido": (
        "Data/hora inválida. Informe no formato AAAA-MM-DDTHH:MM:SS, sem fuso horário."
    ),
    "carteira_inexistente": (
        "A carteira vinculada não foi encontrada no provedor Pix. Contate o suporte."
    ),
    "indisponivel": "O serviço Pix está indisponível no momento. Tente novamente em instantes.",
    "desconhecida": (
        "Não foi possível confirmar se a operação foi concluída. Confira antes de repetir."
    ),
    "requisicao_invalida": "O provedor Pix recusou a requisição.",
    "erro_desconhecido": "Erro inesperado no provedor Pix.",
}

_CENTAVOS = Decimal("0.01")


def _resp(status: str, **extra: Any) -> dict[str, Any]:
    mensagem = MENSAGENS.get(status, MENSAGENS["erro_desconhecido"])
    return {"status": status, "mensagem": mensagem, **extra}


def formatar_brl(valor: Decimal) -> str:
    inteiro = f"{valor:,.2f}"  # 1,234.50
    return "R$ " + inteiro.replace(",", "X").replace(".", ",").replace("X", ".")


def _publica(carteira: dict[str, Any]) -> dict[str, Any]:
    """Visão da carteira para o LLM: sem `wallet_id` e sem `user_id`."""
    return {"chaves": [{"tipo": c["tipo"], "valor": c["valor"]} for c in carteira["chaves"]]}


def _agora() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _parse_em(em: str) -> datetime:
    """`em` sem fuso. Só a data vale meia-noite (o pix-service rejeita só a data, com 500)."""
    texto = em.strip()
    try:
        momento = datetime.fromisoformat(texto)
    except ValueError as exc:
        raise ValueError("formato") from exc
    if momento.tzinfo is not None:
        # O fuso do servidor é desconhecido (L10): converter seria chute.
        raise ValueError("fuso")
    return momento


class PixService:
    def __init__(
        self,
        client: PixServiceClient,
        store: PixStore,
        contas: ContaGateway,
        *,
        segredo_user_id: str,
        max_chaves: int = 5,
        validar_dv_cpf: bool = True,
    ) -> None:
        self._client = client
        self._store = store
        self._contas = contas
        self._segredo = segredo_user_id
        self._max_chaves = max_chaves
        self._validar_dv = validar_dv_cpf

    # -----------------------------
    # Carteira
    # -----------------------------

    async def vincular_carteira(self, cpf: str) -> dict[str, Any]:
        try:
            cpf_n = normalizar_cpf(cpf)
        except ChaveInvalida:
            return _resp("cpf_invalido")

        async with self._store.lock(cpf_n):
            existente = self._store.carteira(cpf_n)
            if existente:
                return _resp("existente", carteira=_publica(existente))

            try:
                tem_conta = await self._contas.existe(cpf)
            except ContaIndisponivel:
                return _resp("indisponivel")
            if not tem_conta:
                return _resp("sem_conta")

            user_id = hash_usuario(cpf_n, self._segredo)
            try:
                dados = await self._client.criar_carteira(user_id)
            except PixServiceError as exc:
                return _resp(exc.codigo)

            # Se a gravação local falhar depois do POST, sobra uma carteira órfã no pix-service
            # (sem busca por usuário, AC-02): inofensiva, e a próxima tentativa cria outra.
            carteira = {
                "wallet_id": int(dados["id"]),
                "user_id": user_id,
                "chaves": [],
                "criada_em": _agora(),
            }
            self._store.salvar_carteira(cpf_n, carteira)
            return _resp("criada", carteira=_publica(carteira))

    async def consultar_carteira(self, cpf: str) -> dict[str, Any]:
        try:
            cpf_n = normalizar_cpf(cpf)
        except ChaveInvalida:
            return _resp("cpf_invalido")
        carteira = self._store.carteira(cpf_n)
        if not carteira:
            return _resp("sem_carteira")
        return _resp("ok", carteira=_publica(carteira))

    # -----------------------------
    # Chaves
    # -----------------------------

    async def registrar_chave(
        self, cpf: str, tipo: str, valor: Optional[str] = None
    ) -> dict[str, Any]:
        try:
            cpf_n = normalizar_cpf(cpf)
        except ChaveInvalida:
            return _resp("cpf_invalido")
        try:
            tipo_chave = TipoChave((tipo or "").strip().upper())
        except ValueError:
            return _resp("tipo_invalido")

        async with self._store.lock(cpf_n):
            carteira = self._store.carteira(cpf_n)
            if not carteira:
                return _resp("sem_carteira")

            if tipo_chave is TipoChave.EVP:
                chave = gerar_evp()  # nunca aceita o valor do LLM/cliente
            else:
                if tipo_chave is TipoChave.CPF:
                    # Sem valor, usa o do titular; com valor, tem de ser o do titular.
                    candidato = valor or cpf_n
                    try:
                        if normalizar_cpf(candidato) != cpf_n:
                            return _resp("chave_cpf_de_terceiro")
                    except ChaveInvalida:
                        return _resp("chave_invalida")
                    valor = cpf_n
                elif not (valor or "").strip():
                    return _resp("valor_obrigatorio")
                try:
                    chave = normalizar_chave(
                        tipo_chave, valor, validar_dv_cpf=self._validar_dv
                    )
                except ChaveInvalida as exc:
                    return _resp("chave_invalida", detalhe=str(exc))

            if any(c["valor"] == chave for c in carteira["chaves"]):
                return _resp("existente", carteira=_publica(carteira))
            if len(carteira["chaves"]) >= self._max_chaves:
                return _resp("limite_de_chaves")

            try:
                await self._client.registrar_chave(
                    carteira["wallet_id"], tipo_chave.value, chave
                )
            except PixServiceError as exc:
                return _resp(exc.codigo)

            carteira["chaves"].append(
                {"tipo": tipo_chave.value, "valor": chave, "registrada_em": _agora()}
            )
            self._store.salvar_carteira(cpf_n, carteira)
            return _resp(
                "ok",
                chave={"tipo": tipo_chave.value, "valor": chave},
                carteira=_publica(carteira),
            )

    # -----------------------------
    # Saldo
    # -----------------------------

    async def consultar_saldo(
        self, cpf: str, em: Optional[str] = None
    ) -> dict[str, Any]:
        try:
            cpf_n = normalizar_cpf(cpf)
        except ChaveInvalida:
            return _resp("cpf_invalido")
        carteira = self._store.carteira(cpf_n)
        if not carteira:
            return _resp("sem_carteira")

        momento: Optional[datetime] = None
        if em and em.strip():
            try:
                momento = _parse_em(em)
            except ValueError:
                return _resp("em_invalido")

        try:
            dados = await self._client.consultar_saldo(carteira["wallet_id"], momento)
        except PixServiceError as exc:
            return _resp(exc.codigo)

        saldo = Decimal(dados["balance"]).quantize(_CENTAVOS, rounding=ROUND_HALF_UP)
        resultado: dict[str, Any] = {
            "saldo": f"{saldo:.2f}",
            "saldo_formatado": formatar_brl(saldo),
            "moeda": "BRL",
            "consulta": "historico" if momento else "atual",
        }
        if momento:
            # O saldo histórico soma os lançamentos estritamente anteriores a `em` (RN-26).
            resultado["em"] = momento.isoformat(timespec="seconds")
        return _resp("ok", **resultado)
