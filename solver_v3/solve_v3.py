"""Solver v3 — ESTOCÁSTICO no DIA da demanda.

Diferença para o v2:
  - Demanda global EXATA (forecast_v2, curva×K) — sem ruído de previsão.
  - A rodada ATUAL usa a carteira real (dias conhecidos).
  - As rodadas FUTURAS entram como cenários (1/3 PA1/PA2/PA3), e a demanda de cada
    uma é ESPALHADA pelos dias conforme a distribuição agregada observada
    (d1 4,1% · d2 22,7% · d3 23,2% · d4 38,1% · d5 11,8%). Assim o solver enxerga
    que parte da demanda pode vir cedo (dia 1) e decide quanto PRÉ-POSICIONAR.
  - `ship_from_stock=True`: o CD pode despachar de ESTOQUE pré-posicionado (buffer),
    não só de produção da rodada — é o que faz o buffer pagar em demanda de dia cedo.
  - Objetivo: max lucro − α·(frascos não atendidos) → empurra o NS o mais alto possível
    e dimensiona estoque/produção/compra de MP pra maximizar o lucro ESPERADO.

Uso: python solver_v3/solve_v3.py --rodada 8 [--alpha 100] [--time_limit 240]
"""
from __future__ import annotations
import argparse
import io
import shutil
import sys
import warnings
from pathlib import Path

warnings.filterwarnings("ignore")
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from solver_v2.solve_v2 import (
    BASE, PRECO_POR_RODADA, ESTADO_OPS, PRECO_FUT, FIX, MAIOR_MP, MAIOR_PA,
    g, extrair_plano,
)
from solver_v2.forecast_v2 import prever_proximas
from solver_v2.milp_multi import resolver_multi, DIAS
from solver.milp import PAS, MPS, BOM, VEL_UN_MIN
from src.config import Config
from src.io_xlsm import escrever_planos_de_df

# Distribuição agregada de demanda por dia (ponderada por demanda, R4..R10).
# ATUALIZADO 2026-06-15: o jogo mudou de demanda ESPALHADA (R4-R7) p/ ENTREGA-NUM-DIA-SÓ
# vindo cada vez mais cedo (R8=dia4, R9=dia3, R10=dia2). O agregado deslocou massa pros dias
# iniciais (dia2 23%→33%), fazendo o solver pré-posicionar MAIS buffer p/ rodadas futuras —
# protetor, pois R11+ deve ser outro pico cedo (onde produção na hora não cobre, ver R9/R10).
DAY_DIST = {1: 0.0351, 2: 0.3278, 3: 0.2649, 4: 0.2939, 5: 0.0783}


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--rodada", type=int, default=8)
    p.add_argument("--alpha", type=float, default=100.0, help="penalidade NS por frasco não atendido")
    p.add_argument("--time_limit", type=float, default=240)
    p.add_argument("--horizonte", type=int, default=3, help="rodadas futuras (cenários)")
    p.add_argument("--no_write", action="store_true")
    p.add_argument("--no_relax", action="store_true")
    p.add_argument("--gurobi", action="store_true")
    p.add_argument("--proteger", action="store_true",
                   help="modela demanda futura como pico-num-dia (1 cenário/dia, prob=DAY_DIST) "
                        "→ solver decide buffer ótimo p/ se proteger de demanda cedo")
    args = p.parse_args()

    cfg = Config.load(BASE)
    rodada = args.rodada
    estado = ESTADO_OPS[rodada][0]()
    ops = ESTADO_OPS[rodada][1]()
    precos = PRECO_POR_RODADA[rodada]
    produto = ops[0]["pa"]
    preco_prod = precos[produto]
    day_map = {o["cidade"]: o["dia_entrega"] for o in ops}
    fc = prever_proximas(3, rodada_atual=rodada)

    res = resolver_multi(estado, ops, precos, cfg, forecast=fc, day_map=day_map,
                         precos_futuro=PRECO_FUT, alpha=args.alpha,
                         time_limit_s=args.time_limit, verbose=False,
                         relax_cenarios=not args.no_relax, n_future=args.horizonte,
                         day_dist=DAY_DIST, ship_from_stock=True, day_scenarios=args.proteger,
                         solver_name=(__import__("mip").GUROBI if args.gurobi else __import__("mip").CBC))
    b = res.bloco_R
    df_sol, df_op, frete = extrair_plano(b, rodada, res.km_fn)

    # DRE exata (mesma contabilidade calibrada do v2)
    receita = sum(o["qtd"] * precos[o["pa"]] for i, o in enumerate(b.ops) if g(b.x_op[i]) > 0.5)
    served = sum(o["qtd"] for i, o in enumerate(b.ops) if g(b.x_op[i]) > 0.5)
    total = sum(o["qtd"] for o in b.ops)
    CHEAP = {mp: min(c for _, c in cfg.fornecedores[mp]) for mp in MPS}
    _consumo = {mp: sum(g(b.prod[(t, pa)]) * BOM[pa][mp] / 1e6 for t in DIAS for pa in PAS) for mp in MPS}
    # Custo de MP = soma DIRETA das compras (qty_buy × preço fornecedor). Com o inter-rodada,
    # parte da MP comprada chega só na próxima rodada (não aparece no estoque final), então o
    # balanço subestimaria; a soma direta é o que o jogo cobra (no dia da coleta).
    _comprado = {mp: sum(g(b.qty_buy[(t, mp, fi)]) for fi in range(len(b.forn_info[mp])) for t in DIAS) for mp in MPS}
    _custo_mp_mp = {mp: sum(g(b.qty_buy[(t, mp, fi)]) * b.forn_info[mp][fi][1]
                            for fi in range(len(b.forn_info[mp])) for t in DIAS) for mp in MPS}
    custo_mp = sum(_custo_mp_mp.values())
    _mp_diag = _custo_mp_mp
    stk_mp5 = {mp: g(b.stk_mp[(5, mp)]) for mp in MPS}
    stk_pa5 = {(cd, pa): g(b.stk_pa[(5, cd, pa)]) for cd in b.cds_info for pa in PAS}
    # Carregamento de MP: o jogo cobra sobre o estoque do último dia EXCLUINDO a MP que
    # CHEGOU no dia 5 (compra-buffer recém-recebida não paga carregamento). Validado vs
    # DRE real R8: regra dia-5-cheio dava R$6.387 (MP1 inflado 10x pela compra de 72t que
    # chegou no dia 5); excluindo o recebimento do dia 5 dá R$2.355 vs R$2.340 real (MP1 cravou).
    _consumo5 = {mp: sum(g(b.prod[(5, pa)]) * BOM[pa][mp] / 1e6 for pa in PAS) for mp in MPS}
    _receb5_mp = {mp: max(0.0, stk_mp5[mp] - g(b.stk_mp[(4, mp)]) + _consumo5[mp]) for mp in MPS}
    base_carreg_mp = {mp: max(0.0, stk_mp5[mp] - _receb5_mp[mp]) for mp in MPS}
    carreg_mp = sum(base_carreg_mp[mp] * MAIOR_MP[mp] * 0.001 for mp in MPS)
    carreg_pa = sum(stk_pa5[(cd, pa)] * MAIOR_PA[pa] * 0.01 for cd in b.cds_info for pa in PAS)  # PA: dia-5 cheio (cravou)
    fix_tot = sum(FIX.values())
    resultado = receita - custo_mp - frete - carreg_mp - carreg_pa + fix_tot

    minutos = {t: sum(g(b.prod[(t, pa)]) / VEL_UN_MIN[pa] for pa in PAS) for t in DIAS}
    util = sum(minutos.values()) / (5 * estado.cap_min_dia) * 100
    trips_mp = int((df_sol["Origem"] == "Fornecedor").sum())
    trips_f1 = int((df_sol["Origem"] == "Fábrica").sum())
    trips_cd = int((df_sol["Origem"] == "CD").sum())

    out = io.StringIO()
    P = lambda s="": out.write(s + "\n")
    P("=" * 64); P(f"  SOLVER v3 (estocástico no dia) — RODADA {rodada} — PLANO E PREVISÃO"); P("=" * 64)
    P(f"  Status: {res.status}  ({res.runtime_s:.0f}s)  alpha={args.alpha:.0f}")
    P(f"  Dias futuros ~ distribuição: " + " ".join(f"d{d}:{f*100:.0f}%" for d, f in DAY_DIST.items()))
    P("")
    P("─" * 64); P(f"  DRE PREVISTA — R{rodada}"); P("─" * 64)
    P(f"  Receita {produto} ({served:,} un × R${preco_prod})    R$ {receita:>15,.0f}")
    P(f"  (-) Compra MP                            R$ {-custo_mp:>15,.0f}")
    P(f"  (-) Frete (regra calibrada)              R$ {-frete:>15,.0f}")
    P(f"  (-) Carregamento MP (buffer)             R$ {-carreg_mp:>15,.0f}")
    P(f"  (-) Carregamento PA (buffer)             R$ {-carreg_pa:>15,.0f}")
    for k, v in FIX.items():
        P(f"  (-) {k:<36} R$ {v:>15,.0f}")
    P("  " + "-" * 58)
    P(f"  RESULTADO R{rodada}                             R$ {resultado:>15,.0f}")
    P("")
    P("─" * 64); P(f"  INDICADORES PREVISTOS — R{rodada}"); P("─" * 64)
    P(f"  Nível de Serviço (NS)        {served/total*100:>6.1f}%   ({served:,} de {total:,} frascos)")
    P(f"  Utilização fábrica média     {util:>6.1f}%")
    P(f"  Min usados/dia               {dict((t, round(v)) for t, v in minutos.items())}")
    P(f"  Transportes                  {trips_mp+trips_f1+trips_cd}/220  (MP {trips_mp} | F1→CD {trips_f1} | CD→V {trips_cd})")
    P("")
    P("─" * 64); P(f"  ESTOQUE FINAL R{rodada} (= buffer pré-posicionado p/ próxima)"); P("─" * 64)
    P(f"  MP no F1 (ton):  MP1 {stk_mp5['MP1']:.1f}  MP2 {stk_mp5['MP2']:.1f}  MP3 {stk_mp5['MP3']:.1f}")
    for mp in MPS:
        P(f"    {mp}: compra {_comprado[mp]:.1f}t (R$ {_mp_diag[mp]:,.0f}) | consumo {_consumo[mp]:.1f} | fim {stk_mp5[mp]:.1f}")
    for cd in b.cds_info:
        pas = {pa: int(stk_pa5[(cd, pa)]) for pa in PAS if stk_pa5[(cd, pa)] > 1}
        if pas:
            P(f"  PA em {cd} ({b.cds_info[cd]}): {pas}")
    P("")
    modo = "pico-num-dia: 1 cenário/dia, prob=DAY_DIST → buffer ótimo" if args.proteger else "demanda espalhada nos dias"
    P("─" * 64); P(f"  PREVISÃO DOS CENÁRIOS FUTUROS (1/3 cada produto; {modo})"); P("─" * 64)
    for rod in range(rodada + 1, rodada + 1 + args.horizonte):
        partes = []
        for pa in PAS:
            if args.proteger:
                # agrega os cenários por dia: NS esperado (ponderado por prob) e pior dia
                ds = [(dia, res.blocos.get(f"R{rod}_{pa}_d{dia}")) for dia in DAY_DIST]
                ds = [(dia, d) for dia, d in ds if d]
                if not ds:
                    continue
                ns_esp = sum(DAY_DIST[dia] * d["ns_pct"] for dia, d in ds)
                dia_pior, d_pior = min(ds, key=lambda x: x[1]["ns_pct"])
                partes.append(f"{pa}: NS~{ns_esp:.0f}% (pior dia{dia_pior}={d_pior['ns_pct']:.0f}%)")
            else:
                d = res.blocos.get(f"R{rod}_{pa}")
                if d:
                    partes.append(f"{pa}: NS {d['ns_pct']:.0f}% (R$ {d['lucro']/1e6:.1f}M)")
        if partes:
            P(f"  R{rod}  →  " + "  |  ".join(partes))
    relatorio = out.getvalue()
    (BASE / "solver_v3" / f"RELATORIO_R{rodada}.txt").write_text(relatorio, encoding="utf-8")
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
    print(relatorio)

    if not args.no_write:
        outdir = BASE / "solver_v3" / "rodadas" / f"rodada_{rodada}"
        outdir.mkdir(parents=True, exist_ok=True)
        # Template = FLAMENGO.xlsm do jogo desta rodada (com histórico R1..R(N-1)).
        # Procura na pasta da própria rodada (solver_v3); fallback p/ solver_v2 (rodadas antigas).
        template = outdir / "FLAMENGO.xlsm"
        if not template.exists():
            template = BASE / "solver_v2" / "rodadas" / f"rodada_{rodada}" / "FLAMENGO.xlsm"
        # Saída = cópia com os planos preenchidos (não sobrescreve o template do jogo).
        dest = outdir / f"FLAMENGO_ENVIO_R{rodada}.xlsm"
        shutil.copy(template, dest)
        n = escrever_planos_de_df(dest, df_sol, df_op, rodada_n=rodada)
        print(f"\n✅ Excel de entrega gerado: {dest}  ({n} linhas SOL_TRANSP R{rodada})")


if __name__ == "__main__":
    main()
