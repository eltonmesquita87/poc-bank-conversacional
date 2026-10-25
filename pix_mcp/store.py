"""Persistência local do pix_mcp (pix_db.json): vínculo CPF → carteira e chaves registradas.

Diferenças deliberadas em relação ao `db.json` de recursos (que não tem lock e engole erros de
leitura): escrita atômica (arquivo temporário + `os.replace`), lock por CPF e falha explícita se o
arquivo existir mas estiver corrompido. Resetar em silêncio apagaria o vínculo das carteiras.

Limite conhecido: o lock é de processo (asyncio). Vale com um worker, como o `fastmcp run` usa.
O CPF é a chave em texto claro, como em `db.json` (risco R2 em docs/pagamentos-pix.md).
"""

import asyncio
import json
import os
import tempfile
from typing import Any, Optional

_VAZIO: dict[str, Any] = {"carteiras": {}}


class PixStore:
    def __init__(self, caminho: str) -> None:
        self._caminho = caminho
        self._locks: dict[str, asyncio.Lock] = {}
        self._dados = self._carregar()
        # Grava já na partida: um volume sem permissão de escrita deve falhar aqui, não depois
        # de o pix-service ter criado a carteira.
        self._gravar()

    def _carregar(self) -> dict[str, Any]:
        if not os.path.exists(self._caminho):
            return json.loads(json.dumps(_VAZIO))
        with open(self._caminho, "r", encoding="utf-8") as f:
            try:
                dados = json.load(f)
            except json.JSONDecodeError as exc:
                raise RuntimeError(
                    f"{self._caminho} está corrompido; corrija ou remova o arquivo "
                    "(não será recriado em silêncio)."
                ) from exc
        if not isinstance(dados, dict) or not isinstance(dados.get("carteiras"), dict):
            raise RuntimeError(f"{self._caminho} tem formato inesperado.")
        return dados

    def _gravar(self) -> None:
        pasta = os.path.dirname(os.path.abspath(self._caminho))
        fd, tmp = tempfile.mkstemp(dir=pasta, prefix=".pix_db.", suffix=".tmp")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump(self._dados, f, indent=2, ensure_ascii=False)
                f.flush()
                os.fsync(f.fileno())
            os.replace(tmp, self._caminho)
        except BaseException:
            if os.path.exists(tmp):
                os.unlink(tmp)
            raise

    # -----------------------------
    # Acesso
    # -----------------------------

    def lock(self, cpf: str) -> asyncio.Lock:
        """Lock por CPF: serializa vincular/registrar sem travar clientes diferentes."""
        return self._locks.setdefault(cpf, asyncio.Lock())

    def carteira(self, cpf: str) -> Optional[dict[str, Any]]:
        return self._dados["carteiras"].get(cpf)

    def salvar_carteira(self, cpf: str, carteira: dict[str, Any]) -> None:
        self._dados["carteiras"][cpf] = carteira
        self._gravar()
