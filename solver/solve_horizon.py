"""Entry point: solver MULTI-RODADA R3+R4.

Uso:
    python solver/solve_horizon.py --rodada 3 --time_limit 300

Resolve R3+R4 simultaneamente, com R4 OPs vindas do forecast HW (PA2).
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
from solver.milp_horizon import resolver_horizonte
from solver.forecast_r4 import forecast_ops_r4
from solver.solve import ops_r3


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--rodada", type=int, default=3)
    p.add_argument("--ns_min", type=float, default=0.80)
    p.add_argument("--time_limit", type=float, default=300)
    p.add_argument("--share_flamengo", type=float, default=0.40)
    p.add_argument("--preco_pa2_r4", type=float, default=50.0,
                   help="Preço de PA2 esperado em R4 (default R$ 50)")
    p.add_argument("--no_write", action="store_true")
    p.add_argument("--conservador", action="store_true",
                   help="CD→Varejo SÓ na rodada do OP. Evita risco se forecast HW errar dia_entrega R4.")
    args = p.parse_args()

    cfg = Config.load(BASE)
    estado = estado_r3_flamengo()

    ops3 = ops_r3()
    ops4 = forecast_ops_r4(rodada_n_atual=args.rodada, share_flamengo=args.share_flamengo)

    total_r3 = sum(o["qtd"] for o in ops3)
    total_r4 = sum(o["qtd"] for o in ops4)

    print(f"\n=== SOLVER HORIZONTE — R{args.rodada} + R{args.rodada+1} ===\n")
    print(f"R{args.rodada} (conhecida):  {len(ops3):>3} OPs, {total_r3:>10,} frascos PA3")
    print(f"R{args.rodada+1} (forecast HW): {len(ops4):>3} OPs, {total_r4:>10,} frascos PA2 (share {args.share_flamengo*100:.0f}%)")
    print(f"Restrição NS ≥ {args.ns_min*100:.0f}% em CADA rodada")
    print(f"Estoque MP inicial: {estado.estoque_mp_ton}")
    print(f"MP em-trânsito R3:")
    for x in estado.mp_em_transito:
        print(f"  Dia {x['dia_rel']}: {x['qtd']:.1f}t {x['mp']} de {x['origem']}")

    print(f"Modo: {'CONSERVADOR (CD→V só na rodada do OP)' if args.conservador else 'AGRESSIVO (pode usar transp R3 p/ entregar R4)'}")

    res = resolver_horizonte(
        estado_r3=estado, ops_r3=ops3, ops_r4_forecast=ops4, cfg=cfg,
        precos_r3={"PA1": 80, "PA2": 50, "PA3": 32},
        precos_r4={"PA1": 80, "PA2": args.preco_pa2_r4, "PA3": 25},
        ns_min=args.ns_min,
        time_limit_s=args.time_limit, verbose=False,
        conservador=args.conservador,
    )

    print(f"\n=== RESULTADO ===")
    print(f"Status:                  {res.status}  ({res.runtime_s:.1f}s)")
    print()
    print(f"{'':<28}{'R3 (real)':>15}{'R4 (forecast)':>17}{'TOTAL':>15}")
    print("-" * 80)
    print(f"{'NS atingido':<28}{res.ns_r3_pct:>12.1f}%{res.ns_r4_pct:>14.1f}% {'':>15}")
    print(f"{'OPs atendidas':<28}{len(res.ops_atend_r3)}/{len(ops3):>4}{len(res.ops_atend_r4)}/{len(ops4):>5}{'':>15}")
    print(f"{'Receita R$':<28}{res.receita_r3:>15,.0f}{res.receita_r4:>17,.0f}{res.receita_r3+res.receita_r4:>15,.0f}")
    print(f"{'Custo variável R$':<28}{res.custo_var_r3:>15,.0f}{res.custo_var_r4:>17,.0f}{res.custo_var_r3+res.custo_var_r4:>15,.0f}")
    print(f"{'Lucro R$':<28}{res.lucro_r3:>15,.0f}{res.lucro_r4:>17,.0f}{res.lucro_horizonte:>15,.0f}")
    print(f"{'Transportes':<28}{res.n_transp_r3:>15}{res.n_transp_r4:>17}{'':>15}")
    print()
    print(f"Estoque MP fim R3: {dict((k, round(v, 2)) for k, v in res.estoque_mp_fim_r3.items())}")
    print(f"Estoque MP fim R4: {dict((k, round(v, 2)) for k, v in res.estoque_mp_fim_r4.items())}")
    print(f"PA2 fim R3 nos CDs: CD1={res.estoque_pa_cd_fim_r3['CD1']['PA2']:,}, CD2={res.estoque_pa_cd_fim_r3['CD2']['PA2']:,}")
    print(f"PA2 fim R4 nos CDs: CD1={res.estoque_pa_cd_fim_r4['CD1']['PA2']:,}, CD2={res.estoque_pa_cd_fim_r4['CD2']['PA2']:,}")

    if res.ops_desc_r3:
        print(f"\nOPs descartadas R3 ({len(res.ops_desc_r3)}):")
        for o in res.ops_desc_r3:
            print(f"  {o['cidade']:<22} dia={o['dia_entrega']} qtd={o['qtd']:,}")
    if res.ops_desc_r4:
        print(f"\nOPs descartadas R4 ({len(res.ops_desc_r4)}):")
        for o in res.ops_desc_r4[:8]:
            print(f"  {o['cidade']:<22} qtd={o['qtd']:,}")
        if len(res.ops_desc_r4) > 8:
            print(f"  ... +{len(res.ops_desc_r4)-8} mais")

    if not args.no_write and res.status != "OptimizationStatus.INFEASIBLE":
        out = BASE / "solver" / "rodadas" / f"rodada_{args.rodada}" / "FLAMENGO.xlsm"
        n = escrever_planos_de_df(out, res.df_sol_transp_r3, res.df_op_fabricas_r3, rodada_n=args.rodada)
        print(f"\nFLAMENGO R{args.rodada} (SOLVER HORIZONTE) atualizado: {n} linhas")
        print(f"  {out}")
        print(f"\n  [R4 não escrito — só usado pra planejamento interno do solver]")


if __name__ == "__main__":
    main()
