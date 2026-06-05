import json
from pathlib import Path
from src.dashboard import ler_snapshots, tabela_resumo


def test_ler_snapshots_vazio(tmp_path):
    rows = ler_snapshots(tmp_path)
    assert rows == []


def test_ler_snapshots_com_arquivo(tmp_path):
    (tmp_path / "historico_rodada_1.json").write_text(json.dumps({
        "rodada": 1,
        "estado": {
            "rodada_atual": 1,
            "estoque_mp_fabrica": {"F1": {"MP1": 50.0, "MP2": 0.0, "MP3": 0.0}},
            "estoque_pa_cd": {"CD1": {"PA1": 100, "PA2": 0, "PA3": 0},
                              "CD2": {"PA1": 200, "PA2": 0, "PA3": 0}},
        },
        "extras": {"n_transportes": 5, "n_atendidas": 3, "n_descartadas": 0},
    }), encoding="utf-8")
    rows = ler_snapshots(tmp_path)
    assert len(rows) == 1
    df = tabela_resumo(rows)
    assert df.loc[0, "transportes"] == 5
    assert df.loc[0, "estoque_pa1_cd1"] == 100
