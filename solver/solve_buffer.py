"""Solver R3 + buffer PA2 nos CDs para R4.

Não planeja entregas R4 — só prepara o terreno.
R3: atende todas as 25 OPs PA3 + produz PA2 e estoca nos CDs.
Buffer = forecast HW por cidade, mapeada para o CD mais barato.
"""
from __future__ import annotations
import argparse
import io
import sys
import time
from collections import defaultdict
from pathlib import Path

import mip
import pandas as pd

BASE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE))

if sys.stdout.encoding and 'utf' not in sys.stdout.encoding.lower():
    try:
        sys.stdout.reconfigure(encoding='utf-8', errors='replace')
    except AttributeError:
        pass

from src.config import Config
from src.io_xlsm import escrever_planos_de_df
from src.planner_manual import forecast_proxima_rodada_via_hw

from solver.state import estado_r3_flamengo
from solver.solve import ops_r3
from solver.milp import (
    MODAIS, PAS, MPS, PESO_UN_TON, BOM, VEL_UN_MIN,
    CAP_MODAL_TON, FRETE_VIAGEM, FRETE_PESO, DOC_MODAL, MAX_TRANSPORTES,
    _cap_un, _carregar_leads,
)


def custo_unit_entrega(cfg, leads, cd_cidade, varejo):
    """Custo estimado por unidade pra entregar PA2 do CD ao varejo."""
    best = float("inf")
    for mod in MODAIS:
        lt = leads.get(mod, {}).get(cd_cidade, {}).get(varejo)
        if lt is None or lt > 5: continue
        if cd_cidade == varejo:
            km = 0.0
        else:
            try:
                km = float(cfg.distancias[mod].at[cd_cidade, varejo])
            except (KeyError, ValueError):
                continue
        cost_per_un = PESO_UN_TON["PA2"] * km * FRETE_PESO[mod]
        if cost_per_un < best:
            best = cost_per_un
    return best if best < float("inf") else 0


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--ns_min_r3", type=float, default=1.0,
                   help="NS R3 minimo")
    p.add_argument("--share_flamengo", type=float, default=0.40)
    p.add_argument("--buffer_pct", type=float, default=1.0,
                   help="Pct do forecast R4 a estocar")
    p.add_argument("--time_limit", type=float, default=120)
    p.add_argument("--no_write", action="store_true")
    args = p.parse_args()

    cfg = Config.load(BASE)
    estado = estado_r3_flamengo()
    ops3 = ops_r3()
    leads = _carregar_leads()

    # ===== Forecast R4 por cidade =====
    fc = forecast_proxima_rodada_via_hw(rodada_n_atual=3, base_dir=BASE)
    forecast_r4 = {}
    for (cidade, pa), q in fc.items():
        if pa == "PA2":
            q_flam = int(q * args.share_flamengo * args.buffer_pct)
            if q_flam > 0:
                forecast_r4[cidade] = q_flam

    # ===== Mapear cidade → CD mais barato (entrega R4) =====
    cidade_to_cd = {}
    cds_info = estado.cds_info
    for cidade in forecast_r4:
        best_cd = None
        best_cost = float("inf")
        for cd_id, cd_cid in cds_info.items():
            cost = custo_unit_entrega(cfg, leads, cd_cid, cidade)
            if cost < best_cost:
                best_cost = cost
                best_cd = cd_id
        if best_cd:
            cidade_to_cd[cidade] = best_cd

    buffer_por_cd = defaultdict(float)
    for cidade, cd in cidade_to_cd.items():
        buffer_por_cd[cd] += forecast_r4[cidade]

    print(f"\n=== SOLVER BUFFER R3+R4 ===\n")
    print(f"R3: {len(ops3)} OPs PA3, {sum(o['qtd'] for o in ops3):,} frascos")
    print(f"R4 forecast HW: {len(forecast_r4)} cidades, {sum(forecast_r4.values()):,} frascos PA2")
    print(f"Buffer alvo nos CDs ao fim de R3:")
    for cd, q in buffer_por_cd.items():
        cd_cid = cds_info[cd]
        print(f"  {cd} ({cd_cid}): {q:,.0f} frascos PA2")
    print(f"NS R3 alvo: {args.ns_min_r3*100:.0f}%")
    print()

    # ===== MILP =====
    def lt(modal, o, d):
        if o == d: return 0
        return leads.get(modal, {}).get(o, {}).get(d)

    def km(modal, o, d):
        if o == d: return 0.0
        try:
            v = cfg.distancias[modal].at[o, d]
            return float(v) if v and v > 0 else 0.0
        except (KeyError, ValueError):
            return 0.0

    fab = estado.fab_cidade
    cds = list(cds_info.keys())
    T = [1, 2, 3, 4, 5]

    # Op rotas R3
    op_rotas = {}
    for i, op in enumerate(ops3):
        rotas = []
        for cd in cds:
            cd_cid = cds_info[cd]
            for m1 in MODAIS:
                lt1 = lt(m1, fab, cd_cid)
                if lt1 is None: continue
                for m2 in MODAIS:
                    lt2 = lt(m2, cd_cid, op["cidade"])
                    if lt2 is None: continue
                    t_prod = op["dia_entrega"] - lt1 - lt2
                    if 1 <= t_prod <= 5:
                        rotas.append({
                            "cd": cd, "cd_cid": cd_cid, "m1": m1, "lt1": lt1,
                            "m2": m2, "lt2": lt2, "t_prod": t_prod,
                            "t_envio_cd": op["dia_entrega"] - lt2,
                        })
        op_rotas[i] = rotas

    forn_info = {}
    for mp in MPS:
        lst = []
        for f, c in cfg.fornecedores[mp]:
            l = lt("Caminhão", f, fab)
            if l is not None:
                lst.append((f, float(c), l))
        forn_info[mp] = lst

    em_transito = {(d, mp): 0.0 for d in T for mp in MPS}
    for x in estado.mp_em_transito:
        em_transito[(int(x["dia_rel"]), x["mp"])] += float(x["qtd"])

    m = mip.Model(name="FLAMENGO_BUFFER")
    m.verbose = 0

    x_op = [m.add_var(name=f"x_{i}", var_type=mip.BINARY) for i in range(len(ops3))]
    prod = {(t, pa): m.add_var(name=f"prod_{t}_{pa}", var_type=mip.INTEGER, lb=0)
            for t in T for pa in PAS}
    n_buy, qty_buy = {}, {}
    for mp in MPS:
        for fi in range(len(forn_info[mp])):
            for t in T:
                n_buy[(t, mp, fi)] = m.add_var(name=f"nbuy_{t}_{mp}_{fi}", var_type=mip.INTEGER, lb=0)
                qty_buy[(t, mp, fi)] = m.add_var(name=f"qbuy_{t}_{mp}_{fi}", lb=0)
    n_f1cd, qty_f1cd = {}, {}
    for t in T:
        for cd in cds:
            for pa in PAS:
                for mod in MODAIS:
                    ltv = lt(mod, fab, cds_info[cd])
                    if ltv is None: continue
                    n_f1cd[(t, cd, pa, mod)] = m.add_var(name=f"nf1cd_{t}_{cd}_{pa}_{mod}",
                                                          var_type=mip.INTEGER, lb=0)
                    qty_f1cd[(t, cd, pa, mod)] = m.add_var(name=f"qf1cd_{t}_{cd}_{pa}_{mod}", lb=0)
    n_cdv, qty_cdv = {}, {}
    for i, op in enumerate(ops3):
        for rota in op_rotas[i]:
            key = (rota["t_envio_cd"], rota["cd"], op["cidade"], op["pa"], rota["m2"])
            if key not in n_cdv:
                n_cdv[key] = m.add_var(name=f"ncdv_{key}".replace(" ", "_"),
                                        var_type=mip.INTEGER, lb=0)
                qty_cdv[key] = m.add_var(name=f"qcdv_{key}".replace(" ", "_"), lb=0)

    stk_mp = {(t, mp): m.add_var(name=f"stk_mp_{t}_{mp}", lb=0) for t in [0] + T for mp in MPS}
    stk_pa = {(t, cd, pa): m.add_var(name=f"stk_pa_{t}_{cd}_{pa}", lb=0)
              for t in [0] + T for cd in cds for pa in PAS}

    for mp in MPS:
        m += stk_mp[(0, mp)] == estado.estoque_mp_ton.get(mp, 0)
    for cd in cds:
        for pa in PAS:
            m += stk_pa[(0, cd, pa)] == estado.estoque_pa_cd.get(cd, {}).get(pa, 0)

    # Cap fábrica
    for t in T:
        m += mip.xsum(prod[(t, pa)] / VEL_UN_MIN[pa] for pa in PAS) <= estado.cap_min_dia
    # Cap modal
    for key in qty_f1cd:
        t, cd, pa, mod = key
        m += qty_f1cd[key] <= n_f1cd[key] * _cap_un(mod, pa)
    for key in qty_cdv:
        t, cd, c, pa, mod = key
        m += qty_cdv[key] <= n_cdv[key] * _cap_un(mod, pa)
    for key in qty_buy:
        m += qty_buy[key] <= n_buy[key] * CAP_MODAL_TON["Caminhão"]
    # PA sai F1 mesmo dia
    for t in T:
        for pa in PAS:
            m += prod[(t, pa)] == mip.xsum(
                qty_f1cd[(t, cd, pa, mod)] for cd in cds for mod in MODAIS
                if (t, cd, pa, mod) in qty_f1cd
            )
    # Balance MP
    for t in T:
        for mp in MPS:
            chegadas = []
            for fi in range(len(forn_info[mp])):
                ltf = forn_info[mp][fi][2]
                t_part = t - ltf
                if t_part in T:
                    chegadas.append(qty_buy[(t_part, mp, fi)])
            consumo = mip.xsum(prod[(t, pa)] * BOM[pa][mp] / 1_000_000 for pa in PAS)
            m += stk_mp[(t, mp)] == (
                stk_mp[(t-1, mp)] + em_transito[(t, mp)]
                + (mip.xsum(chegadas) if chegadas else 0) - consumo
            )
            m += stk_mp[(t, mp)] <= estado.cap_mp_ton[mp]
    # Balance PA CDs
    for t in T:
        for cd in cds:
            for pa in PAS:
                chegadas = []
                for mod in MODAIS:
                    ltv = lt(mod, fab, cds_info[cd])
                    if ltv is None: continue
                    t_part = t - ltv
                    if t_part in T:
                        chegadas.append(qty_f1cd[(t_part, cd, pa, mod)])
                saidas = [v for key, v in qty_cdv.items()
                          if key[0] == t and key[1] == cd and key[3] == pa]
                m += stk_pa[(t, cd, pa)] == (
                    stk_pa[(t-1, cd, pa)] + (mip.xsum(chegadas) if chegadas else 0)
                    - (mip.xsum(saidas) if saidas else 0)
                )
                m += stk_pa[(t, cd, pa)] <= estado.cap_pa_cd_un[cd][pa]
    # OPs R3 no dia exato
    for i, op in enumerate(ops3):
        rotas = op_rotas[i]
        if not rotas:
            m += x_op[i] == 0
            continue
        keys = {(r["t_envio_cd"], r["cd"], op["cidade"], op["pa"], r["m2"]) for r in rotas}
        m += mip.xsum(qty_cdv[k] for k in keys) == op["qtd"] * x_op[i]
    # NS R3
    total_q_r3 = sum(op["qtd"] for op in ops3)
    m += mip.xsum(x_op[i] * ops3[i]["qtd"] for i in range(len(ops3))) >= args.ns_min_r3 * total_q_r3
    # *** BUFFER PA2 NOS CDs AO FIM R3 — usa variáveis x_r4 por cidade ***
    # x_r4[c] binário: estocou PA2 suficiente pra atender cidade c em R4?
    x_r4 = {c: m.add_var(name=f"x_r4_{c}", var_type=mip.BINARY) for c in cidade_to_cd}
    for cd in cds:
        cidades_desse_cd = [c for c in cidade_to_cd if cidade_to_cd[c] == cd]
        if cidades_desse_cd:
            m += stk_pa[(5, cd, "PA2")] >= mip.xsum(
                x_r4[c] * forecast_r4[c] for c in cidades_desse_cd
            )
    # Cap transp
    trips = (mip.xsum(n_buy[k] for k in n_buy)
             + mip.xsum(n_f1cd[k] for k in n_f1cd)
             + mip.xsum(n_cdv[k] for k in n_cdv))
    m += trips <= MAX_TRANSPORTES

    # Objetivo: MINIMIZAR custo R3 (receita R3 é fixa se NS R3 = 100%)
    precos_r3 = {"PA1": 80, "PA2": 50, "PA3": 32}
    custo_mp = mip.xsum(qty_buy[(t, mp, fi)] * forn_info[mp][fi][1]
                        for t in T for mp in MPS for fi in range(len(forn_info[mp])))
    # PROXY LINEAR: cada viagem custa frete-viagem cheio (frete_viagem×km×n).
    # Calibrado vs DRE real R3 — sem CT-e/doc nem meia-viagem fixa.
    def frete_term(qty_v, n_v, modal, kv, item):
        return n_v * FRETE_VIAGEM[modal] * kv
    custo_frete = (
        mip.xsum(frete_term(qty_buy[(t, mp, fi)], n_buy[(t, mp, fi)], "Caminhão",
                            km("Caminhão", forn_info[mp][fi][0], fab), mp)
                 for t in T for mp in MPS for fi in range(len(forn_info[mp])))
        + mip.xsum(frete_term(qty_f1cd[key], n_f1cd[key], key[3],
                              km(key[3], fab, cds_info[key[1]]), key[2])
                   for key in qty_f1cd)
        + mip.xsum(frete_term(qty_cdv[key], n_cdv[key], key[4],
                              km(key[4], cds_info[key[1]], key[2]), key[3])
                   for key in qty_cdv)
    )
    maior_mp = {"MP1": 56000, "MP2": 22000, "MP3": 41000}
    custo_carreg_mp = mip.xsum(stk_mp[(5, mp)] * maior_mp[mp] * 0.01 for mp in MPS)
    custo_carreg_pa = mip.xsum(stk_pa[(5, cd, pa)] * precos_r3[pa] * 0.01
                                for cd in cds for pa in PAS)
    # NEGATIVO porque min (custo - receita) ≡ max (receita - custo)
    receita_r3 = mip.xsum(x_op[i] * ops3[i]["qtd"] * precos_r3[ops3[i]["pa"]]
                          for i in range(len(ops3)))
    # Receita esperada R4 = soma das cidades buffered × preço PA2
    receita_r4_esperada = mip.xsum(x_r4[c] * forecast_r4[c] * 50 for c in cidade_to_cd)

    m.objective = mip.minimize(
        custo_mp + custo_frete + custo_carreg_mp + custo_carreg_pa
        - receita_r3 - receita_r4_esperada
    )

    print(f"[MILP-BUFFER] {m.num_cols} vars, {m.num_rows} restrições")
    print(f"[MILP-BUFFER] Resolvendo (limite {args.time_limit}s)...")
    t0 = time.time()
    status = m.optimize(max_seconds=args.time_limit)
    print(f"[MILP-BUFFER] Status: {status} ({time.time()-t0:.1f}s)")

    def get(v): return v.x if v.x is not None else 0.0

    # Resultados
    ops_atend = [op for i, op in enumerate(ops3) if get(x_op[i]) > 0.5]
    prod_dia = {t: {pa: int(round(get(prod[(t, pa)]))) for pa in PAS} for t in T}
    stk_mp_fim = {mp: get(stk_mp[(5, mp)]) for mp in MPS}
    stk_pa_fim = {cd: {pa: int(round(get(stk_pa[(5, cd, pa)]))) for pa in PAS} for cd in cds}

    # Custos REAIS
    receita_val = sum(int(op["qtd"]) * precos_r3[op["pa"]] for op in ops_atend)
    custo_mp_val = sum(get(qty_buy[(t, mp, fi)]) * forn_info[mp][fi][1]
                       for t in T for mp in MPS for fi in range(len(forn_info[mp])))
    # Custo de frete EXATO pós-solve — regra oficial calibrada vs DRE real R3:
    #   ocup/viagem ≥80% → frete-viagem cheio; <80% → frete-peso puro. Sem doc.
    def _frete_exato(modal, kv, q, n, item):
        if kv is None or kv <= 0 or n <= 0:
            return 0.0
        peso = q * PESO_UN_TON[item] if item in PAS else q
        cap = CAP_MODAL_TON[modal]
        ocup = (peso / n) / cap if cap > 0 else 0
        return FRETE_VIAGEM[modal] * kv * n if ocup >= 0.8 else FRETE_PESO[modal] * kv * peso
    custo_frete_val = 0
    for (t, mp, fi) in qty_buy:
        custo_frete_val += _frete_exato("Caminhão", km("Caminhão", forn_info[mp][fi][0], fab),
                                        get(qty_buy[(t, mp, fi)]), get(n_buy[(t, mp, fi)]), mp)
    for key in qty_f1cd:
        custo_frete_val += _frete_exato(key[3], km(key[3], fab, cds_info[key[1]]),
                                        get(qty_f1cd[key]), get(n_f1cd[key]), key[2])
    for key in qty_cdv:
        custo_frete_val += _frete_exato(key[4], km(key[4], cds_info[key[1]], key[2]),
                                        get(qty_cdv[key]), get(n_cdv[key]), key[3])
    carreg_mp_v = sum(stk_mp_fim[mp] * maior_mp[mp] * 0.01 for mp in MPS)
    carreg_pa_v = sum(stk_pa_fim[cd][pa] * precos_r3[pa] * 0.01 for cd in cds for pa in PAS)
    custo_total = custo_mp_val + custo_frete_val + carreg_mp_v + carreg_pa_v
    lucro = receita_val - custo_total

    print(f"\n=== RESULTADO ===")
    print(f"OPs R3 atendidas: {len(ops_atend)}/{len(ops3)} ({len(ops_atend)/len(ops3)*100:.0f}%)")
    print(f"Receita R3:           R$ {receita_val:>14,.0f}")
    print(f"Compra MP:            R$ {custo_mp_val:>14,.0f}")
    print(f"Frete:                R$ {custo_frete_val:>14,.0f}")
    print(f"Carregamento MP:      R$ {carreg_mp_v:>14,.0f}")
    print(f"Carregamento PA:      R$ {carreg_pa_v:>14,.0f}")
    print(f"CUSTO TOTAL R3:       R$ {custo_total:>14,.0f}")
    print(f"LUCRO R3:             R$ {lucro:>14,.0f}")
    print()
    print("Buffer PA2 nos CDs (fim R3):")
    for cd in cds:
        buf_atual = stk_pa_fim[cd]["PA2"]
        buf_alvo = buffer_por_cd.get(cd, 0)
        cd_cid = cds_info[cd]
        print(f"  {cd} ({cd_cid}): {buf_atual:>8,} frascos (alvo {buf_alvo:>8,.0f}) {'✅' if buf_atual >= buf_alvo else '❌'}")
    print()
    print(f"Estoque MP fim R3: {dict((mp, round(v,2)) for mp, v in stk_mp_fim.items())}")
    print(f"Min usados/dia: {dict((t, round(sum(prod_dia[t][pa]/VEL_UN_MIN[pa] for pa in PAS))) for t in T)}")

    # SOL_TRANSP
    linhas = []
    for (t, mp, fi), var_n in n_buy.items():
        nv = int(round(get(var_n)))
        qty = get(qty_buy[(t, mp, fi)])
        if nv <= 0 or qty <= 0.01: continue
        forn = forn_info[mp][fi][0]
        qpv = qty / nv
        for _ in range(nv):
            linhas.append({"Rodada": "Rodada_3", "Origem": "Fornecedor", "Cidade": forn,
                           "Dia da Coleta": f"Dia {t}", "Modal": "Caminhão", "Tipo do Produto": mp,
                           "Qtde": round(qpv, 2), "Destino": "Fábrica", "Cidade_Destino": fab})
    for key, var_n in n_f1cd.items():
        t, cd, pa, mod = key
        nv = int(round(get(var_n)))
        qty = get(qty_f1cd[key])
        if nv <= 0 or qty <= 0.5: continue
        cap = _cap_un(mod, pa); rest = int(round(qty))
        for _ in range(nv):
            q = min(rest, cap)
            if q <= 0: continue
            linhas.append({"Rodada": "Rodada_3", "Origem": "Fábrica", "Cidade": fab,
                           "Dia da Coleta": f"Dia {t}", "Modal": mod, "Tipo do Produto": pa,
                           "Qtde": q, "Destino": "CD", "Cidade_Destino": cds_info[cd]})
            rest -= q
    for key, var_n in n_cdv.items():
        t, cd, c, pa, mod = key
        nv = int(round(get(var_n)))
        qty = get(qty_cdv[key])
        if nv <= 0 or qty <= 0.5: continue
        cap = _cap_un(mod, pa); rest = int(round(qty))
        for _ in range(nv):
            q = min(rest, cap)
            if q <= 0: continue
            linhas.append({"Rodada": "Rodada_3", "Origem": "CD", "Cidade": cds_info[cd],
                           "Dia da Coleta": f"Dia {t}", "Modal": mod, "Tipo do Produto": pa,
                           "Qtde": q, "Destino": "Varejista", "Cidade_Destino": c})
            rest -= q

    df_sol = pd.DataFrame(linhas, columns=["Rodada","Origem","Cidade","Dia da Coleta","Modal",
                                            "Tipo do Produto","Qtde","Destino","Cidade_Destino"])
    df_op = pd.DataFrame([{"Dia": f"Dia {t}", **{pa: prod_dia[t][pa] for pa in PAS}} for t in T])

    print(f"\nTransportes: {len(df_sol)}/220")

    if not args.no_write and status != mip.OptimizationStatus.INFEASIBLE:
        out = BASE / "solver" / "rodadas" / "rodada_3" / "FLAMENGO.xlsm"
        n = escrever_planos_de_df(out, df_sol, df_op, rodada_n=3)
        print(f"\nFLAMENGO R3 (BUFFER) atualizado: {n} linhas em {out}")

        from solver.mesclar_historico import mesclar_historico
        mesclar_historico(rodada_alvo=3, base=BASE)


if __name__ == "__main__":
    main()
