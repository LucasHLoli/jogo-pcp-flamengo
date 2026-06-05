"""MILP MULTI-RODADA — planeja R3 + R4 (forecast) simultaneamente.

Diferenças vs milp.py (single-rodada):
  - T = 1..10 (R3 dias 1-5, R4 dias 6-10)
  - OPs concatenam: R3 conhecidas + R4 forecast (HW)
  - Cap modal de transportes: ≤ 220 PARA CADA RODADA separadamente
  - Receita = R3 (PA3 × R$ 32) + R4 (PA2 × R$ 50)
  - Solver decide otimizar lucro do horizonte inteiro

Premissas:
  - R4 são todas PA2 (confirmado pelo usuário)
  - Preço PA2 R4 = R$ 50 (preço referência; ajustar quando souber o real)
  - R4 OPs vêm do forecast HW tunado, share Flamengo = 40%
  - dia_entrega das OPs R4 = 3 (meio da rodada) por simplicidade
  - Custos fixos: incidentes em CADA rodada (não modelados no objetivo MILP
    porque são constantes — adicionados na contabilização externa)
"""
from __future__ import annotations
import json
import math
import sys
import time
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
    MODAIS, PAS, MPS, PESO_UN_TON, DENS_MP, DENS_PA, BOM, VEL_UN_MIN,
    CAP_MODAL_TON, FRETE_VIAGEM, FRETE_PESO, DOC_MODAL, MAX_TRANSPORTES,
    _cap_un, _carregar_leads,
)


@dataclass
class ResultadoSolverHorizonte:
    status: str
    objetivo: float
    runtime_s: float

    # Por rodada
    ns_r3_pct: float
    ns_r4_pct: float
    receita_r3: float
    receita_r4: float
    custo_var_r3: float
    custo_var_r4: float
    lucro_r3: float
    lucro_r4: float
    lucro_horizonte: float

    # Detalhes
    n_transp_r3: int
    n_transp_r4: int
    ops_atend_r3: List[Dict]
    ops_atend_r4: List[Dict]
    ops_desc_r3: List[Dict]
    ops_desc_r4: List[Dict]

    df_sol_transp_r3: pd.DataFrame
    df_sol_transp_r4: pd.DataFrame
    df_op_fabricas_r3: pd.DataFrame
    df_op_fabricas_r4: pd.DataFrame

    estoque_mp_fim_r3: Dict[str, float]
    estoque_mp_fim_r4: Dict[str, float]
    estoque_pa_cd_fim_r3: Dict[str, Dict[str, int]]
    estoque_pa_cd_fim_r4: Dict[str, Dict[str, int]]


def resolver_horizonte(
    estado_r3: EstadoRodada,
    ops_r3: List[Dict],
    ops_r4_forecast: List[Dict],
    cfg: Config,
    *,
    precos_r3: Dict[str, float] | None = None,
    precos_r4: Dict[str, float] | None = None,
    ns_min: float = 0.80,
    time_limit_s: float = 300,
    verbose: bool = False,
    conservador: bool = False,
) -> ResultadoSolverHorizonte:
    """
    Args:
        conservador: se True, força CD→Varejo só dentro da própria rodada
                     (não usa transporte R3 pra entregar em R4).
                     Reduz risco se forecast HW errar, mas perde lucro horizonte.
    """
    """Resolve R3+R4 simultaneamente.

    Horizonte T = 1..10 (R3 = 1..5, R4 = 6..10).
    Dias absolutos da rodada continuam 1..5 dentro de cada uma.
    """
    if precos_r3 is None:
        precos_r3 = {"PA1": 80, "PA2": 50, "PA3": 32}
    if precos_r4 is None:
        precos_r4 = {"PA1": 80, "PA2": 50, "PA3": 25}

    leads = _carregar_leads()

    def lt(modal, o, d):
        if o == d:
            return 0
        return leads.get(modal, {}).get(o, {}).get(d)

    def km(modal, o, d):
        if o == d: return 0.0
        try:
            v = cfg.distancias[modal].at[o, d]
            return float(v) if v and v > 0 else 0.0
        except (KeyError, ValueError):
            return 0.0

    fab = estado_r3.fab_cidade
    cds_info = estado_r3.cds_info
    cds = list(cds_info.keys())

    # Indexação: dia absoluto t ∈ {1..10}
    # R3: t=1..5  /  R4: t=6..10
    # Para cada OP, dia_entrega absoluto = dia_entrega_relativo + 5 × (rodada - 3)
    # ops_r3: dia_entrega relativo 1..5 → absoluto 1..5
    # ops_r4: dia_entrega relativo 1..5 → absoluto 6..10

    # Normaliza OPs com flag de rodada e dia absoluto
    ops_all = []
    for op in ops_r3:
        ops_all.append({**op, "rodada": 3, "dia_entrega_abs": op["dia_entrega"]})
    for op in ops_r4_forecast:
        ops_all.append({**op, "rodada": 4, "dia_entrega_abs": op["dia_entrega"] + 5})

    T = list(range(1, 11))  # 10 dias

    # Para cada OP, todas rotas viáveis (t_prod ABS, cd, m1, m2)
    op_rotas: Dict[int, List[Dict]] = {}
    for i, op in enumerate(ops_all):
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
                    t_prod = op["dia_entrega_abs"] - lt1 - lt2
                    t_envio_cd = op["dia_entrega_abs"] - lt2
                    if t_prod not in T:
                        continue
                    # MODO CONSERVADOR: CD→Varejo deve sair na MESMA rodada do dia_entrega.
                    # Evita despachar PA de R3 chegando R4 (forecast pode errar dia_entrega).
                    if conservador:
                        rod_op = op["rodada"]
                        ts_da_rodada = list(range((rod_op - 3) * 5 + 1, (rod_op - 3) * 5 + 6))
                        if t_envio_cd not in ts_da_rodada:
                            continue
                    rotas_op.append({
                        "cd": cd, "cd_cid": cd_cid, "m1": m1, "lt1": lt1,
                        "m2": m2, "lt2": lt2, "t_prod": t_prod,
                        "t_envio_cd": t_envio_cd,
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

    # MP em-trânsito (R2→R3) — converte dia_rel pra absoluto
    em_transito_abs = {(d, mp): 0.0 for d in T for mp in MPS}
    for x in estado_r3.mp_em_transito:
        d_abs = int(x["dia_rel"])  # R3 dia 1 = absoluto 1
        em_transito_abs[(d_abs, x["mp"])] += float(x["qtd"])

    # ============ MODELO ============
    m = mip.Model(name=f"FLAMENGO_HORIZONTE_R3_R4")
    m.verbose = 1 if verbose else 0

    # --- Variáveis ---
    x_op = [m.add_var(name=f"x_{i}", var_type=mip.BINARY) for i in range(len(ops_all))]

    prod = {(t, pa): m.add_var(name=f"prod_{t}_{pa}", var_type=mip.INTEGER, lb=0)
            for t in T for pa in PAS}

    n_buy = {}; qty_buy = {}
    for mp_ in MPS:
        for fi in range(len(forn_info[mp_])):
            for t in T:
                n_buy[(t, mp_, fi)] = m.add_var(name=f"nbuy_{t}_{mp_}_{fi}", var_type=mip.INTEGER, lb=0)
                qty_buy[(t, mp_, fi)] = m.add_var(name=f"qbuy_{t}_{mp_}_{fi}", lb=0)

    n_f1cd = {}; qty_f1cd = {}
    for t in T:
        for cd in cds:
            for pa in PAS:
                for mod in MODAIS:
                    lt_v = lt(mod, fab, cds_info[cd])
                    if lt_v is None: continue
                    n_f1cd[(t, cd, pa, mod)] = m.add_var(name=f"nf1cd_{t}_{cd}_{pa}_{mod}",
                                                          var_type=mip.INTEGER, lb=0)
                    qty_f1cd[(t, cd, pa, mod)] = m.add_var(name=f"qf1cd_{t}_{cd}_{pa}_{mod}", lb=0)

    n_cdv = {}; qty_cdv = {}
    for i, op in enumerate(ops_all):
        cidade = op["cidade"]; pa = op["pa"]
        for rota in op_rotas[i]:
            key = (rota["t_envio_cd"], rota["cd"], cidade, pa, rota["m2"])
            if key not in n_cdv:
                n_cdv[key] = m.add_var(name=f"ncdv_{key[0]}_{key[1]}_{key[2]}_{key[3]}_{key[4]}",
                                        var_type=mip.INTEGER, lb=0)
                qty_cdv[key] = m.add_var(name=f"qcdv_{key[0]}_{key[1]}_{key[2]}_{key[3]}_{key[4]}", lb=0)

    stk_mp = {(t, mp): m.add_var(name=f"stk_mp_{t}_{mp}", lb=0) for t in [0] + T for mp in MPS}
    stk_pa = {(t, cd, pa): m.add_var(name=f"stk_pa_{t}_{cd}_{pa}", lb=0)
              for t in [0] + T for cd in cds for pa in PAS}

    # Estoques iniciais
    for mp_ in MPS:
        m += stk_mp[(0, mp_)] == estado_r3.estoque_mp_ton.get(mp_, 0)
    for cd in cds:
        for pa in PAS:
            m += stk_pa[(0, cd, pa)] == estado_r3.estoque_pa_cd.get(cd, {}).get(pa, 0)

    # --- Restrições ---

    # 1. Cap fábrica por dia
    for t in T:
        m += mip.xsum(prod[(t, pa)] / VEL_UN_MIN[pa] for pa in PAS) <= estado_r3.cap_min_dia

    # 2. Cap modal
    for key in qty_f1cd:
        t, cd, pa, mod = key
        m += qty_f1cd[key] <= n_f1cd[key] * _cap_un(mod, pa)
    for key in qty_cdv:
        t, cd, c, pa, mod = key
        m += qty_cdv[key] <= n_cdv[key] * _cap_un(mod, pa)
    for key in qty_buy:
        m += qty_buy[key] <= n_buy[key] * CAP_MODAL_TON["Caminhão"]

    # 3. PA sai F1 mesmo dia
    for t in T:
        for pa in PAS:
            m += prod[(t, pa)] == mip.xsum(
                qty_f1cd[(t, cd, pa, mod)] for cd in cds for mod in MODAIS
                if (t, cd, pa, mod) in qty_f1cd
            )

    # 4. Balance MP F1
    for t in T:
        for mp_ in MPS:
            chegadas_compras = []
            for fi in range(len(forn_info[mp_])):
                ltf = forn_info[mp_][fi][2]
                t_part = t - ltf
                if t_part in T:
                    chegadas_compras.append(qty_buy[(t_part, mp_, fi)])
            consumo = mip.xsum(prod[(t, pa)] * BOM[pa][mp_] / 1_000_000 for pa in PAS)
            m += stk_mp[(t, mp_)] == (
                stk_mp[(t-1, mp_)] + em_transito_abs[(t, mp_)]
                + (mip.xsum(chegadas_compras) if chegadas_compras else 0)
                - consumo
            )
            m += stk_mp[(t, mp_)] <= estado_r3.cap_mp_ton[mp_]

    # 5. Balance PA CDs
    for t in T:
        for cd in cds:
            for pa in PAS:
                chegadas = []
                for mod in MODAIS:
                    lt_v = lt(mod, fab, cds_info[cd])
                    if lt_v is None: continue
                    t_part = t - lt_v
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

    # 6. Entrega no dia EXATO (com keys únicas)
    for i, op in enumerate(ops_all):
        rotas = op_rotas[i]
        if not rotas:
            m += x_op[i] == 0
            continue
        keys = {(r["t_envio_cd"], r["cd"], op["cidade"], op["pa"], r["m2"]) for r in rotas}
        m += mip.xsum(qty_cdv[k] for k in keys) == op["qtd"] * x_op[i]

    # 7. NS ≥ ns_min POR rodada
    total_q_r3 = sum(op["qtd"] for op in ops_all if op["rodada"] == 3)
    total_q_r4 = sum(op["qtd"] for op in ops_all if op["rodada"] == 4)
    if total_q_r3 > 0:
        m += mip.xsum(x_op[i] * ops_all[i]["qtd"] for i in range(len(ops_all))
                      if ops_all[i]["rodada"] == 3) >= ns_min * total_q_r3
    if total_q_r4 > 0:
        m += mip.xsum(x_op[i] * ops_all[i]["qtd"] for i in range(len(ops_all))
                      if ops_all[i]["rodada"] == 4) >= ns_min * total_q_r4

    # CONSERVADOR: PA → Varejo via CD deve sair na rodada do OP (já forçado nas rotas).
    # F1 → CD pode acontecer em qualquer rodada (PA fica estocado no CD).
    # Isso é o que o usuário pediu: "produzir e levar PA pra CD em R3 pra estar pronto pra R4"

    # 8. Cap 220 transportes POR rodada (R3: t=1..5, R4: t=6..10)
    for rodada, ts in [(3, [1, 2, 3, 4, 5]), (4, [6, 7, 8, 9, 10])]:
        trips_rod = (
            mip.xsum(n_buy[(t, mp_, fi)] for t in ts for mp_ in MPS for fi in range(len(forn_info[mp_])))
            + mip.xsum(n_f1cd[key] for key in n_f1cd if key[0] in ts)
            + mip.xsum(n_cdv[key] for key in n_cdv if key[0] in ts)
        )
        m += trips_rod <= MAX_TRANSPORTES

    # --- OBJETIVO: max receita_total − custo_total ---
    receita_expr = mip.xsum(
        x_op[i] * ops_all[i]["qtd"] * (precos_r3[ops_all[i]["pa"]] if ops_all[i]["rodada"] == 3
                                        else precos_r4[ops_all[i]["pa"]])
        for i in range(len(ops_all))
    )

    custo_compra_mp = mip.xsum(
        qty_buy[(t, mp_, fi)] * forn_info[mp_][fi][1]
        for t in T for mp_ in MPS for fi in range(len(forn_info[mp_]))
    )

    # PROXY LINEAR: cada viagem custa frete-viagem cheio (frete_viagem×km×n).
    # Calibrado vs DRE real R3 — sem CT-e/doc nem meia-viagem fixa.
    def frete_term(qty_v, n_v, modal, k, item):
        return n_v * FRETE_VIAGEM[modal] * k

    custo_frete = (
        mip.xsum(frete_term(qty_buy[(t, mp_, fi)], n_buy[(t, mp_, fi)], "Caminhão",
                            km("Caminhão", forn_info[mp_][fi][0], fab), mp_)
                 for t in T for mp_ in MPS for fi in range(len(forn_info[mp_])))
        + mip.xsum(frete_term(qty_f1cd[key], n_f1cd[key], key[3],
                              km(key[3], fab, cds_info[key[1]]), key[2])
                   for key in qty_f1cd)
        + mip.xsum(frete_term(qty_cdv[key], n_cdv[key], key[4],
                              km(key[4], cds_info[key[1]], key[2]), key[3])
                   for key in qty_cdv)
    )

    # Carregamento ao FIM de cada rodada (fim Day 5 e Day 10)
    maior_mp = {"MP1": 56000, "MP2": 22000, "MP3": 41000}
    custo_carreg_r3_mp = mip.xsum(stk_mp[(5, mp_)] * maior_mp[mp_] * 0.01 for mp_ in MPS)
    custo_carreg_r4_mp = mip.xsum(stk_mp[(10, mp_)] * maior_mp[mp_] * 0.01 for mp_ in MPS)
    custo_carreg_r3_pa = mip.xsum(stk_pa[(5, cd, pa)] * precos_r3[pa] * 0.01
                                  for cd in cds for pa in PAS)
    custo_carreg_r4_pa = mip.xsum(stk_pa[(10, cd, pa)] * precos_r4[pa] * 0.01
                                  for cd in cds for pa in PAS)

    custo_total = (custo_compra_mp + custo_frete + custo_carreg_r3_mp
                   + custo_carreg_r4_mp + custo_carreg_r3_pa + custo_carreg_r4_pa)

    m.objective = mip.minimize(custo_total - receita_expr)

    # ============ RESOLVER ============
    print(f"[MILP-H] {m.num_cols} vars, {m.num_rows} restrições")
    print(f"[MILP-H] Resolvendo (limite {time_limit_s}s)...")
    t0 = time.time()
    status = m.optimize(max_seconds=time_limit_s)
    runtime = time.time() - t0
    print(f"[MILP-H] Status: {status} ({runtime:.1f}s)")

    if status not in (mip.OptimizationStatus.OPTIMAL, mip.OptimizationStatus.FEASIBLE):
        return ResultadoSolverHorizonte(
            status=str(status), objetivo=float("inf"), runtime_s=runtime,
            ns_r3_pct=0, ns_r4_pct=0,
            receita_r3=0, receita_r4=0,
            custo_var_r3=0, custo_var_r4=0,
            lucro_r3=0, lucro_r4=0, lucro_horizonte=0,
            n_transp_r3=0, n_transp_r4=0,
            ops_atend_r3=[], ops_atend_r4=[],
            ops_desc_r3=[], ops_desc_r4=[],
            df_sol_transp_r3=pd.DataFrame(),
            df_sol_transp_r4=pd.DataFrame(),
            df_op_fabricas_r3=pd.DataFrame(),
            df_op_fabricas_r4=pd.DataFrame(),
            estoque_mp_fim_r3={}, estoque_mp_fim_r4={},
            estoque_pa_cd_fim_r3={}, estoque_pa_cd_fim_r4={},
        )

    # ============ EXTRAÇÃO ============
    def get(var):
        return var.x if var.x is not None else 0.0

    # OPs atendidas/descartadas por rodada
    ops_atend_r3 = []; ops_atend_r4 = []
    ops_desc_r3 = []; ops_desc_r4 = []
    for i, op in enumerate(ops_all):
        if get(x_op[i]) > 0.5:
            (ops_atend_r3 if op["rodada"] == 3 else ops_atend_r4).append(op)
        else:
            (ops_desc_r3 if op["rodada"] == 3 else ops_desc_r4).append(op)

    # Produção dia a dia
    prod_dia = {t: {pa: int(round(get(prod[(t, pa)]))) for pa in PAS} for t in T}

    # Constroi SOL_TRANSP por rodada
    def build_sol_transp(rodada: int, ts: List[int]) -> pd.DataFrame:
        linhas = []
        # Forn → F1
        for (t, mp_, fi), var_n in n_buy.items():
            if t not in ts: continue
            nv = int(round(get(var_n)))
            qty = get(qty_buy[(t, mp_, fi)])
            if nv <= 0 or qty <= 0.01: continue
            forn, _, _ = forn_info[mp_][fi]
            qpv = qty / nv
            for _ in range(nv):
                linhas.append({
                    "Rodada": f"Rodada_{rodada}", "Origem": "Fornecedor", "Cidade": forn,
                    "Dia da Coleta": f"Dia {(t-1) % 5 + 1}",  # relativo da rodada
                    "Modal": "Caminhão", "Tipo do Produto": mp_, "Qtde": round(qpv, 2),
                    "Destino": "Fábrica", "Cidade_Destino": fab,
                })
        # F1 → CD
        for key, var_n in n_f1cd.items():
            t, cd, pa, mod = key
            if t not in ts: continue
            nv = int(round(get(var_n)))
            qty = get(qty_f1cd[key])
            if nv <= 0 or qty <= 0.5: continue
            cap_un = _cap_un(mod, pa)
            rest = int(round(qty))
            for _ in range(nv):
                q = min(rest, cap_un)
                if q <= 0: continue
                linhas.append({
                    "Rodada": f"Rodada_{rodada}", "Origem": "Fábrica", "Cidade": fab,
                    "Dia da Coleta": f"Dia {(t-1) % 5 + 1}",
                    "Modal": mod, "Tipo do Produto": pa, "Qtde": q,
                    "Destino": "CD", "Cidade_Destino": cds_info[cd],
                })
                rest -= q
        # CD → V
        for key, var_n in n_cdv.items():
            t, cd, c, pa, mod = key
            if t not in ts: continue
            nv = int(round(get(var_n)))
            qty = get(qty_cdv[key])
            if nv <= 0 or qty <= 0.5: continue
            cap_un = _cap_un(mod, pa)
            rest = int(round(qty))
            for _ in range(nv):
                q = min(rest, cap_un)
                if q <= 0: continue
                linhas.append({
                    "Rodada": f"Rodada_{rodada}", "Origem": "CD", "Cidade": cds_info[cd],
                    "Dia da Coleta": f"Dia {(t-1) % 5 + 1}",
                    "Modal": mod, "Tipo do Produto": pa, "Qtde": q,
                    "Destino": "Varejista", "Cidade_Destino": c,
                })
                rest -= q
        return pd.DataFrame(linhas, columns=[
            "Rodada", "Origem", "Cidade", "Dia da Coleta", "Modal",
            "Tipo do Produto", "Qtde", "Destino", "Cidade_Destino",
        ])

    df_st_r3 = build_sol_transp(3, [1, 2, 3, 4, 5])
    df_st_r4 = build_sol_transp(4, [6, 7, 8, 9, 10])
    df_op_r3 = pd.DataFrame([
        {"Dia": f"Dia {t}", **{pa: prod_dia[t][pa] for pa in PAS}} for t in [1,2,3,4,5]
    ])
    df_op_r4 = pd.DataFrame([
        {"Dia": f"Dia {t-5}", **{pa: prod_dia[t][pa] for pa in PAS}} for t in [6,7,8,9,10]
    ])

    # Receitas + custos por rodada
    receita_r3 = sum(op["qtd"] * precos_r3[op["pa"]] for op in ops_atend_r3)
    receita_r4 = sum(op["qtd"] * precos_r4[op["pa"]] for op in ops_atend_r4)

    def custo_rodada(ts):
        c_mp = sum(get(qty_buy[(t, mp_, fi)]) * forn_info[mp_][fi][1]
                   for t in ts for mp_ in MPS for fi in range(len(forn_info[mp_])))
        # Frete por viagem (usa fórmula linearizada — comparável ao objetivo)
        c_fr = 0
        for t in ts:
            for mp_ in MPS:
                for fi in range(len(forn_info[mp_])):
                    q = get(qty_buy[(t, mp_, fi)])
                    n = get(n_buy[(t, mp_, fi)])
                    if n > 0:
                        kv = km("Caminhão", forn_info[mp_][fi][0], fab)
                        # regra oficial calibrada: ≥80% viagem cheia / <80% peso puro, sem doc
                        c_fr += (FRETE_VIAGEM["Caminhão"] * kv * n if (q/n)/CAP_MODAL_TON["Caminhão"] >= 0.8
                                 else FRETE_PESO["Caminhão"] * kv * q)
        for key in qty_f1cd:
            if key[0] not in ts: continue
            q = get(qty_f1cd[key]); n = get(n_f1cd[key])
            if n > 0:
                kv = km(key[3], fab, cds_info[key[1]])
                peso = q * PESO_UN_TON[key[2]]
                c_fr += (FRETE_VIAGEM[key[3]] * kv * n if (peso/n)/CAP_MODAL_TON[key[3]] >= 0.8
                         else FRETE_PESO[key[3]] * kv * peso)
        for key in qty_cdv:
            if key[0] not in ts: continue
            q = get(qty_cdv[key]); n = get(n_cdv[key])
            if n > 0:
                kv = km(key[4], cds_info[key[1]], key[2])
                peso = q * PESO_UN_TON[key[3]]
                c_fr += (FRETE_VIAGEM[key[4]] * kv * n if (peso/n)/CAP_MODAL_TON[key[4]] >= 0.8
                         else FRETE_PESO[key[4]] * kv * peso)
        return c_mp, c_fr

    cmp_r3, cfr_r3 = custo_rodada([1, 2, 3, 4, 5])
    cmp_r4, cfr_r4 = custo_rodada([6, 7, 8, 9, 10])
    car_r3 = sum(get(stk_mp[(5, mp_)]) * maior_mp[mp_] * 0.01 for mp_ in MPS) + \
             sum(get(stk_pa[(5, cd, pa)]) * precos_r3[pa] * 0.01 for cd in cds for pa in PAS)
    car_r4 = sum(get(stk_mp[(10, mp_)]) * maior_mp[mp_] * 0.01 for mp_ in MPS) + \
             sum(get(stk_pa[(10, cd, pa)]) * precos_r4[pa] * 0.01 for cd in cds for pa in PAS)

    custo_r3 = cmp_r3 + cfr_r3 + car_r3
    custo_r4 = cmp_r4 + cfr_r4 + car_r4
    lucro_r3 = receita_r3 - custo_r3
    lucro_r4 = receita_r4 - custo_r4

    qty_atend_r3 = sum(op["qtd"] for op in ops_atend_r3)
    qty_atend_r4 = sum(op["qtd"] for op in ops_atend_r4)
    ns_r3 = qty_atend_r3 / max(1, total_q_r3) * 100
    ns_r4 = qty_atend_r4 / max(1, total_q_r4) * 100

    return ResultadoSolverHorizonte(
        status=str(status),
        objetivo=float(m.objective_value),
        runtime_s=runtime,
        ns_r3_pct=ns_r3, ns_r4_pct=ns_r4,
        receita_r3=receita_r3, receita_r4=receita_r4,
        custo_var_r3=custo_r3, custo_var_r4=custo_r4,
        lucro_r3=lucro_r3, lucro_r4=lucro_r4,
        lucro_horizonte=lucro_r3 + lucro_r4,
        n_transp_r3=len(df_st_r3), n_transp_r4=len(df_st_r4),
        ops_atend_r3=ops_atend_r3, ops_atend_r4=ops_atend_r4,
        ops_desc_r3=ops_desc_r3, ops_desc_r4=ops_desc_r4,
        df_sol_transp_r3=df_st_r3, df_sol_transp_r4=df_st_r4,
        df_op_fabricas_r3=df_op_r3, df_op_fabricas_r4=df_op_r4,
        estoque_mp_fim_r3={mp_: get(stk_mp[(5, mp_)]) for mp_ in MPS},
        estoque_mp_fim_r4={mp_: get(stk_mp[(10, mp_)]) for mp_ in MPS},
        estoque_pa_cd_fim_r3={cd: {pa: int(round(get(stk_pa[(5, cd, pa)]))) for pa in PAS} for cd in cds},
        estoque_pa_cd_fim_r4={cd: {pa: int(round(get(stk_pa[(10, cd, pa)]))) for pa in PAS} for cd in cds},
    )
