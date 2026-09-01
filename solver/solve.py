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


def ops_r7():
    """OPs oficiais de R7 (Rodada_07_PA2.pdf). PA2. dia_entrega RELATIVO (abs-30):
    Dia 31→1, 32→2, 33→3, 34→4, 35→5. Total 895.793 PA2 (sem demanda no dia 35).
    Totais/dia conferidos: 131.681 / 181.847 / 269.186 / 313.079."""
    return [{"cidade": c, "pa": "PA2", "qtd": q, "dia_entrega": d} for c, q, d in [
        ("Belém", 15676, 1), ("Belo Horizonte", 47029, 3), ("Brasília", 67185, 3),
        ("Campinas", 37623, 4), ("Campo Grande", 13437, 3), ("Cuiabá", 16124, 3),
        ("Curitiba", 59122, 4), ("Fortaleza", 53300, 1), ("Goiânia", 37623, 3),
        ("João Pessoa", 31353, 2), ("Joinville", 16124, 4), ("Maceió", 31353, 2),
        ("Manaus", 15676, 1), ("Natal", 31353, 1), ("Porto Alegre", 59122, 4),
        ("Recife", 47029, 2), ("Ribeirão Preto", 31353, 4), ("Rio de Janeiro", 62706, 3),
        ("Salvador", 62706, 2), ("Santos", 31353, 4), ("São Luís", 15676, 1),
        ("São Paulo", 78382, 4), ("Uberlândia", 15676, 3), ("Vitória", 9406, 3),
        ("Vitória da Conquista", 9406, 2),
    ]]


def ops_r8():
    """OPs oficiais de R8 (Rodada_08_PA3.pdf). PA3. Toda a carteira entrega no Dia 39
    → dia_entrega RELATIVO (abs-35) = 4. Total 1.335.398 PA3."""
    return [{"cidade": c, "pa": "PA3", "qtd": q, "dia_entrega": 4} for c, q in [
        ("Belém", 20031), ("Belo Horizonte", 70108), ("Brasília", 116847),
        ("Campinas", 56087), ("Campo Grande", 23369), ("Cuiabá", 28043),
        ("Curitiba", 102826), ("Fortaleza", 68105), ("Goiânia", 65435),
        ("João Pessoa", 40062), ("Joinville", 28043), ("Maceió", 40062),
        ("Manaus", 20031), ("Natal", 40062), ("Porto Alegre", 102826),
        ("Recife", 60093), ("Ribeirão Preto", 46739), ("Rio de Janeiro", 93478),
        ("Salvador", 80124), ("Santos", 46739), ("São Luís", 20031),
        ("São Paulo", 116847), ("Uberlândia", 23369), ("Vitória", 14022),
        ("Vitória da Conquista", 12019),
    ]]


def ops_r9():
    """OPs oficiais de R9 (Rodada_09_PA2.pdf). PA2. Toda a carteira entrega no Dia 43
    → dia_entrega RELATIVO (abs-40) = 3. Total 928.973 PA2 (= previsão forecast_v2 cravada)."""
    return [{"cidade": c, "pa": "PA2", "qtd": q, "dia_entrega": 3} for c, q in [
        ("Belém", 16257), ("Belo Horizonte", 48771), ("Brasília", 69673),
        ("Campinas", 39017), ("Campo Grande", 13935), ("Cuiabá", 16722),
        ("Curitiba", 61312), ("Fortaleza", 55274), ("Goiânia", 39017),
        ("João Pessoa", 32514), ("Joinville", 16722), ("Maceió", 32514),
        ("Manaus", 16257), ("Natal", 32514), ("Porto Alegre", 61312),
        ("Recife", 48771), ("Ribeirão Preto", 32514), ("Rio de Janeiro", 65028),
        ("Salvador", 65028), ("Santos", 32514), ("São Luís", 16257),
        ("São Paulo", 81285), ("Uberlândia", 16257), ("Vitória", 9754),
        ("Vitória da Conquista", 9754),
    ]]


def ops_r10():
    """OPs oficiais de R10 (Rodada_10_PA3.pdf). PA3. Toda a carteira entrega no Dia 47
    → dia_entrega RELATIVO (abs-45) = 2. Total 1.492.994 PA3 (= previsão forecast_v2: 1.492.988, diff 6).
    ATENÇÃO: demanda no dia 2 (muito cedo) — round difícil, buffer crítico."""
    return [{"cidade": c, "pa": "PA3", "qtd": q, "dia_entrega": 2} for c, q in [
        ("Belém", 22395), ("Belo Horizonte", 78382), ("Brasília", 130637),
        ("Campinas", 62706), ("Campo Grande", 26127), ("Cuiabá", 31353),
        ("Curitiba", 114960), ("Fortaleza", 76143), ("Goiânia", 73157),
        ("João Pessoa", 44790), ("Joinville", 31353), ("Maceió", 44790),
        ("Manaus", 22395), ("Natal", 44790), ("Porto Alegre", 114960),
        ("Recife", 67185), ("Ribeirão Preto", 52255), ("Rio de Janeiro", 104509),
        ("Salvador", 89580), ("Santos", 52255), ("São Luís", 22395),
        ("São Paulo", 130637), ("Uberlândia", 26127), ("Vitória", 15676),
        ("Vitória da Conquista", 13437),
    ]]


def ops_r11():
    """OPs oficiais de R11 (Rodada_11_PA1.pdf). PA1. Demanda ESPALHADA (dias 52-55).
    dia_entrega RELATIVO (abs-50): 52→2, 53→3, 54→4, 55→5. Total 381.544 PA1
    (= previsão forecast_v2: 381.542, diff 2). Por dia: d2=152.617 d3=125.910 d4=59.749 d5=43.268."""
    return [{"cidade": c, "pa": "PA1", "qtd": q, "dia_entrega": d} for c, q, d in [
        ("Belém", 5151, 5), ("Belo Horizonte", 28616, 3), ("Brasília", 21939, 3),
        ("Campinas", 22893, 2), ("Campo Grande", 4388, 3), ("Cuiabá", 5265, 3),
        ("Curitiba", 19306, 2), ("Fortaleza", 17513, 5), ("Goiânia", 12286, 3),
        ("João Pessoa", 10302, 4), ("Joinville", 5265, 2), ("Maceió", 10302, 4),
        ("Manaus", 5151, 5), ("Natal", 10302, 5), ("Porto Alegre", 19306, 2),
        ("Recife", 15452, 4), ("Ribeirão Preto", 19077, 2), ("Rio de Janeiro", 38154, 3),
        ("Salvador", 20603, 4), ("Santos", 19077, 2), ("São Luís", 5151, 5),
        ("São Paulo", 47693, 2), ("Uberlândia", 9539, 3), ("Vitória", 5723, 3),
        ("Vitória da Conquista", 3090, 4),
    ]]


def ops_r12():
    """OPs oficiais de R12 (Rodada_12_PA1.pdf + Rodada_12_PA2.pdf). RODADA DUPLA: PA1 E PA2.
    dia_entrega RELATIVO (abs-55): 56→1, 57→2, 58→3, 59→4. Espalhada.
    PA1 total 398.133 (prev 398.131), PA2 total 967.681 (prev 967.683). ÚLTIMA RODADA."""
    pa1 = [("Belém", 5375, 4), ("Belo Horizonte", 29860, 2), ("Brasília", 22893, 2),
           ("Campinas", 23888, 1), ("Campo Grande", 4579, 2), ("Cuiabá", 5494, 2),
           ("Curitiba", 20145, 1), ("Fortaleza", 18274, 4), ("Goiânia", 12820, 2),
           ("João Pessoa", 10750, 3), ("Joinville", 5494, 1), ("Maceió", 10750, 3),
           ("Manaus", 5375, 4), ("Natal", 10750, 4), ("Porto Alegre", 20145, 1),
           ("Recife", 16124, 3), ("Ribeirão Preto", 19907, 1), ("Rio de Janeiro", 39813, 2),
           ("Salvador", 21499, 3), ("Santos", 19907, 1), ("São Luís", 5375, 4),
           ("São Paulo", 49766, 1), ("Uberlândia", 9953, 2), ("Vitória", 5972, 2),
           ("Vitória da Conquista", 3225, 3)]
    pa2 = [("Belém", 16934, 4), ("Belo Horizonte", 50803, 2), ("Brasília", 72576, 2),
           ("Campinas", 40643, 1), ("Campo Grande", 14515, 2), ("Cuiabá", 17418, 2),
           ("Curitiba", 63867, 1), ("Fortaleza", 57577, 4), ("Goiânia", 40643, 2),
           ("João Pessoa", 33869, 3), ("Joinville", 17418, 1), ("Maceió", 33869, 3),
           ("Manaus", 16934, 4), ("Natal", 33869, 4), ("Porto Alegre", 63867, 1),
           ("Recife", 50803, 3), ("Ribeirão Preto", 33869, 1), ("Rio de Janeiro", 67738, 2),
           ("Salvador", 67738, 3), ("Santos", 33869, 1), ("São Luís", 16934, 4),
           ("São Paulo", 84672, 1), ("Uberlândia", 16934, 2), ("Vitória", 10161, 2),
           ("Vitória da Conquista", 10161, 3)]
    return ([{"cidade": c, "pa": "PA1", "qtd": q, "dia_entrega": d} for c, q, d in pa1] +
            [{"cidade": c, "pa": "PA2", "qtd": q, "dia_entrega": d} for c, q, d in pa2])


def ops_r13():
    """OPs oficiais de R13 (Rodada_13_PA1/PA2/PA3.pdf). RODADA TRIPLA: PA1 + PA2 + PA3.
    dia_entrega RELATIVO (abs-60): 61→1, 62→2, 63→3, 64→4 (Dia 65 vazio). Espalhada.
    Totais: PA1 304.126, PA2 696.733, PA3 995.328 → DEMANDA TOTAL 1.996.187 frascos.
    ATENÇÃO: começamos SEM buffer de PA (só 1.740 PA3 em CD1) após o "troll" da R12 (zerou
    o estoque). Capacidade da fábrica (~50.400 min/sem) só cobre ~84% da demanda total
    mesmo a pleno, e o Dia 1 sozinho pede 633.709 frascos → NS limitado por capacidade+buffer."""
    pa1 = [("Belém", 4106, 3), ("Belo Horizonte", 22810, 1), ("Brasília", 17487, 1),
           ("Campinas", 18248, 4), ("Campo Grande", 3497, 1), ("Cuiabá", 4197, 1),
           ("Curitiba", 15389, 4), ("Fortaleza", 13959, 3), ("Goiânia", 9793, 1),
           ("João Pessoa", 8211, 2), ("Joinville", 4197, 4), ("Maceió", 8211, 2),
           ("Manaus", 4106, 3), ("Natal", 8211, 3), ("Porto Alegre", 15389, 4),
           ("Recife", 12317, 2), ("Ribeirão Preto", 15206, 4), ("Rio de Janeiro", 30413, 1),
           ("Salvador", 16423, 2), ("Santos", 15206, 4), ("São Luís", 4106, 3),
           ("São Paulo", 38016, 4), ("Uberlândia", 7603, 1), ("Vitória", 4562, 1),
           ("Vitória da Conquista", 2463, 2)]
    pa2 = [("Belém", 12193, 3), ("Belo Horizonte", 36578, 1), ("Brasília", 52255, 1),
           ("Campinas", 29263, 4), ("Campo Grande", 10451, 1), ("Cuiabá", 12541, 1),
           ("Curitiba", 45984, 4), ("Fortaleza", 41455, 3), ("Goiânia", 29263, 1),
           ("João Pessoa", 24386, 2), ("Joinville", 12541, 4), ("Maceió", 24386, 2),
           ("Manaus", 12193, 3), ("Natal", 24386, 3), ("Porto Alegre", 45984, 4),
           ("Recife", 36578, 2), ("Ribeirão Preto", 24386, 4), ("Rio de Janeiro", 48771, 1),
           ("Salvador", 48771, 2), ("Santos", 24386, 4), ("São Luís", 12193, 3),
           ("São Paulo", 60964, 4), ("Uberlândia", 12193, 1), ("Vitória", 7316, 1),
           ("Vitória da Conquista", 7316, 2)]
    pa3 = [("Belém", 14930, 3), ("Belo Horizonte", 52255, 1), ("Brasília", 87091, 1),
           ("Campinas", 41804, 4), ("Campo Grande", 17418, 1), ("Cuiabá", 20902, 1),
           ("Curitiba", 76640, 4), ("Fortaleza", 50762, 3), ("Goiânia", 48771, 1),
           ("João Pessoa", 29860, 2), ("Joinville", 20902, 4), ("Maceió", 29860, 2),
           ("Manaus", 14930, 3), ("Natal", 29860, 3), ("Porto Alegre", 76640, 4),
           ("Recife", 44790, 2), ("Ribeirão Preto", 34836, 4), ("Rio de Janeiro", 69673, 1),
           ("Salvador", 59720, 2), ("Santos", 34836, 4), ("São Luís", 14930, 3),
           ("São Paulo", 87091, 4), ("Uberlândia", 17418, 1), ("Vitória", 10451, 1),
           ("Vitória da Conquista", 8958, 2)]
    return ([{"cidade": c, "pa": "PA1", "qtd": q, "dia_entrega": d} for c, q, d in pa1] +
            [{"cidade": c, "pa": "PA2", "qtd": q, "dia_entrega": d} for c, q, d in pa2] +
            [{"cidade": c, "pa": "PA3", "qtd": q, "dia_entrega": d} for c, q, d in pa3])


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
