from pathlib import Path
from src.io_xlsm import ler_instalacoes, ler_sol_transp, ler_op_rodada, calcular_rod_dia_chegada

BASE = Path(__file__).resolve().parents[1]
FLAMENGO = BASE / "rodadas" / "FLAMENGO.xlsm"
RODADA1 = BASE / "rodadas" / "Rodada 1.xlsm"


def test_ler_instalacoes_real():
    inst = ler_instalacoes(FLAMENGO)
    assert inst["empresa"] == "FLAMENGO"
    f1 = inst["fabricas"]["F1"]
    assert f1["cidade"] == "Joinville"
    assert f1["maquinas"] == 7
    assert f1["turnos"] == 3
    assert f1["area_mp"]["MP1"] == 127.0
    cd1 = inst["cds"]["CD1"]
    assert cd1["cidade"] == "São Luís"
    assert cd1["area_pa"]["PA3"] == 873.0


def test_ler_sol_transp_rodada1():
    items = ler_sol_transp(RODADA1, rodada=1)
    assert len(items) >= 10
    primeiro_pa = [t for t in items if t.item.startswith("PA")][0]
    assert primeiro_pa.origem_cidade == "Joinville"
    assert primeiro_pa.destino_tipo == "CD"


def test_calcular_rod_dia_chegada_dentro_da_rodada():
    rc, dc = calcular_rod_dia_chegada(rod_part=1, dia_part=1, lead_dias=3)
    assert (rc, dc) == (1, 4)


def test_calcular_rod_dia_chegada_atravessa():
    rc, dc = calcular_rod_dia_chegada(rod_part=1, dia_part=4, lead_dias=3)
    assert (rc, dc) == (2, 2)


def test_calcular_rod_dia_chegada_duas_rodadas():
    rc, dc = calcular_rod_dia_chegada(rod_part=1, dia_part=5, lead_dias=10)
    assert (rc, dc) == (3, 5)


def test_ler_op_rodada(op_rodada_dummy):
    ops = ler_op_rodada(op_rodada_dummy)
    assert len(ops) == 2
    assert ops[0].cidade == "São Paulo"
    assert ops[0].pa == "PA1"
    assert ops[0].qtd == 50000
    assert ops[0].dia_entrega == 3


def test_ler_op_rodada_inexistente(tmp_path):
    ops = ler_op_rodada(tmp_path / "nao_existe.xlsx")
    assert ops == []
