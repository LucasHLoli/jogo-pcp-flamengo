import pytest
from pathlib import Path
from src.config import Config
from src.domain import TarefaTransporte
from src.lp_modal import otimizar_modal

BASE = Path(__file__).resolve().parents[1]


@pytest.fixture(scope="module")
def cfg():
    return Config.load(BASE)


def test_otimiza_2_tarefas(cfg):
    tarefas = [
        TarefaTransporte(origem_cidade="Joinville", destino_cidade="Santos",
                         item="PA1", qtd=80000, janela_dias=[2, 3, 4],
                         rodada=2, motivo="reposição_CD2_PA1",
                         origem_tipo="Fábrica", destino_tipo="CD"),
        TarefaTransporte(origem_cidade="Manaus", destino_cidade="Joinville",
                         item="MP1", qtd=24.0, janela_dias=[1, 2, 3, 4, 5],
                         rodada=2, motivo="compra_MP1",
                         origem_tipo="Fornecedor", destino_tipo="Fábrica"),
    ]
    planos = otimizar_modal(tarefas, cfg, rodada_n=2)
    assert len(planos) >= 2
    for p in planos:
        cap = cfg.cap_modal_por_item[p.modal][p.item]
        assert p.qtd <= cap + 1e-3


def test_janela_unica_respeita(cfg):
    tarefas = [
        TarefaTransporte(origem_cidade="Joinville", destino_cidade="Santos",
                         item="PA1", qtd=10000, janela_dias=[3],
                         rodada=2, motivo="reposição_CD2_PA1_d3",
                         origem_tipo="Fábrica", destino_tipo="CD"),
    ]
    planos = otimizar_modal(tarefas, cfg, rodada_n=2)
    assert all(p.dia_coleta == 3 for p in planos)
