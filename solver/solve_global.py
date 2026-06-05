"""Entry point: solver GLOBAL R3+R4 (R4 como buffer agregado por cidade).

Uso:
    python solver/solve_global.py --rodada 3 --time_limit 300
"""
from __future__ import annotations
import argparse
import io
import sys
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE))

if hasattr(sys.stdout, "buffer"):
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

from src.config import Config
from src.io_xlsm import escrever_planos_de_df

from solver.state import estado_r3_flamengo
from solver.milp_global import resolver_global
from solver.solve import ops_r3
from src.planner_manual import forecast_proxima_rodada_via_hw


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--rodada", type=int, default=3)
    p.add_argument("--ns_min_r3", type=float, default=0.80)
    p.add_argument("--ns_min_r4", type=float, default=0.80)
    p.add_argument("--share_flamengo", type=float, default=0.40)
    p.add_argument("--preco_pa2_r4", type=float, default=50.0)
    p.add_argument("--time_limit", type=float, default=300)
    p.add_argument("--no_write", action="store_true")
    args = p.parse_args()

    cfg = Config.load(BASE)
    estado = estado_r3_flamengo()
    ops3 = ops_r3()

    # Forecast HW por cidade para PA2 R4
    fc = forecast_proxima_rodada_via_hw(rodada_n_atual=args.rodada, base_dir=BASE)
    forecast_r4 = {}
    for (cidade, pa), q in fc.items():
        if pa == "PA2":
            q_flam = int(q * args.share_flamengo)
            if q_flam > 0:
                forecast_r4[cidade] = q_flam

    print(f"\n=== SOLVER GLOBAL — R{args.rodada} + R{args.rodada+1} ===\n")
    print(f"R{args.rodada} (real): {len(ops3)} OPs PA3, {sum(o['qtd'] for o in ops3):,} frascos")
    print(f"R{args.rodada+1} (forecast HW): {len(forecast_r4)} cidades PA2, "
          f"{sum(forecast_r4.values()):,} frascos total")
    print(f"Restrições:")
    print(f"  NS R{args.rodada} ≥ {args.ns_min_r3*100:.0f}%")
    print(f"  NS R{args.rodada+1} ≥ {args.ns_min_r4*100:.0f}%")
    print(f"  Cap transp ≤ 220 (R3)")
    print(f"  Cap fábrica = 10.080 min/dia")
    print(f"  PA chega no DIA EXATO (R3 OPs)")
    print(f"  PA2 deve estar nos CDs ao fim de R3 (R4 buffer)")
    print(f"Estoque MP inicial: {estado.estoque_mp_ton}")
    print(f"MP em-trânsito R3 (de R2):")
    for x in estado.mp_em_transito:
        print(f"  Dia {x['dia_rel']}: {x['qtd']:.1f}t {x['mp']} de {x['origem']}")

    res = resolver_global(
        estado_r3=estado, ops_r3=ops3,
        forecast_r4_por_cidade=forecast_r4, cfg=cfg,
        precos_r3={"PA1": 80, "PA2": 50, "PA3": 32},
        preco_pa2_r4=args.preco_pa2_r4,
        ns_min_r3=args.ns_min_r3, ns_min_r4=args.ns_min_r4,
        time_limit_s=args.time_limit, verbose=True,
    )

    print(f"\n=== RESULTADO ===")
    print(f"Status: {res.status} ({res.runtime_s:.1f}s)")
    print()
    print(f"{'':<28}{'R3 (real)':>20}{'R4 (forecast)':>20}{'TOTAL':>20}")
    print("-" * 90)
    print(f"{'NS atingido':<28}{res.ns_r3_pct:>17.1f}% {res.ns_r4_pct:>17.1f}%")
    print(f"{'Receita R$':<28}{res.receita_r3:>20,.0f}{res.receita_r4:>20,.0f}{res.receita_r3+res.receita_r4:>20,.0f}")
    print(f"{'Custo variável R$':<28}{res.custo_var_r3:>20,.0f}{res.custo_estim_r4:>20,.0f}{res.custo_var_r3+res.custo_estim_r4:>20,.0f}")
    print(f"{'Lucro R$':<28}{res.lucro_r3:>20,.0f}{res.lucro_r4_estim:>20,.0f}{res.lucro_horizonte:>20,.0f}")
    print(f"{'Transportes R3':<28}{res.n_transp_r3:>20}")
    print()
    print(f"Estoque MP fim R3: {dict((k, round(v,2)) for k,v in res.estoque_mp_fim_r3.items())}")
    print(f"Estoque PA2 nos CDs fim R3 (= buffer R4):")
    for cd, q in res.pa2_no_cd_fim_r3.items():
        cd_cid = estado.cds_info.get(cd, cd)
        print(f"  {cd} ({cd_cid}): {q:,} frascos")
    print()
    print(f"R4 PA2 entregue por cidade (do buffer R3):")
    for cidade, q in sorted(res.pa2_atendido_r4_por_cidade.items(), key=lambda x: -x[1]):
        if q > 0:
            cd = res.cidade_to_cd_r4[cidade]
            print(f"  {cidade:<25} → {cd:<5} qty={q:,}")
    print()
    print(f"Min usados/dia: {dict((d, round(v)) for d,v in res.minutos_usados_por_dia.items())}")

    if not args.no_write and res.status not in ("OptimizationStatus.INFEASIBLE", "OptimizationStatus.NO_SOLUTION_FOUND"):
        out = BASE / "solver" / "rodadas" / f"rodada_{args.rodada}" / "FLAMENGO.xlsm"
        n = escrever_planos_de_df(out, res.df_sol_transp_r3, res.df_op_fabricas_r3, rodada_n=args.rodada)
        print(f"\nFLAMENGO R{args.rodada} (SOLVER GLOBAL) atualizado: {n} linhas SOL_TRANSP")
        print(f"  {out}")

        # Mescla histórico R1..R_atual automaticamente
        from solver.mesclar_historico import mesclar_historico
        mesclar_historico(rodada_alvo=args.rodada, base=BASE)


if __name__ == "__main__":
    main()
