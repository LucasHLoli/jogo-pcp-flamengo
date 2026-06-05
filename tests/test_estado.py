from pathlib import Path
import json
from src.estado import salvar_estado, carregar_estado, snapshot_rodada, estado_inicial
from src.domain import Estado, TransitItem, OP


def test_carregar_inexistente_retorna_inicial(tmp_path):
    estado = carregar_estado(tmp_path / "state.json")
    assert estado.rodada_atual == 0
    assert estado.transit == []


def test_round_trip(tmp_path):
    e1 = estado_inicial()
    e1.transit.append(TransitItem(
        rod_part=1, dia_part=1, rod_cheg=1, dia_cheg=4,
        origem_tipo="Fornecedor", origem_cidade="Manaus",
        destino_tipo="Fábrica", destino_cidade="Joinville",
        modal="Caminhão", item="MP1", qtd=24.0,
    ))
    e1.ops_atendidas.append(OP(rodada=2, cidade="São Paulo", pa="PA1", qtd=50000, dia_entrega=3))
    path = tmp_path / "state.json"
    salvar_estado(e1, path)
    e2 = carregar_estado(path)
    assert e2.transit[0].destino_cidade == "Joinville"
    assert e2.ops_atendidas[0].cidade == "São Paulo"


def test_snapshot_rodada(tmp_path):
    e = estado_inicial()
    e.rodada_atual = 2
    snapshot_rodada(e, rodada_n=2, extras={"custo_total": 1234.5, "transportes": 10}, dir_path=tmp_path)
    f = tmp_path / "historico_rodada_2.json"
    assert f.exists()
    data = json.loads(f.read_text(encoding="utf-8"))
    assert data["rodada"] == 2
    assert data["extras"]["custo_total"] == 1234.5
    assert "estado" in data
