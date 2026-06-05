"""Gera OPs FORECAST para R4 a partir do Holt-Winters tunado.

R4 será 100% PA2 (segundo confirmação do usuário). Para cada cidade
distribuimos as quantidades previstas em UMA OP de PA2 com dia_entrega = 3
(meio da rodada — dá flexibilidade ao solver de produzir nos dias 1, 2 ou 3).

Para refinar: usar dia_entrega = uniforme(1..5) baseado em padrão histórico —
mas hoje todas as OPs vão pra dia 3 (heurística simples).
"""
from __future__ import annotations
import sys
from pathlib import Path
from typing import Any, Dict, List

BASE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE))

from src.planner_manual import forecast_proxima_rodada_via_hw


def forecast_ops_r4(rodada_n_atual: int = 3, share_flamengo: float = 1.0,
                    dia_entrega: int = 3) -> List[Dict[str, Any]]:
    """Retorna lista de OPs PA2 esperadas em R4.

    Args:
        rodada_n_atual: rodada que estamos resolvendo (R3 = 3 → forecast R4)
        share_flamengo: fatia da Flamengo. CALIBRADO = 1.0 (~100%): a carteira
            real ≈ a previsão nacional inteira (razão 1,06 em R3 e R4). O antigo
            0,40 era erro e subestimava a demanda em 2,5×. Ver memória share.
        dia_entrega: dia relativo da R4 em que assumimos cada OP cair (3 = meio)
    """
    fc = forecast_proxima_rodada_via_hw(rodada_n_atual=rodada_n_atual, base_dir=BASE)
    ops_r4 = []
    for (cidade, pa), qtd_brasil in fc.items():
        if pa != "PA2":
            continue
        q = int(qtd_brasil * share_flamengo)
        if q <= 0:
            continue
        ops_r4.append({
            "cidade": cidade, "pa": "PA2",
            "qtd": q, "dia_entrega": dia_entrega,
        })
    return ops_r4


def forecast_ops_r4_distribuido(rodada_n_atual: int = 3,
                                share_flamengo: float = 1.0) -> List[Dict[str, Any]]:
    """Versão alternativa: distribui qty da forecast da cidade entre dias 1-5 da R4."""
    fc = forecast_proxima_rodada_via_hw(rodada_n_atual=rodada_n_atual, base_dir=BASE)
    ops_r4 = []
    for (cidade, pa), qtd_brasil in fc.items():
        if pa != "PA2":
            continue
        q_total = int(qtd_brasil * share_flamengo)
        if q_total <= 0:
            continue
        # Distribui em 5 OPs (um por dia)
        for d in (1, 2, 3, 4, 5):
            q = q_total // 5
            if d <= q_total % 5:
                q += 1
            if q > 0:
                ops_r4.append({"cidade": cidade, "pa": "PA2", "qtd": q, "dia_entrega": d})
    return ops_r4


if __name__ == "__main__":
    import io
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
    ops = forecast_ops_r4()
    print(f"Forecast R4: {len(ops)} OPs (todas PA2, dia_entrega=3):")
    total = 0
    for op in sorted(ops, key=lambda x: -x["qtd"]):
        total += op["qtd"]
        print(f"  {op['cidade']:<22} {op['qtd']:>10,}")
    print(f"\nTOTAL R4 (Flamengo): {total:,} frascos PA2")
