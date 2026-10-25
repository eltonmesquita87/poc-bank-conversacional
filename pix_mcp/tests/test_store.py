import asyncio
import json
import os

import pytest
from store import PixStore

CPF = "52998224725"


def test_persiste_entre_instancias(tmp_path):
    caminho = str(tmp_path / "pix_db.json")
    PixStore(caminho).salvar_carteira(CPF, {"wallet_id": 7, "chaves": []})

    assert PixStore(caminho).carteira(CPF) == {"wallet_id": 7, "chaves": []}
    assert PixStore(caminho).carteira("00000000000") is None


def test_grava_na_partida_para_falhar_cedo_em_volume_sem_escrita(tmp_path):
    caminho = tmp_path / "pix_db.json"
    PixStore(str(caminho))
    assert json.loads(caminho.read_text()) == {"carteiras": {}}


def test_arquivo_corrompido_falha_em_vez_de_resetar_em_silencio(tmp_path):
    caminho = tmp_path / "pix_db.json"
    caminho.write_text("{isto nao e json")
    with pytest.raises(RuntimeError, match="corrompido"):
        PixStore(str(caminho))
    # o arquivo original é preservado para análise
    assert caminho.read_text() == "{isto nao e json"


def test_formato_inesperado_tambem_falha(tmp_path):
    caminho = tmp_path / "pix_db.json"
    caminho.write_text(json.dumps({"outra": 1}))
    with pytest.raises(RuntimeError, match="formato"):
        PixStore(str(caminho))


def test_escrita_atomica_nao_deixa_temporarios(tmp_path):
    store = PixStore(str(tmp_path / "pix_db.json"))
    for i in range(5):
        store.salvar_carteira(f"{i:011d}", {"wallet_id": i, "chaves": []})
    assert sorted(os.listdir(tmp_path)) == ["pix_db.json"]


def test_lock_e_por_cpf(tmp_path):
    store = PixStore(str(tmp_path / "pix_db.json"))
    assert store.lock("a") is store.lock("a")
    assert store.lock("a") is not store.lock("b")


def test_lock_serializa_o_mesmo_cpf_e_libera_cpfs_diferentes(tmp_path):
    store = PixStore(str(tmp_path / "pix_db.json"))
    ordem: list[str] = []

    async def secao(cpf: str, nome: str):
        async with store.lock(cpf):
            ordem.append(f"{nome}:entra")
            await asyncio.sleep(0.01)
            ordem.append(f"{nome}:sai")

    async def main():
        await asyncio.gather(secao("a", "1"), secao("a", "2"), secao("b", "3"))

    asyncio.run(main())
    # mesmo CPF: sem intercalar. CPF diferente: entra sem esperar.
    assert ordem.index("1:sai") < ordem.index("2:entra")
    assert ordem.index("3:entra") < ordem.index("1:sai")
