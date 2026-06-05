"""Lê snapshots de rodada e gera plots/tabela."""
from __future__ import annotations
import json
from pathlib import Path
from typing import Any, Dict, List

import matplotlib.pyplot as plt
import pandas as pd


def ler_snapshots(dir_path: Path) -> List[Dict[str, Any]]:
    dir_path = Path(dir_path)
    if not dir_path.exists():
        return []
    return [json.loads(f.read_text(encoding="utf-8"))
            for f in sorted(dir_path.glob("historico_rodada_*.json"))]


def tabela_resumo(snaps: List[Dict[str, Any]]) -> pd.DataFrame:
    rows = []
    for s in snaps:
        e = s["estado"]
        ex = s.get("extras", {})
        rows.append({
            "rodada": s["rodada"],
            "transportes": ex.get("n_transportes", 0),
            "ops_atendidas": ex.get("n_atendidas", 0),
            "ops_descartadas": ex.get("n_descartadas", 0),
            "estoque_mp1_F1": e.get("estoque_mp_fabrica", {}).get("F1", {}).get("MP1", 0),
            "estoque_mp2_F1": e.get("estoque_mp_fabrica", {}).get("F1", {}).get("MP2", 0),
            "estoque_mp3_F1": e.get("estoque_mp_fabrica", {}).get("F1", {}).get("MP3", 0),
            "estoque_pa1_cd1": e.get("estoque_pa_cd", {}).get("CD1", {}).get("PA1", 0),
            "estoque_pa1_cd2": e.get("estoque_pa_cd", {}).get("CD2", {}).get("PA1", 0),
            "estoque_pa2_cd1": e.get("estoque_pa_cd", {}).get("CD1", {}).get("PA2", 0),
            "estoque_pa2_cd2": e.get("estoque_pa_cd", {}).get("CD2", {}).get("PA2", 0),
            "estoque_pa3_cd1": e.get("estoque_pa_cd", {}).get("CD1", {}).get("PA3", 0),
            "estoque_pa3_cd2": e.get("estoque_pa_cd", {}).get("CD2", {}).get("PA3", 0),
        })
    return pd.DataFrame(rows)


def plot_historico(dir_path: Path) -> None:
    snaps = ler_snapshots(dir_path)
    if not snaps:
        print("Sem histórico ainda.")
        return
    df = tabela_resumo(snaps)
    fig, axes = plt.subplots(2, 3, figsize=(15, 8))
    ax = axes[0, 0]
    ax.plot(df["rodada"], df["estoque_mp1_F1"], label="MP1")
    ax.plot(df["rodada"], df["estoque_mp2_F1"], label="MP2")
    ax.plot(df["rodada"], df["estoque_mp3_F1"], label="MP3")
    ax.set_title("Estoque MP em F1 (ton)"); ax.legend(); ax.set_xlabel("Rodada")

    ax = axes[0, 1]
    ax.plot(df["rodada"], df["estoque_pa1_cd1"], label="CD1")
    ax.plot(df["rodada"], df["estoque_pa1_cd2"], label="CD2")
    ax.set_title("Estoque PA1 nos CDs"); ax.legend(); ax.set_xlabel("Rodada")

    ax = axes[0, 2]
    ax.plot(df["rodada"], df["transportes"])
    ax.set_title("Nº transportes na rodada"); ax.set_xlabel("Rodada")

    ax = axes[1, 0]
    ax.plot(df["rodada"], df["ops_atendidas"], label="atendidas")
    ax.plot(df["rodada"], df["ops_descartadas"], label="descartadas")
    ax.set_title("OPs"); ax.legend(); ax.set_xlabel("Rodada")

    ax = axes[1, 1]
    ax.plot(df["rodada"], df["estoque_pa2_cd1"], label="CD1")
    ax.plot(df["rodada"], df["estoque_pa2_cd2"], label="CD2")
    ax.set_title("Estoque PA2 nos CDs"); ax.legend(); ax.set_xlabel("Rodada")

    ax = axes[1, 2]
    ax.plot(df["rodada"], df["estoque_pa3_cd1"], label="CD1")
    ax.plot(df["rodada"], df["estoque_pa3_cd2"], label="CD2")
    ax.set_title("Estoque PA3 nos CDs"); ax.legend(); ax.set_xlabel("Rodada")

    plt.tight_layout()
    plt.show()
    print(df.to_string(index=False))
