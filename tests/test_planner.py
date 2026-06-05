import pytest
from pathlib import Path
from src.config import Config
from src.domain import Estado, OP
from src.estado import estado_inicial
from src.planner import passo1_entregas_cd_varejo

BASE = Path(__file__).resolve().parents[1]


@pytest.fixture(scope="module")
def cfg():
    return Config.load(BASE)


def test_passo1_op_atendida(cfg):
    estado = estado_inicial()
    estado.estoque_pa_cd["CD2"]["PA1"] = 100000  # Santos
    ops = [OP(rodada=2, cidade="São Paulo", pa="PA1", qtd=50000, dia_entrega=5)]
    cds_info = {"CD1": "São Luís", "CD2": "Santos"}
    tarefas, descartadas = passo1_entregas_cd_varejo(estado, ops, cfg, cds_info, rodada_n=2)
    assert len(tarefas) == 1
    assert tarefas[0].origem_cidade == "Santos"  # CD2 mais perto de SP
    assert tarefas[0].qtd == 50000
    assert descartadas == []


def test_passo1_sem_estoque_descartada(cfg):
    estado = estado_inicial()  # tudo zero
    ops = [OP(rodada=2, cidade="Manaus", pa="PA3", qtd=1000, dia_entrega=1)]
    cds_info = {"CD1": "São Luís", "CD2": "Santos"}
    tarefas, descartadas = passo1_entregas_cd_varejo(estado, ops, cfg, cds_info, rodada_n=2)
    assert tarefas == []
    assert len(descartadas) == 1
    assert descartadas[0].motivo == "sem_estoque_CD"


def test_passo1_lead_time_inviavel(cfg):
    estado = estado_inicial()
    estado.estoque_pa_cd["CD1"]["PA1"] = 100000
    ops = [OP(rodada=2, cidade="Manaus", pa="PA1", qtd=10000, dia_entrega=1)]
    cds_info = {"CD1": "São Luís"}
    tarefas, descartadas = passo1_entregas_cd_varejo(estado, ops, cfg, cds_info, rodada_n=2)
    assert tarefas == []
    assert descartadas[0].motivo == "lead_time_inviavel"


def test_passo2_reposicao_basica(cfg):
    from src.planner import passo2_reposicao_fabrica_cd
    from src.estado import estado_inicial

    estado = estado_inicial()
    estado.estoque_pa_cd["CD2"]["PA1"] = 5000
    forecast = {
        ("São Paulo", "PA1"): [50000] * 4,
        ("Rio de Janeiro", "PA1"): [30000] * 4,
    }
    cidades_por_cd = {"CD1": ["Manaus", "Belém"], "CD2": ["São Paulo", "Rio de Janeiro", "Santos"]}
    cds_info = {"CD1": "São Luís", "CD2": "Santos"}
    saidas_cd = {"CD2": {"PA1": 10000}, "CD1": {"PA1": 0}}

    necessidades = passo2_reposicao_fabrica_cd(
        estado, forecast, cfg, cds_info, cidades_por_cd, saidas_cd, rodada_n=2,
    )
    assert necessidades["CD2"]["PA1"] > 0
    assert necessidades["CD1"]["PA1"] == 0


def test_passo3_aloca_por_dia(cfg):
    from src.planner import passo3_producao

    necessidades = {
        "CD1": {"PA1": 50000, "PA2": 0, "PA3": 0},
        "CD2": {"PA1": 30000, "PA2": 100000, "PA3": 0},
    }
    planos_prod, tarefas_f1_cd = passo3_producao(
        necessidades, cfg, cds_info={"CD1": "São Luís", "CD2": "Santos"},
        rodada_n=2, fabrica="F1", fabrica_cidade="Joinville", maquinas=7, turnos=3,
    )
    tot_pa1 = sum(p.qtd for p in planos_prod if p.pa == "PA1")
    assert tot_pa1 == 80000
    tot_pa2 = sum(p.qtd for p in planos_prod if p.pa == "PA2")
    assert tot_pa2 == 100000
    for t in tarefas_f1_cd:
        assert len(t.janela_dias) == 1


def test_passo4_gera_compras(cfg):
    from src.planner import passo4_compras_mp
    from src.domain import PlanoProducao

    planos_prod = [
        PlanoProducao(rodada=2, fabrica="F1", dia=2, pa="PA1", qtd=10000),
        PlanoProducao(rodada=2, fabrica="F1", dia=3, pa="PA2", qtd=20000),
    ]
    estoque_inicial = {"MP1": 0.0, "MP2": 0.0, "MP3": 0.0}
    cap_mp = {"MP1": 127 * 2 * 0.5, "MP2": 36 * 2 * 0.7, "MP3": 42 * 2 * 0.9}
    tarefas, descartadas = passo4_compras_mp(
        planos_prod, estoque_inicial, cfg, cap_mp,
        rodada_n=2, fabrica_cidade="Joinville", transit_atual=[],
    )
    mps = {t.item for t in tarefas}
    assert "MP1" in mps and "MP2" in mps and "MP3" in mps
    for t in tarefas:
        assert t.origem_tipo == "Fornecedor"
