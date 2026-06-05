import json
from dataclasses import asdict
from src.domain import (
    Estado, TransitItem, OP, OPDescartada,
    PlanoTransporte, PlanoProducao, TarefaTransporte,
)


def test_estado_round_trip_json():
    estado = Estado(
        rodada_atual=2,
        estoque_mp_fabrica={"F1": {"MP1": 10.5, "MP2": 0.0, "MP3": 5.0}},
        estoque_pa_cd={
            "CD1": {"PA1": 100, "PA2": 0, "PA3": 50},
            "CD2": {"PA1": 0, "PA2": 200, "PA3": 0},
        },
        transit=[TransitItem(
            rod_part=1, dia_part=4, rod_cheg=2, dia_cheg=2,
            origem_tipo="Fábrica", origem_cidade="Joinville",
            destino_tipo="CD", destino_cidade="São Luís",
            modal="Caminhão", item="PA1", qtd=27200.0,
        )],
        ops_pendentes=[],
        ops_atendidas=[OP(rodada=2, cidade="São Paulo", pa="PA1", qtd=50000, dia_entrega=3)],
        ops_descartadas=[OPDescartada(
            op=OP(rodada=2, cidade="Manaus", pa="PA3", qtd=1000, dia_entrega=1),
            motivo="sem_estoque_CD",
            rodada_descarte=2,
        )],
    )
    blob = json.dumps(asdict(estado), ensure_ascii=False)
    data = json.loads(blob)
    assert data["rodada_atual"] == 2
    assert data["transit"][0]["destino_cidade"] == "São Luís"
    assert data["ops_descartadas"][0]["motivo"] == "sem_estoque_CD"
    assert data["estoque_pa_cd"]["CD1"]["PA1"] == 100


def test_tarefa_transporte_minimal():
    t = TarefaTransporte(
        origem_cidade="Joinville", destino_cidade="Santos",
        item="PA1", qtd=80000, janela_dias=[3],
        rodada=2, motivo="reposição_CD2_PA1",
    )
    assert t.janela_dias == [3]
