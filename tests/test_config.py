from pathlib import Path
import math
from src.config import Config

BASE = Path(__file__).resolve().parents[1]


def test_carrega_parametros():
    cfg = Config.load(BASE)
    assert cfg.BoM["PA1"]["MP1"] == 60
    assert cfg.BoM["PA1"]["peso_total_g"] == 300
    assert math.isclose(cfg.peso_un_ton["PA1"], 3e-4, rel_tol=1e-6)
    assert math.isclose(cfg.peso_un_ton["PA3"], 1.5e-4, rel_tol=1e-6)
    assert cfg.cap_modal_ton["Caminhão"] == 24
    assert cfg.cap_modal_por_item["Caminhão"]["PA1"] == 80000  # 24 / 3e-4
    assert cfg.cap_modal_por_item["Avião"]["PA1"] == 3333      # floor(1 / 3e-4)
    assert cfg.cap_modal_por_item["Navio"]["MP1"] == 100
    assert len(cfg.fornecedores["MP1"]) == 2
    assert cfg.ne_por_cidade["São Paulo"] == 1
    assert cfg.ne_por_cidade["Joinville"] == 6


def test_carrega_distancias():
    cfg = Config.load(BASE)
    assert "Caminhão" in cfg.distancias
    assert cfg.distancias["Caminhão"].shape[0] == 25
    assert len(cfg.rotas_navio_validas) > 0
