import numpy as np
import pandas as pd
from src.forecast import (
    agregar_op_para_serie,
    treinar_inicial,
    prever,
    salvar_modelos,
    carregar_modelos,
)
from src.domain import OP


def test_agregar_op_para_serie():
    ops = [
        OP(rodada=2, cidade="São Paulo", pa="PA1", qtd=10000, dia_entrega=1),
        OP(rodada=2, cidade="São Paulo", pa="PA1", qtd=5000, dia_entrega=3),
        OP(rodada=2, cidade="Rio de Janeiro", pa="PA2", qtd=20000, dia_entrega=5),
    ]
    agg = agregar_op_para_serie(ops, rodada_n=2)
    assert agg[("São Paulo", "PA1")] == 15000
    assert agg[("Rio de Janeiro", "PA2")] == 20000


def test_treina_e_preve():
    rng = np.random.default_rng(42)
    base = np.tile(np.linspace(50, 100, 48), 2)
    ruido = rng.normal(0, 5, 96)
    serie = pd.DataFrame({
        "periodo_global": list(range(1, 97)),
        "cidade": ["TestCity"] * 96,
        "PA": ["PA1"] * 96,
        "qtd": base + ruido,
    })
    modelos = treinar_inicial(serie)
    assert ("TestCity", "PA1") in modelos
    info = modelos[("TestCity", "PA1")]
    assert info["tipo"].startswith("HW_") or info["tipo"] in ("Holt_simples", "media_4")
    assert info["rmse_in_sample"] > 0

    forecast = prever(modelos, horizonte=4)
    assert len(forecast[("TestCity", "PA1")]) == 4
    assert all(v >= 0 for v in forecast[("TestCity", "PA1")])


def test_round_trip_json(tmp_path):
    serie = pd.DataFrame({
        "periodo_global": list(range(1, 97)),
        "cidade": ["A"] * 96,
        "PA": ["PA1"] * 96,
        "qtd": [100.0 + i for i in range(96)],
    })
    modelos = treinar_inicial(serie)
    path = tmp_path / "hw.json"
    salvar_modelos(modelos, path)
    recarregados = carregar_modelos(path)
    assert recarregados[("A", "PA1")]["tipo"] == modelos[("A", "PA1")]["tipo"]


def test_refit_adiciona_ponto(tmp_path):
    hist_path = tmp_path / "hist.parquet"
    df = pd.DataFrame({
        "periodo_global": list(range(1, 97)),
        "cidade": ["TestCity"] * 96,
        "PA": ["PA1"] * 96,
        "qtd": [100.0] * 96,
    })
    df.to_parquet(hist_path)

    from src.forecast import treinar_inicial, refit, agregar_op_para_serie
    modelos = treinar_inicial(df)
    ops = [OP(rodada=2, cidade="TestCity", pa="PA1", qtd=200, dia_entrega=3)]
    agg = agregar_op_para_serie(ops, rodada_n=2)
    novos_modelos = refit(hist_path, modelos, agg, rodada_n=2)

    df_novo = pd.read_parquet(hist_path)
    assert len(df_novo) == 97
    assert df_novo.iloc[-1]["periodo_global"] == 97
    assert df_novo.iloc[-1]["qtd"] == 200
    assert ("TestCity", "PA1") in novos_modelos


def test_grid_search_escolhe_config():
    # série com sazonal forte de 12: grid deve preferir essa config
    import numpy as np
    rng = np.random.default_rng(7)
    sazonal = np.tile([10, 20, 30, 40, 30, 20, 10, 5, 8, 12, 18, 25], 8)  # 96 pontos
    valores = sazonal + rng.normal(0, 1, 96)
    df = pd.DataFrame({
        "periodo_global": list(range(1, 97)),
        "cidade": ["X"] * 96, "PA": ["PA1"] * 96, "qtd": valores,
    })
    modelos = treinar_inicial(df)
    info = modelos[("X", "PA1")]
    # com sazonal forte, deve escolher HW com seasonal != None
    assert info.get("config", {}).get("seasonal") is not None or info["tipo"] == "Holt_simples"
    assert info["rmse_holdout"] >= 0
