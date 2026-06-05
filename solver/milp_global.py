"""MILP GLOBAL — R3 dia-a-dia + R4 como requisito agregado nos CDs.

Idéia:
- R3: planeja dia a dia (produção, MP, transporte) com todas as 25 OPs PA3
- R4: forecast HW dá apenas TOTAL por cidade (sem dia_entrega)
- Cada cidade R4 é mapeada para um CD (aquele que entrega mais barato)
- CD precisa ter PA2 ≥ Σ R4 demand cidades mapeadas, AO FIM de R3
- Solver decide trade-off:
    + Produzir PA2 em R3 e estocar no CD (custo carregamento 1%)
    + Comprar MP em R3 com lead_time longo p/ chegar em R4 (sem carregamento)
    + Cortar parte da demanda R4 (NS ≥ 80%)

Função objetivo:
    max  receita_R3 + receita_R4_esperada
       − compra_MP − frete_R3 − frete_R4_estimado − carregamento(MP+PA)

Restrições:
- Todas as do MILP base (cap fábrica, MP, CD, modal, NS por rodada)
- Estoque PA2 em cada CD ao fim de R3 ≥ Σ R4 atendido
- MP comprada considera capacidade do depósito DIA A DIA
- PA sai da F1 mesmo dia produção
- Entrega R3 no DIA EXATO
"""
from __future__ import annotations
import io
import json
import math
import sys
import time
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Tuple

import mip
import pandas as pd

BASE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE))
from src.config import Config

from solver.state import EstadoRodada
from solver.milp import (
    MODAIS, PAS, MPS, PESO_UN_TON, DENS_MP, BOM, VEL_UN_MIN,
    CAP_MODAL_TON, FRETE_VIAGEM, FRETE_PESO, DOC_MODAL, MAX_TRANSPORTES,
    _cap_un, _carregar_leads,
)


@dataclass
class ResultadoGlobal:
    status: str
    runtime_s: float
    # R3 (real)
    ns_r3_pct: float
    receita_r3: float
    custo_var_r3: float
    lucro_r3: float
    # R4 (estimado)
    ns_r4_pct: float
    receita_r4: float
    custo_estim_r4: float
    lucro_r4_estim: float
    # Acumulado
    lucro_horizonte: float
    # Operacional R3
    df_sol_transp_r3: pd.DataFrame
    df_op_fabricas_r3: pd.DataFrame
    n_transp_r3: int
    estoque_mp_fim_r3: Dict[str, float]
    estoque_pa_cd_fim_r3: Dict[str, Dict[str, int]]
    # R4 plano
    cidade_to_cd_r4: Dict[str, str]
    pa2_atendido_r4_por_cidade: Dict[str, int]
    pa2_no_cd_fim_r3: Dict[str, int]
    minutos_usados_por_dia: Dict[int, float]


def custo_frete_unit(modal: str, km: float, peso_un_ton: float, cap_ton: float) -> float:
    """Custo estimado de frete por unidade transportada (ocupação parcial assumida)."""
    if km <= 0:
        return DOC_MODAL[modal] / max(1, int(cap_ton / peso_un_ton))
    # Custo por unidade ≈ peso_un × km × frete_peso + doc/qty_per_viagem
    return peso_un_ton * km * FRETE_PESO[modal] + DOC_MODAL[modal] / max(1, int(cap_ton / peso_un_ton))


def resolver_global(
    estado_r3: EstadoRodada,
    ops_r3: List[Dict],
    forecast_r4_por_cidade: Dict[str, int],  # cidade → qty PA2 esperada R4
    cfg: Config,
    *,
    precos_r3: Dict[str, float] | None = None,
    preco_pa2_r4: float = 50.0,
    ns_min_r3: float = 0.80,
    ns_min_r4: float = 0.80,
    time_limit_s: float = 300,
    verbose: bool = False,
) -> ResultadoGlobal:
    """Resolve plano global R3 + R4 (R4 como buffer agregado)."""
    if precos_r3 is None:
        precos_r3 = {"PA1": 80, "PA2": 50, "PA3": 32}

    leads = _carregar_leads()

    def lt(modal, o, d):
        if o == d:
            return 0
        return leads.get(modal, {}).get(o, {}).get(d)

    def km(modal, o, d):
        if o == d:
            return 0.0
        try:
            v = cfg.distancias[modal].at[o, d]
            return float(v) if v and v > 0 else 0.0
        except (KeyError, ValueError):
            return 0.0

    fab = estado_r3.fab_cidade
    cds_info = estado_r3.cds_info
    cds = list(cds_info.keys())

    # ============ 1. MAPEAR CIDADES R4 → CD MAIS BARATO ============
    cidade_to_cd_r4 = {}  # cidade → (cd_id, custo_unit_estimado)
    for cidade, qty in forecast_r4_por_cidade.items():
        if qty <= 0:
            continue
        best_cd = None
        best_cost_per_un = float("inf")
        for cd_id in cds:
            cd_cid = cds_info[cd_id]
            for mod in MODAIS:
                ltv = lt(mod, cd_cid, cidade)
                if ltv is None:
                    continue
                # Lead must be ≤ 5 to be deliverable within R4
                if ltv > 5:
                    continue
                kmv = km(mod, cd_cid, cidade)
                c_unit = custo_frete_unit(mod, kmv, PESO_UN_TON["PA2"], CAP_MODAL_TON[mod])
                if c_unit < best_cost_per_un:
                    best_cost_per_un = c_unit
                    best_cd = cd_id
        if best_cd is None:
            # cidade não alcançável
            continue
        cidade_to_cd_r4[cidade] = (best_cd, best_cost_per_un)

    # Total agregado por CD
    pa2_req_por_cd_max = defaultdict(float)
    for cidade, (cd, _) in cidade_to_cd_r4.items():
        pa2_req_por_cd_max[cd] += forecast_r4_por_cidade[cidade]

    if verbose:
        print(f"[GLOBAL] Mapeamento cidade R4 → CD:")
        for cidade, (cd, c) in cidade_to_cd_r4.items():
            print(f"  {cidade:<22} → {cd} ({cds_info[cd]}) custo_unit_estim={c:.4f} R$/un")
        print(f"[GLOBAL] PA2 max por CD R4:")
        for cd, q in pa2_req_por_cd_max.items():
            print(f"  {cd}: {q:,.0f} frascos")

    # ============ 2. PRÉ-PROCESSAR ROTAS R3 OPS ============
    op_rotas: Dict[int, List[Dict]] = {}
    for i, op in enumerate(ops_r3):
        rotas_op = []
        for cd in cds:
            cd_cid = cds_info[cd]
            for m1 in MODAIS:
                lt1 = lt(m1, fab, cd_cid)
                if lt1 is None:
                    continue
                for m2 in MODAIS:
                    lt2 = lt(m2, cd_cid, op["cidade"])
                    if lt2 is None:
                        continue
                    t_prod = op["dia_entrega"] - lt1 - lt2
                    if 1 <= t_prod <= 5:
                        rotas_op.append({
                            "cd": cd, "cd_cid": cd_cid, "m1": m1, "lt1": lt1,
                            "m2": m2, "lt2": lt2, "t_prod": t_prod,
                            "t_envio_cd": op["dia_entrega"] - lt2,
                        })
        op_rotas[i] = rotas_op

    # Fornecedores
    forn_info: Dict[str, List[Tuple[str, float, int]]] = {}
    for mp in MPS:
        lst = []
        for f, c in cfg.fornecedores[mp]:
            l = lt("Caminhão", f, fab)
            if l is not None:
                lst.append((f, float(c), l))
        forn_info[mp] = lst

    T = [1, 2, 3, 4, 5]

    # MP em-trânsito de R2→R3
    em_transito = {(d, mp): 0.0 for d in T for mp in MPS}
    for x in estado_r3.mp_em_transito:
        em_transito[(int(x["dia_rel"]), x["mp"])] += float(x["qtd"])

    # ============ 3. MILP ============
    m = mip.Model(name="FLAMENGO_GLOBAL")
    m.verbose = 1 if verbose else 0

    # Vars R3 OPs (binary)
    x_op = [m.add_var(name=f"x_{i}", var_type=mip.BINARY) for i in range(len(ops_r3))]

    # Vars R4 OPs (binary por cidade — atende ou não a cidade inteira)
    x_r4 = {cidade: m.add_var(name=f"x_r4_{cidade}", var_type=mip.BINARY)
            for cidade in cidade_to_cd_r4}

    # Produção
    prod = {(t, pa): m.add_var(name=f"prod_{t}_{pa}", var_type=mip.INTEGER, lb=0)
            for t in T for pa in PAS}

    # Compra MP
    n_buy = {}
    qty_buy = {}
    for mp in MPS:
        for fi in range(len(forn_info[mp])):
            for t in T:
                n_buy[(t, mp, fi)] = m.add_var(name=f"nbuy_{t}_{mp}_{fi}", var_type=mip.INTEGER, lb=0)
                qty_buy[(t, mp, fi)] = m.add_var(name=f"qbuy_{t}_{mp}_{fi}", lb=0)

    # F1 → CD
    n_f1cd = {}; qty_f1cd = {}
    for t in T:
        for cd in cds:
            for pa in PAS:
                for mod in MODAIS:
                    ltv = lt(mod, fab, cds_info[cd])
                    if ltv is None: continue
                    n_f1cd[(t, cd, pa, mod)] = m.add_var(name=f"nf1cd_{t}_{cd}_{pa}_{mod}",
                                                          var_type=mip.INTEGER, lb=0)
                    qty_f1cd[(t, cd, pa, mod)] = m.add_var(name=f"qf1cd_{t}_{cd}_{pa}_{mod}", lb=0)

    # CD → Varejo (só pra R3 OPs)
    n_cdv = {}; qty_cdv = {}
    for i, op in enumerate(ops_r3):
        for rota in op_rotas[i]:
            key = (rota["t_envio_cd"], rota["cd"], op["cidade"], op["pa"], rota["m2"])
            if key not in n_cdv:
                n_cdv[key] = m.add_var(name=f"ncdv_{key[0]}_{key[1]}_{key[2]}_{key[3]}_{key[4]}",
                                        var_type=mip.INTEGER, lb=0)
                qty_cdv[key] = m.add_var(name=f"qcdv_{key[0]}_{key[1]}_{key[2]}_{key[3]}_{key[4]}", lb=0)

    # Estoques
    stk_mp = {(t, mp): m.add_var(name=f"stk_mp_{t}_{mp}", lb=0) for t in [0] + T for mp in MPS}
    stk_pa = {(t, cd, pa): m.add_var(name=f"stk_pa_{t}_{cd}_{pa}", lb=0)
              for t in [0] + T for cd in cds for pa in PAS}

    # Estoques iniciais
    for mp in MPS:
        m += stk_mp[(0, mp)] == estado_r3.estoque_mp_ton.get(mp, 0)
    for cd in cds:
        for pa in PAS:
            m += stk_pa[(0, cd, pa)] == estado_r3.estoque_pa_cd.get(cd, {}).get(pa, 0)

    # ============ RESTRIÇÕES ============

    # Cap fábrica
    for t in T:
        m += mip.xsum(prod[(t, pa)] / VEL_UN_MIN[pa] for pa in PAS) <= estado_r3.cap_min_dia

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

    # Balance MP F1
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
                + (mip.xsum(chegadas) if chegadas else 0)
                - consumo
            )
            m += stk_mp[(t, mp)] <= estado_r3.cap_mp_ton[mp]

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
                    stk_pa[(t-1, cd, pa)]
                    + (mip.xsum(chegadas) if chegadas else 0)
                    - (mip.xsum(saidas) if saidas else 0)
                )
                m += stk_pa[(t, cd, pa)] <= estado_r3.cap_pa_cd_un[cd][pa]

    # Entrega R3 no DIA EXATO
    for i, op in enumerate(ops_r3):
        rotas = op_rotas[i]
        if not rotas:
            m += x_op[i] == 0
            continue
        keys = {(r["t_envio_cd"], r["cd"], op["cidade"], op["pa"], r["m2"]) for r in rotas}
        m += mip.xsum(qty_cdv[k] for k in keys) == op["qtd"] * x_op[i]

    # NS R3 ≥ ns_min_r3
    total_q_r3 = sum(op["qtd"] for op in ops_r3)
    m += mip.xsum(x_op[i] * ops_r3[i]["qtd"] for i in range(len(ops_r3))) >= ns_min_r3 * total_q_r3

    # *** CONSTRAINT R4: PA2 em CADA CD ao fim de R3 ≥ Σ R4 atendido pela cidade mapeada ***
    for cd in cds:
        cidades_desse_cd = [c for c, (cd_, _) in cidade_to_cd_r4.items() if cd_ == cd]
        if not cidades_desse_cd:
            continue
        m += stk_pa[(5, cd, "PA2")] >= mip.xsum(
            x_r4[c] * forecast_r4_por_cidade[c] for c in cidades_desse_cd
        )

    # NS R4 ≥ ns_min_r4
    total_q_r4 = sum(forecast_r4_por_cidade[c] for c in cidade_to_cd_r4)
    if total_q_r4 > 0:
        m += mip.xsum(x_r4[c] * forecast_r4_por_cidade[c] for c in cidade_to_cd_r4) >= ns_min_r4 * total_q_r4

    # Cap transportes R3
    trips_r3 = (
        mip.xsum(n_buy[k] for k in n_buy)
        + mip.xsum(n_f1cd[k] for k in n_f1cd)
        + mip.xsum(n_cdv[k] for k in n_cdv)
    )
    m += trips_r3 <= MAX_TRANSPORTES

    # ============ OBJETIVO ============
    # Receita R3
    receita_r3_expr = mip.xsum(
        x_op[i] * ops_r3[i]["qtd"] * precos_r3[ops_r3[i]["pa"]] for i in range(len(ops_r3))
    )
    # Receita esperada R4 (do CD vai sair PA2 conforme x_r4 indica)
    receita_r4_expr = mip.xsum(
        x_r4[c] * forecast_r4_por_cidade[c] * preco_pa2_r4 for c in cidade_to_cd_r4
    )

    # Compra MP R3
    custo_compra_mp = mip.xsum(
        qty_buy[(t, mp, fi)] * forn_info[mp][fi][1]
        for t in T for mp in MPS for fi in range(len(forn_info[mp]))
    )

    # Frete R3 — PROXY LINEAR: cada viagem custa frete-viagem cheio (frete_viagem×km×n).
    # Calibrado vs DRE real R3: sem CT-e/doc nem meia-viagem fixa. Custo exato
    # (≥80% viagem / <80% peso) é recomputado pós-solve.
    def frete_term(qty_v, n_v, modal, kv, item):
        return n_v * FRETE_VIAGEM[modal] * kv

    custo_frete_r3 = (
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

    # Frete R4 estimado (cidade × custo_unit × x_r4)
    custo_frete_r4_estim = mip.xsum(
        x_r4[c] * forecast_r4_por_cidade[c] * cidade_to_cd_r4[c][1]
        for c in cidade_to_cd_r4
    )

    # Carregamento ao FIM de R3 (de tudo que ficou estocado)
    maior_mp = {"MP1": 56000, "MP2": 22000, "MP3": 41000}
    custo_carreg_mp = mip.xsum(stk_mp[(5, mp)] * maior_mp[mp] * 0.01 for mp in MPS)
    custo_carreg_pa = mip.xsum(stk_pa[(5, cd, pa)] * precos_r3[pa] * 0.01
                                for cd in cds for pa in PAS)

    # Objetivo: max (receita - custo) ≡ min (custo - receita)
    m.objective = mip.minimize(
        custo_compra_mp + custo_frete_r3 + custo_frete_r4_estim
        + custo_carreg_mp + custo_carreg_pa
        - receita_r3_expr - receita_r4_expr
    )

    print(f"[GLOBAL] Modelo: {m.num_cols} vars, {m.num_rows} restrições")
    print(f"[GLOBAL] Resolvendo (limite {time_limit_s}s)...")
    t0 = time.time()
    status = m.optimize(max_seconds=time_limit_s)
    runtime = time.time() - t0
    print(f"[GLOBAL] Status: {status} ({runtime:.1f}s)")

    if status not in (mip.OptimizationStatus.OPTIMAL, mip.OptimizationStatus.FEASIBLE):
        return ResultadoGlobal(
            status=str(status), runtime_s=runtime,
            ns_r3_pct=0, receita_r3=0, custo_var_r3=0, lucro_r3=0,
            ns_r4_pct=0, receita_r4=0, custo_estim_r4=0, lucro_r4_estim=0,
            lucro_horizonte=0,
            df_sol_transp_r3=pd.DataFrame(), df_op_fabricas_r3=pd.DataFrame(),
            n_transp_r3=0, estoque_mp_fim_r3={}, estoque_pa_cd_fim_r3={},
            cidade_to_cd_r4={}, pa2_atendido_r4_por_cidade={}, pa2_no_cd_fim_r3={},
            minutos_usados_por_dia={},
        )

    # ============ EXTRAIR SOLUÇÃO ============
    def get(var):
        return var.x if var.x is not None else 0.0

    # OPs R3
    ops_atend_r3 = [op for i, op in enumerate(ops_r3) if get(x_op[i]) > 0.5]
    qty_atend_r3 = sum(int(op["qtd"]) for op in ops_atend_r3)

    # OPs R4
    pa2_atend = {c: int(get(x_r4[c])) * int(forecast_r4_por_cidade[c])
                 for c in cidade_to_cd_r4}
    qty_atend_r4 = sum(pa2_atend.values())

    # Produção dia a dia
    prod_dia = {t: {pa: int(round(get(prod[(t, pa)]))) for pa in PAS} for t in T}

    # SOL_TRANSP R3
    linhas = []
    # Forn → F1
    for (t, mp, fi), var_n in n_buy.items():
        nv = int(round(get(var_n)))
        qty = get(qty_buy[(t, mp, fi)])
        if nv <= 0 or qty <= 0.01: continue
        forn = forn_info[mp][fi][0]
        qpv = qty / nv
        for _ in range(nv):
            linhas.append({
                "Rodada": "Rodada_3", "Origem": "Fornecedor", "Cidade": forn,
                "Dia da Coleta": f"Dia {t}", "Modal": "Caminhão", "Tipo do Produto": mp,
                "Qtde": round(qpv, 2), "Destino": "Fábrica", "Cidade_Destino": fab,
            })
    # F1 → CD
    for key, var_n in n_f1cd.items():
        t, cd, pa, mod = key
        nv = int(round(get(var_n)))
        qty = get(qty_f1cd[key])
        if nv <= 0 or qty <= 0.5: continue
        cap_un = _cap_un(mod, pa)
        rest = int(round(qty))
        for _ in range(nv):
            q = min(rest, cap_un)
            if q <= 0: continue
            linhas.append({
                "Rodada": "Rodada_3", "Origem": "Fábrica", "Cidade": fab,
                "Dia da Coleta": f"Dia {t}", "Modal": mod, "Tipo do Produto": pa,
                "Qtde": q, "Destino": "CD", "Cidade_Destino": cds_info[cd],
            })
            rest -= q
    # CD → Varejo (só R3)
    for key, var_n in n_cdv.items():
        t, cd, c, pa, mod = key
        nv = int(round(get(var_n)))
        qty = get(qty_cdv[key])
        if nv <= 0 or qty <= 0.5: continue
        cap_un = _cap_un(mod, pa)
        rest = int(round(qty))
        for _ in range(nv):
            q = min(rest, cap_un)
            if q <= 0: continue
            linhas.append({
                "Rodada": "Rodada_3", "Origem": "CD", "Cidade": cds_info[cd],
                "Dia da Coleta": f"Dia {t}", "Modal": mod, "Tipo do Produto": pa,
                "Qtde": q, "Destino": "Varejista", "Cidade_Destino": c,
            })
            rest -= q

    df_sol = pd.DataFrame(linhas, columns=["Rodada","Origem","Cidade","Dia da Coleta",
                                            "Modal","Tipo do Produto","Qtde","Destino","Cidade_Destino"])
    df_op = pd.DataFrame([{"Dia": f"Dia {t}", **{pa: prod_dia[t][pa] for pa in PAS}} for t in T])

    # Custos reais
    receita_r3_val = sum(int(op["qtd"]) * precos_r3[op["pa"]] for op in ops_atend_r3)
    receita_r4_val = qty_atend_r4 * preco_pa2_r4
    custo_compra_val = sum(get(qty_buy[(t, mp, fi)]) * forn_info[mp][fi][1]
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
    custo_frete_r3_val = 0
    for (t, mp, fi) in qty_buy:
        custo_frete_r3_val += _frete_exato("Caminhão", km("Caminhão", forn_info[mp][fi][0], fab),
                                           get(qty_buy[(t, mp, fi)]), get(n_buy[(t, mp, fi)]), mp)
    for key in qty_f1cd:
        custo_frete_r3_val += _frete_exato(key[3], km(key[3], fab, cds_info[key[1]]),
                                           get(qty_f1cd[key]), get(n_f1cd[key]), key[2])
    for key in qty_cdv:
        custo_frete_r3_val += _frete_exato(key[4], km(key[4], cds_info[key[1]], key[2]),
                                           get(qty_cdv[key]), get(n_cdv[key]), key[3])
    estoque_mp_fim = {mp: get(stk_mp[(5, mp)]) for mp in MPS}
    estoque_pa_fim = {cd: {pa: int(round(get(stk_pa[(5, cd, pa)]))) for pa in PAS} for cd in cds}
    custo_carreg_mp_val = sum(estoque_mp_fim[mp] * maior_mp[mp] * 0.01 for mp in MPS)
    custo_carreg_pa_val = sum(estoque_pa_fim[cd][pa] * precos_r3[pa] * 0.01
                               for cd in cds for pa in PAS)
    custo_frete_r4_val = sum(pa2_atend[c] * cidade_to_cd_r4[c][1] for c in cidade_to_cd_r4)
    custo_var_r3 = custo_compra_val + custo_frete_r3_val + custo_carreg_mp_val + custo_carreg_pa_val
    lucro_r3_val = receita_r3_val - custo_var_r3
    lucro_r4_val = receita_r4_val - custo_frete_r4_val

    return ResultadoGlobal(
        status=str(status), runtime_s=runtime,
        ns_r3_pct=qty_atend_r3 / max(1, total_q_r3) * 100,
        receita_r3=receita_r3_val, custo_var_r3=custo_var_r3, lucro_r3=lucro_r3_val,
        ns_r4_pct=qty_atend_r4 / max(1, total_q_r4) * 100 if total_q_r4 > 0 else 0,
        receita_r4=receita_r4_val, custo_estim_r4=custo_frete_r4_val, lucro_r4_estim=lucro_r4_val,
        lucro_horizonte=lucro_r3_val + lucro_r4_val,
        df_sol_transp_r3=df_sol, df_op_fabricas_r3=df_op,
        n_transp_r3=len(df_sol),
        estoque_mp_fim_r3=estoque_mp_fim,
        estoque_pa_cd_fim_r3=estoque_pa_fim,
        cidade_to_cd_r4={c: cd for c, (cd, _) in cidade_to_cd_r4.items()},
        pa2_atendido_r4_por_cidade=pa2_atend,
        pa2_no_cd_fim_r3={cd: estoque_pa_fim[cd]["PA2"] for cd in cds},
        minutos_usados_por_dia={t: sum(get(prod[(t, pa)]) / VEL_UN_MIN[pa] for pa in PAS) for t in T},
    )
