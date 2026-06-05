"""Entry point do solver. Roda MILP da rodada N e escreve no FLAMENGO.xlsm.

Uso:
    python solver/solve.py --rodada 3
    python solver/solve.py --rodada 3 --ns_min 0.85 --time_limit 180
"""
from __future__ import annotations
import argparse
import io
import sys
from pathlib import Path

if hasattr(sys.stdout, "buffer"):
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

BASE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE))

from src.config import Config
from src.io_xlsm import escrever_planos_de_df
from src.planner_manual import forecast_proxima_rodada_via_hw

from solver.state import consolidar_estado, estado_r3_flamengo, estado_r4_flamengo
from solver.milp import resolver_rodada


def ops_r4():
    """OPs oficiais de R4 (RODADA_04_PA3.pdf). dia_entrega RELATIVO (abs-15):
    Dia 16→1, 17→2, 18→3, 19→4, 20→5. Total 1.393.461 PA3."""
    return [{"cidade": c, "pa": "PA3", "qtd": q, "dia_entrega": d} for c, q, d in [
        ("Belém", 20902, 4), ("Belo Horizonte", 73157, 2), ("Brasília", 121928, 2),
        ("Campinas", 58525, 3), ("Campo Grande", 24386, 2), ("Cuiabá", 29263, 2),
        ("Curitiba", 107296, 3), ("Fortaleza", 71066, 4), ("Goiânia", 68279, 2),
        ("João Pessoa", 41804, 5), ("Joinville", 29263, 3), ("Maceió", 41804, 5),
        ("Manaus", 20902, 4), ("Natal", 41804, 4), ("Porto Alegre", 107296, 3),
        ("Recife", 62706, 5), ("Ribeirão Preto", 48771, 3), ("Rio de Janeiro", 97542, 2),
        ("Salvador", 83608, 5), ("Santos", 48771, 3), ("São Luís", 20902, 4),
        ("São Paulo", 121928, 3), ("Uberlândia", 24386, 2), ("Vitória", 14631, 2),
        ("Vitória da Conquista", 12541, 5),
    ]]


def ops_r5():
    """OPs oficiais de R5 (RODADA_05_PA1.pdf). PA1. dia_entrega RELATIVO (abs-20):
    Dia 21→1, 22→2, 23→3, 24→4, 25→5. Total 387.072 PA1."""
    return [{"cidade": c, "pa": "PA1", "qtd": q, "dia_entrega": d} for c, q, d in [
        ("Belém", 5225, 3), ("Belo Horizonte", 29030, 1), ("Brasília", 22257, 1),
        ("Campinas", 23224, 2), ("Campo Grande", 4451, 1), ("Cuiabá", 5342, 1),
        ("Curitiba", 19586, 2), ("Fortaleza", 17767, 3), ("Goiânia", 12464, 1),
        ("João Pessoa", 10451, 4), ("Joinville", 5342, 2), ("Maceió", 10451, 4),
        ("Manaus", 5225, 3), ("Natal", 10451, 3), ("Porto Alegre", 19586, 2),
        ("Recife", 15676, 4), ("Ribeirão Preto", 19354, 2), ("Rio de Janeiro", 38707, 1),
        ("Salvador", 20902, 4), ("Santos", 19354, 2), ("São Luís", 5225, 3),
        ("São Paulo", 48384, 2), ("Uberlândia", 9677, 1), ("Vitória", 5806, 1),
        ("Vitória da Conquista", 3135, 4),
    ]]


def ops_r6():
    """OPs oficiais de R6 (RODADA_06_PA2.pdf). PA2. dia_entrega RELATIVO (abs-25):
    Dia 26→1, 27→2, 28→3, 29→4, 30→5. Total 962.152 PA2 (sem demanda no dia 26)."""
    return [{"cidade": c, "pa": "PA2", "qtd": q, "dia_entrega": d} for c, q, d in [
        ("Belém", 16838, 2), ("Belo Horizonte", 50513, 4), ("Brasília", 72161, 4),
        ("Campinas", 40410, 5), ("Campo Grande", 14432, 4), ("Cuiabá", 17319, 4),
        ("Curitiba", 63502, 5), ("Fortaleza", 57248, 2), ("Goiânia", 40410, 4),
        ("João Pessoa", 33675, 3), ("Joinville", 17319, 5), ("Maceió", 33675, 3),
        ("Manaus", 16838, 2), ("Natal", 33675, 2), ("Porto Alegre", 63502, 5),
        ("Recife", 50513, 3), ("Ribeirão Preto", 33675, 5), ("Rio de Janeiro", 67351, 4),
        ("Salvador", 67351, 3), ("Santos", 33675, 5), ("São Luís", 16838, 2),
        ("São Paulo", 84188, 5), ("Uberlândia", 16838, 4), ("Vitória", 10103, 4),
        ("Vitória da Conquista", 10103, 3),
    ]]


def ops_r3():
    return [{"cidade": c, "pa": "PA3", "qtd": q, "dia_entrega": d} for c, q, d in [
        ("Belém", 20155, 5), ("Belo Horizonte", 70544, 3), ("Brasília", 117573, 3),
        ("Campinas", 56435, 2), ("Campo Grande", 23515, 3), ("Cuiabá", 28218, 3),
        ("Curitiba", 103464, 2), ("Fortaleza", 68528, 5), ("Goiânia", 65841, 3),
        ("João Pessoa", 40311, 4), ("Joinville", 28218, 2), ("Maceió", 40311, 4),
        ("Manaus", 20155, 5), ("Natal", 40311, 5), ("Porto Alegre", 103464, 2),
        ("Recife", 60466, 4), ("Ribeirão Preto", 47029, 2), ("Rio de Janeiro", 94059, 3),
        ("Salvador", 80622, 4), ("Santos", 47029, 2), ("São Luís", 20155, 5),
        ("São Paulo", 117573, 2), ("Uberlândia", 23515, 3), ("Vitória", 14109, 3),
        ("Vitória da Conquista", 12093, 4),
    ]]


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--rodada", type=int, default=3)
    p.add_argument("--ns_min", type=float, default=0.80,
                   help="Piso de NS (default 0.80). Solver vai tentar maximizar lucro acima disso.")
    p.add_argument("--objetivo", choices=["max_lucro", "min_custo"], default="max_lucro",
                   help="max_lucro (default): max receita-custo s.t. NS≥ns_min. "
                        "min_custo: min apenas custo s.t. NS≥ns_min — cuidado, pode cortar OPs lucrativas.")
    p.add_argument("--time_limit", type=float, default=120)
    p.add_argument("--buffer_pa", type=int, default=0,
                   help="Buffer mínimo do PA da próxima rodada (default 0)")
    p.add_argument("--buffer_pa_tipo", default="PA2",
                   help="Tipo de PA para buffer (default PA2)")
    p.add_argument("--no_write", action="store_true",
                   help="Não escreve em FLAMENGO.xlsm (só relatório)")
    args = p.parse_args()

    cfg = Config.load(BASE)

    if args.rodada == 3:
        estado = estado_r3_flamengo()
        ops = ops_r3()
        precos = {"PA1": 80, "PA2": 50, "PA3": 32}
    elif args.rodada == 4:
        estado = estado_r4_flamengo()
        ops = ops_r4()
        precos = {"PA1": 80, "PA2": 50, "PA3": 20}  # preço PA3 R4 = R$20 (IND panel)
    else:
        raise NotImplementedError(f"Rodada {args.rodada} não implementada ainda")

    print(f"\n=== SOLVER MILP — RODADA {estado.rodada} ===\n")
    print(f"Estoque MP inicial: {estado.estoque_mp_ton}")
    print(f"MP em-trânsito chegando R{args.rodada}:")
    for x in estado.mp_em_transito:
        print(f"  Dia {x['dia_rel']}: {x['qtd']:.1f}t {x['mp']} de {x['origem']} (lt={x['lt']}d)")
    print(f"OPs: {len(ops)}")
    print(f"Restrição NS ≥ {args.ns_min*100:.0f}%")
    print(f"Objetivo: {args.objetivo}")

    res = resolver_rodada(
        estado=estado, ops=ops, cfg=cfg,
        pa_proxima_rodada=args.buffer_pa_tipo,
        buffer_pa_proxima_min=args.buffer_pa,
        preco_pa_rodada=precos,
        ns_min=args.ns_min,
        objetivo=args.objetivo,
        time_limit_s=args.time_limit,
        verbose=True,
    )

    custo_total = res.custo_compra_mp + res.custo_frete + res.custo_carregamento
    print(f"\n=== RESULTADO ===")
    print(f"Status:               {res.status}")
    print(f"NS atingido:          {res.ns_pct:.1f}% ({len(res.ops_atendidas)}/{len(ops)} OPs)")
    print(f"Receita:              R$ {res.receita:,.0f}")
    print(f"Custo total variável: R$ {custo_total:,.0f}")
    print(f"  Compra MP:          R$ {res.custo_compra_mp:,.0f}")
    print(f"  Frete:              R$ {res.custo_frete:,.0f}")
    print(f"  Carregamento:       R$ {res.custo_carregamento:,.0f}")
    print(f"Lucro (recv-cv):      R$ {res.resultado_rodada:,.0f}")
    print(f"Transportes:          {res.n_transportes}/220")
    print(f"Min usados/dia:       {dict((d, round(v)) for d, v in res.minutos_usados_por_dia.items())}")
    print(f"Estoque MP final (t): {dict((mp, round(v, 2)) for mp, v in res.estoque_mp_final.items())}")
    print(f"Runtime:              {res.runtime_s:.1f}s")

    if res.ops_descartadas:
        print(f"\nOPs descartadas (>{args.ns_min*100:.0f}% NS atingido):")
        for d in res.ops_descartadas:
            print(f"  {d['cidade']:<22} dia={d['dia_entrega']} qtd={d['qtd']:,}")

    # Escreve no Excel — em SOLVER/rodadas (separado da heurística!)
    if not args.no_write and res.status != "OptimizationStatus.INFEASIBLE":
        out = BASE / "solver" / "rodadas" / f"rodada_{args.rodada}" / "FLAMENGO.xlsm"
        n = escrever_planos_de_df(out, res.df_sol_transp, res.df_op_fabricas, rodada_n=args.rodada)
        print(f"\nFLAMENGO R{args.rodada} (SOLVER) atualizado: {n} linhas SOL_TRANSP")
        print(f"  {out}")


if __name__ == "__main__":
    main()
