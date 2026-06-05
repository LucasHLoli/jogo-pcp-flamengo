import shutil
from pathlib import Path
from src.pipeline import run_rodada

BASE = Path(__file__).resolve().parents[1]


def test_run_rodada_1_smoke(tmp_path, monkeypatch):
    rodadas_src = BASE / "rodadas"
    rodadas_dst = tmp_path / "rodadas"
    rodadas_dst.mkdir()
    shutil.copy(rodadas_src / "FLAMENGO.xlsm", rodadas_dst / "FLAMENGO.xlsm")
    shutil.copy(rodadas_src / "Rodada 1.xlsm", rodadas_dst / "Rodada 1.xlsm")
    shutil.copytree(BASE / "data", tmp_path / "data")

    monkeypatch.chdir(tmp_path)

    resumo = run_rodada(rodada_n=1, rodada_xlsm_path=rodadas_dst / "Rodada 1.xlsm")
    assert "transportes" in resumo
    assert (tmp_path / "estado" / "state.json").exists()
    assert (tmp_path / "estado" / "historico_rodada_1.json").exists()
    assert (rodadas_dst / "FLAMENGO.xlsm").exists()


def test_run_rodada_com_ops_dict(tmp_path, monkeypatch):
    rodadas_src = BASE / "rodadas"
    rodadas_dst = tmp_path / "rodadas"
    rodadas_dst.mkdir()
    shutil.copy(rodadas_src / "FLAMENGO.xlsm", rodadas_dst / "FLAMENGO.xlsm")
    shutil.copy(rodadas_src / "Rodada 1.xlsm", rodadas_dst / "Rodada 1.xlsm")
    shutil.copytree(BASE / "data", tmp_path / "data")
    monkeypatch.chdir(tmp_path)

    ops = [
        {"cidade": "São Paulo", "pa": "PA1", "qtd": 50000, "dia_entrega": 5},
        {"cidade": "Rio de Janeiro", "pa": "PA2", "qtd": 30000, "dia_entrega": 4},
    ]
    precos = {"PA1": 78.50, "PA2": 51.20, "PA3": 24.80}

    resumo = run_rodada(
        rodada_n=2,
        rodada_xlsm_path=rodadas_dst / "Rodada 1.xlsm",  # reusar Rodada 1 como placeholder
        ops=ops,
        precos=precos,
    )
    assert "cockpit" in resumo
    assert resumo["receita"] >= 0
    assert "margem_pct" in resumo
    assert "alertas" in resumo
