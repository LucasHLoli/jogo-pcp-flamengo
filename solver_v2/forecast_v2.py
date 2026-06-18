"""forecast_v2 — gerador EXATO de demanda (substitui o HW no solver_v2).

Descoberta (validada R3..R8): a demanda do jogo é DETERMINÍSTICA e separável:

    demanda(rodada, cidade, PA) = curva_sazonal(rodada, PA) × peso_jogo(cidade, PA)

- `curva_sazonal`: a "forma" sazonal por produto ao longo das 48 rodadas (lida de
  data/demand_formula.json, referência São Paulo, Ano 1). O jogo replica a forma do
  Ano 1: game rodada N usa a curva da rodada N.
- `peso_jogo(cidade, PA)`: o peso FIXO de cada cidade no jogo. Os shares são travados
  (variam 0,001% entre rodadas do mesmo produto), então medimos uma vez:
      peso_jogo(cidade) = demanda_real(cidade, rodada_obs) / curva(rodada_obs)
  Isso embute o multiplicador K_PA (= Σ peso_jogo): PA1≈7,87 · PA2≈12,54 · PA3≈13,33.

Precisão: total nacional e por-cidade cravam (~0,04%, só arredondamento), contra o
HW que errava de -24% a +27% (ver forecast.py, mantido para backtest/comparação).

Saída de `prever_proximas`: {pa: {cidade: [v_próx, v_próx+1, ...]}} — mesma estrutura
do forecast.py (HW), para ser drop-in no solver_v2.
"""
from __future__ import annotations
import json
from pathlib import Path
from typing import Dict, List

BASE = Path(__file__).resolve().parent.parent
PAS = ("PA1", "PA2", "PA3")

# Curva sazonal SP-ref (Ano 1), carregada uma vez.
_CURVA_CACHE = None


def _curva() -> dict:
    global _CURVA_CACHE
    if _CURVA_CACHE is None:
        d = json.loads((BASE / "data" / "demand_formula.json").read_text(encoding="utf-8"))
        _CURVA_CACHE = d["curva_sazonal"]
    return _CURVA_CACHE


def _ref_observada() -> Dict[str, tuple]:
    """Última rodada REAL observada de cada produto: (rodada, {cidade: qtd}).
    Como os shares do jogo são fixos, qualquer rodada serve de referência; usamos a
    mais recente de cada produto. PA1=R5, PA2=R7, PA3=R8 (carteira já conhecida)."""
    from solver.solve import ops_r5, ops_r7, ops_r8
    obs = lambda fn: {o["cidade"]: o["qtd"] for o in fn()}
    return {"PA1": (5, obs(ops_r5)), "PA2": (7, obs(ops_r7)), "PA3": (8, obs(ops_r8))}


def prever_proximas(n_ahead: int = 3, rodada_atual: int = 8,
                    ano_curva: str = "1") -> Dict[str, Dict[str, List[float]]]:
    """Demanda EXATA das próximas `n_ahead` rodadas (calendário rodada_atual+1 ..).

    Para cada produto pa e rodada futura r:
        demanda(cidade) = curva[pa][r] × peso_jogo[pa][cidade]
    com peso_jogo medido na última rodada observada do produto.
    Retorna {pa: {cidade: [v0, v1, ...]}} (v_idx = rodada_atual+1+idx, se for `pa`).
    """
    cs = _curva()
    ref = _ref_observada()
    out: Dict[str, Dict[str, List[float]]] = {pa: {} for pa in PAS}
    for pa in PAS:
        r_obs, dem_obs = ref[pa]
        curva_obs = cs[pa][ano_curva][str(r_obs)]
        peso_jogo = {c: q / curva_obs for c, q in dem_obs.items()}  # = real/curva (embute K e share)
        for idx in range(n_ahead):
            r_fut = rodada_atual + 1 + idx
            curva_fut = cs[pa][ano_curva].get(str(r_fut))
            for c, w in peso_jogo.items():
                v = round(curva_fut * w) if curva_fut else 0
                out[pa].setdefault(c, []).append(float(v))
    return out


if __name__ == "__main__":
    import io, sys
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
    print("=== forecast_v2 (gerador exato curva × peso_jogo) ===")
    for rod in (7, 8):
        fc = prever_proximas(3, rodada_atual=rod - 1)  # prevê 'rod' como idx 0
        print(f"\nPrevendo a partir do fim de R{rod-1}:")
        for pa in PAS:
            tots = [sum(fc[pa][c][k] for c in fc[pa]) for k in range(3)]
            print(f"  {pa}: próximas 3 rodadas (R{rod}+) = " + " | ".join(f"{t:,.0f}" for t in tots))
