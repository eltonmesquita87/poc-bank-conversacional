"""Verificação de conta em `recursos` (regra "conta antes de Pix" imposta na tool).

O prompt do agente não é confiável para essa regra (docs/arquitetura.md, ponto 7): só a tool é.
Por isso o pix_mcp consulta `consultar_conta` no MCP `recursos`, propagando os IDs de correlação.
"""

import logging
import time
from typing import Protocol

from correlation import log_event, outbound_headers
from domain import candidatos_cpf

logger = logging.getLogger("mcp")


class ContaIndisponivel(Exception):
    """Não foi possível confirmar a conta (recursos fora do ar ou resposta inesperada)."""


class ContaGateway(Protocol):
    async def existe(self, cpf: str) -> bool: ...


class RecursosContaGateway:
    def __init__(self, url: str, *, timeout: float = 5.0) -> None:
        self._url = url
        self._timeout = timeout

    async def existe(self, cpf: str) -> bool:
        # Import sob demanda: os testes de serviço usam um gateway falso e não precisam do fastmcp.
        from fastmcp import Client
        from fastmcp.client.transports import StreamableHttpTransport

        started = time.perf_counter()
        log_event(
            logger,
            "mcp",
            "client",
            "request",
            operation="call_tool",
            server="recursos",
            tool="consultar_conta",
        )
        try:
            transport = StreamableHttpTransport(self._url, headers=outbound_headers())
            # Uma sessão para todas as variantes do CPF (recursos mistura formatado e só dígitos).
            async with Client(transport, timeout=self._timeout) as client:
                for candidato in candidatos_cpf(cpf):
                    resultado = await client.call_tool(
                        "consultar_conta", {"cpf": candidato}
                    )
                    dados = resultado.structured_content or resultado.data
                    if not isinstance(dados, dict) or "existe" not in dados:
                        raise ContaIndisponivel("resposta inesperada de consultar_conta")
                    if dados["existe"]:
                        self._log_fim(started)
                        return True
        except ContaIndisponivel:
            self._log_erro(started, "resposta_inesperada")
            raise
        except Exception as exc:
            self._log_erro(started, type(exc).__name__)
            raise ContaIndisponivel(str(exc)) from exc
        self._log_fim(started)
        return False

    @staticmethod
    def _log_fim(started: float) -> None:
        log_event(
            logger,
            "mcp",
            "client",
            "response",
            operation="call_tool",
            server="recursos",
            tool="consultar_conta",
            duration_ms=round((time.perf_counter() - started) * 1000, 1),
        )

    @staticmethod
    def _log_erro(started: float, erro: str) -> None:
        log_event(
            logger,
            "mcp",
            "client",
            "error",
            operation="call_tool",
            server="recursos",
            tool="consultar_conta",
            error=erro,
            duration_ms=round((time.perf_counter() - started) * 1000, 1),
        )
