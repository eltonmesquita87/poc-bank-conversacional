"""Cliente HTTP do pix-service (camada anticorrupção).

Único ponto que conhece o contrato REST do pix-service e a forma de classificar seus erros
(docs/pagamentos-pix.md, seções 3 a 5). O pix-service não tem código de erro estável
(R-07 do doc 03): a classificação usa endpoint + status + `error` + prefixo de `message`, e fica
toda aqui, para uma mudança de texto no servidor quebrar um lugar só.

Regras:
- Retry só em GET. POST nunca é reenviado aqui (depósito/saque não têm idempotência, L2).
- `message` do servidor nunca vai para log nem para o LLM: contém a chave Pix (AC-07).
- Valores monetários são `Decimal` (JSON lido com `parse_float=Decimal`), nunca `float`.
"""

import asyncio
import logging
import time
from datetime import datetime
from decimal import Decimal
from typing import Any, Optional

import httpx
from correlation import log_event, outbound_headers

logger = logging.getLogger("pix")

# IDs dos endpoints (numeração do doc 01/03).
A1_CRIAR_CARTEIRA = "A1"
A2_REGISTRAR_CHAVE = "A2"
A3_DEPOSITAR = "A3"
A4_SACAR = "A4"
A5_SALDO = "A5"
A6_TRANSFERIR = "A6"

_GET = {A5_SALDO}


class PixServiceError(Exception):
    """Falha ao falar com o pix-service. `codigo` é o `status` devolvido pela tool."""

    def __init__(
        self, codigo: str, *, http_status: Optional[int] = None, endpoint: str = ""
    ) -> None:
        super().__init__(codigo)
        self.codigo = codigo
        self.http_status = http_status
        self.endpoint = endpoint


def classificar_erro(endpoint: str, status: int, error: str, message: str) -> str:
    """Traduz uma resposta de erro do pix-service para o `status` da tool.

    Tabela em docs/pagamentos-pix.md, seção 5. Prefixos conferidos com o doc 03 (§2.2 e §4).
    """
    msg = (message or "").lower()

    if status >= 500:
        return "indisponivel" if endpoint in _GET else "desconhecida"

    if status == 404:
        if msg.startswith("pix key not found"):
            return "chave_nao_encontrada"
        if "wallet not found" in msg:
            return "carteira_inexistente"

    if status == 409:
        if msg.startswith("insufficient balance"):
            return "saldo_insuficiente"
        if msg.startswith("duplicate request"):
            return "ja_enviada"
        if msg.startswith("pix key already registered"):
            return "chave_ja_registrada"

    if status == 400:
        # D-01: no depósito, carteira inexistente é 400 "Bad Request", não 404.
        if "wallet not found" in msg:
            return "carteira_inexistente"
        if "same wallet" in msg:
            return "mesma_carteira"
        if endpoint == A2_REGISTRAR_CHAVE:
            return "chave_invalida"
        if endpoint in (A3_DEPOSITAR, A4_SACAR) or (
            endpoint == A6_TRANSFERIR and "amount" in msg
        ):
            return "valor_invalido"
        return "requisicao_invalida"

    return "erro_desconhecido"


def _envelope(resposta: httpx.Response) -> tuple[str, str]:
    """`error` e `message` do ErrorResponse, ou vazios se o corpo não for o envelope."""
    try:
        corpo = resposta.json()
    except ValueError:
        return "", ""
    if not isinstance(corpo, dict):
        return "", ""
    return str(corpo.get("error") or ""), str(corpo.get("message") or "")


class PixServiceClient:
    def __init__(
        self,
        base_url: str,
        *,
        timeout: float = 5.0,
        retries: int = 2,
        backoff: float = 0.2,
        transport: Optional[httpx.AsyncBaseTransport] = None,
    ) -> None:
        self._http = httpx.AsyncClient(
            base_url=base_url.rstrip("/"), timeout=timeout, transport=transport
        )
        self._retries = retries
        self._backoff = backoff

    async def aclose(self) -> None:
        await self._http.aclose()

    # -----------------------------
    # Núcleo
    # -----------------------------

    async def _request(
        self,
        endpoint: str,
        method: str,
        path: str,
        *,
        rotulo: str,
        json: Any = None,
        params: Optional[dict[str, str]] = None,
    ) -> Any:
        """Uma chamada ao pix-service, com log `pix.*`.

        `rotulo` é o path com placeholders (ex.: "POST /wallets/{id}/pix-keys"): o log nunca
        recebe o path real nem o corpo.
        """
        tentativas = 1 + (self._retries if endpoint in _GET else 0)
        ultimo: Optional[PixServiceError] = None

        for tentativa in range(tentativas):
            if tentativa:
                await asyncio.sleep(self._backoff * (2 ** (tentativa - 1)))
            started = time.perf_counter()
            log_event(
                logger, "pix", "client", "request", endpoint=rotulo, attempt=tentativa + 1
            )
            try:
                resposta = await self._http.request(
                    method, path, json=json, params=params, headers=outbound_headers()
                )
            except (httpx.ConnectError, httpx.ConnectTimeout, httpx.PoolTimeout) as exc:
                # A requisição não chegou ao servidor: seguro mesmo em POST.
                ultimo = PixServiceError("indisponivel", endpoint=rotulo)
                self._log_erro(rotulo, ultimo, started, exc)
                continue
            except httpx.HTTPError as exc:
                # Timeout de leitura, conexão cortada etc.: em POST não sabemos se gravou.
                codigo = "indisponivel" if endpoint in _GET else "desconhecida"
                ultimo = PixServiceError(codigo, endpoint=rotulo)
                self._log_erro(rotulo, ultimo, started, exc)
                continue

            duracao = round((time.perf_counter() - started) * 1000, 1)
            if resposta.is_success:
                log_event(
                    logger,
                    "pix",
                    "client",
                    "response",
                    endpoint=rotulo,
                    http_status=resposta.status_code,
                    duration_ms=duracao,
                )
                try:
                    return resposta.json(parse_float=Decimal)
                except ValueError:
                    raise PixServiceError(
                        "erro_desconhecido",
                        http_status=resposta.status_code,
                        endpoint=rotulo,
                    ) from None

            error, message = _envelope(resposta)
            codigo = classificar_erro(endpoint, resposta.status_code, error, message)
            ultimo = PixServiceError(
                codigo, http_status=resposta.status_code, endpoint=rotulo
            )
            log_event(
                logger,
                "pix",
                "client",
                "error",
                endpoint=rotulo,
                http_status=resposta.status_code,
                error_code=codigo,
                duration_ms=duracao,
            )
            if codigo == "indisponivel" and tentativa + 1 < tentativas:
                continue  # 5xx em GET: tenta de novo
            raise ultimo

        assert ultimo is not None
        raise ultimo

    @staticmethod
    def _log_erro(
        rotulo: str, erro: PixServiceError, started: float, exc: Exception
    ) -> None:
        log_event(
            logger,
            "pix",
            "client",
            "error",
            endpoint=rotulo,
            error_code=erro.codigo,
            error=type(exc).__name__,
            duration_ms=round((time.perf_counter() - started) * 1000, 1),
        )

    @staticmethod
    def _exigir(dados: Any, *campos: str, endpoint: str) -> dict:
        """Garante o formato da resposta de sucesso; mudança de contrato vira erro explícito."""
        if not isinstance(dados, dict) or any(c not in dados for c in campos):
            raise PixServiceError("erro_desconhecido", endpoint=endpoint)
        return dados

    # -----------------------------
    # Endpoints
    # -----------------------------

    async def criar_carteira(self, user_id: str) -> dict:
        """A1. Devolve `{id, userId, balance}`."""
        rotulo = "POST /wallets"
        dados = await self._request(
            A1_CRIAR_CARTEIRA, "POST", "/wallets", rotulo=rotulo, json={"userId": user_id}
        )
        return self._exigir(dados, "id", endpoint=rotulo)

    async def registrar_chave(self, wallet_id: int, tipo: str, valor: str) -> dict:
        """A2. Devolve `{id, walletId, keyType, keyValue}`."""
        rotulo = "POST /wallets/{id}/pix-keys"
        dados = await self._request(
            A2_REGISTRAR_CHAVE,
            "POST",
            f"/wallets/{int(wallet_id)}/pix-keys",
            rotulo=rotulo,
            json={"keyType": tipo, "keyValue": valor},
        )
        return self._exigir(dados, "id", endpoint=rotulo)

    async def consultar_saldo(
        self, wallet_id: int, em: Optional[datetime] = None
    ) -> dict:
        """A5. `em` é enviado sem fuso (LocalDateTime); o fuso do servidor é desconhecido (L10)."""
        rotulo = "GET /wallets/{id}/balance"
        params = {"at": em.replace(tzinfo=None).isoformat(timespec="seconds")} if em else None
        dados = await self._request(
            A5_SALDO,
            "GET",
            f"/wallets/{int(wallet_id)}/balance",
            rotulo=rotulo,
            params=params,
        )
        dados = self._exigir(dados, "balance", endpoint=rotulo)
        if not isinstance(dados["balance"], (Decimal, int)):
            raise PixServiceError("erro_desconhecido", endpoint=rotulo)
        return dados
