"""Load/save state.json e snapshots por rodada."""
from __future__ import annotations
import json
from dataclasses import asdict
from pathlib import Path
from typing import Any, Dict

from src.domain import Estado, TransitItem, OP, OPDescartada


def estado_inicial() -> Estado:
    return Estado(
        rodada_atual=0,
        estoque_mp_fabrica={"F1": {"MP1": 0.0, "MP2": 0.0, "MP3": 0.0}},
        estoque_pa_cd={
            "CD1": {"PA1": 0, "PA2": 0, "PA3": 0},
            "CD2": {"PA1": 0, "PA2": 0, "PA3": 0},
        },
        transit=[],
        ops_pendentes=[],
        ops_atendidas=[],
        ops_descartadas=[],
    )


def carregar_estado(path: Path) -> Estado:
    path = Path(path)
    if not path.exists():
        return estado_inicial()
    data = json.loads(path.read_text(encoding="utf-8"))
    return Estado(
        rodada_atual=data["rodada_atual"],
        estoque_mp_fabrica=data["estoque_mp_fabrica"],
        estoque_pa_cd=data["estoque_pa_cd"],
        transit=[TransitItem(**t) for t in data["transit"]],
        ops_pendentes=[OP(**o) for o in data["ops_pendentes"]],
        ops_atendidas=[OP(**o) for o in data["ops_atendidas"]],
        ops_descartadas=[
            OPDescartada(op=OP(**d["op"]), motivo=d["motivo"], rodada_descarte=d["rodada_descarte"])
            for d in data["ops_descartadas"]
        ],
    )


def salvar_estado(estado: Estado, path: Path) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(asdict(estado), ensure_ascii=False, indent=2), encoding="utf-8")


def snapshot_rodada(estado: Estado, rodada_n: int, extras: Dict[str, Any], dir_path: Path) -> None:
    dir_path = Path(dir_path)
    dir_path.mkdir(parents=True, exist_ok=True)
    f = dir_path / f"historico_rodada_{rodada_n}.json"
    data = {"rodada": rodada_n, "estado": asdict(estado), "extras": extras}
    f.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
