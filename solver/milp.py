"""MILP do planejamento da rodada (Flamengo).

Função objetivo:
    min  custo_mp_comprada + frete (peso, simplificado) + carregamento_estoque
Sujeito a:
    NS ≥ 80%  (frascos entregues no dia exato / frascos pedidos)
    + restrições físicas de cap, fluxo, BoM, lead times.

API:
    resolver_rodada(estado, ops, forecast_proxima, cfg, ...) -> Resultado
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


# Modais e parâmetros (do jogo)
MODAIS = ("Caminhão", "Navio", "Avião")
PAS = ("PA1", "PA2", "PA3")
MPS = ("MP1", "MP2", "MP3")
DIAS = (1, 2, 3, 4, 5)
PESO_UN_TON = {"PA1": 0.0003, "PA2": 0.00025, "PA3": 0.00015}  # peso unitário em ton
DENS_MP = {"MP1": 0.5, "MP2": 0.7, "MP3": 0.9}
DENS_PA = {"PA1": 1.0, "PA2": 0.5, "PA3": 0.8}
BOM = {  # g/un
    "PA1": {"MP1": 60, "MP2": 90, "MP3": 150},
    "PA2": {"MP1": 75, "MP2": 125, "MP3": 50},
    "PA3": {"MP1": 75, "MP2": 30, "MP3": 45},
}
VEL_UN_MIN = {"PA1": 15, "PA2": 30, "PA3": 60}
CAP_MODAL_TON = {"Caminhão": 24, "Navio": 100, "Avião": 1}
FRETE_VIAGEM = {"Caminhão": 8.0, "Navio": 5.0, "Avião": 12.0}
FRETE_PESO = {"Caminhão": 0.5, "Navio": 0.075, "Avião": 18.0}
DOC_MODAL = {"Caminhão": 100, "Navio": 50, "Avião": 200}
MAX_TRANSPORTES = 220


@dataclass
class ResultadoSolver:
    status: str
    objetivo: float
    ns_pct: float
    custo_compra_mp: float
    custo_frete: float
    custo_carregamento: float
    receita: float
    resultado_rodada: float
    n_transportes: int

    df_sol_transp: pd.DataFrame
    df_op_fabricas: pd.DataFrame

    # Detalhes
    ops_atendidas: List[Dict]
    ops_descartadas: List[Dict]
    estoque_mp_final: Dict[str, float]
    estoque_pa_cd_final: Dict[str, Dict[str, int]]
    minutos_usados_por_dia: Dict[int, float]

    runtime_s: float
    gap_pct: float | None = None


def _carregar_leads() -> Dict[str, Dict[str, Dict[str, int]]]:
    return json.loads((BASE / "data" / "lead_times.json").read_text(encoding="utf-8"))


def _cap_un(modal: str, item: str) -> int:
    """Capacidade do modal em unidades por viagem para um PA, ou ton para MP."""
    if item in PAS:
        return math.floor(CAP_MODAL_TON[modal] / PESO_UN_TON[item])
    return CAP_MODAL_TON[modal]  # MP em ton


def resolver_rodada(
    estado: EstadoRodada,
    ops: List[Dict],
    cfg: Config,
    *,
    pa_proxima_rodada: str | None = None,
    buffer_pa_proxima_min: int = 0,
    preco_pa_rodada: Dict[str, float] | None = None,
    ns_min: float = 0.80,
    objetivo: str = "max_lucro",  # "max_lucro" ou "min_custo"
    time_limit_s: float = 120,
    verbose: bool = False,
) -> ResultadoSolver:
    """Resolve o problema da rodada como MILP.

    Args:
        estado: do solver.state.consolidar_estado()
        ops: list of {cidade, pa, qtd, dia_entrega}
        cfg: parâmetros do jogo
        pa_proxima_rodada: e.g. "PA2" para R4
        buffer_pa_proxima_min: estoca pelo menos isso de pa_proxima_rodada
        preco_pa_rodada: e.g. {"PA1": 80, "PA2": 50, "PA3": 32}
        ns_min: 0.80 = 80%
        time_limit_s: limite CBC
    """
    if preco_pa_rodada is None:
        preco_pa_rodada = {"PA1": 80, "PA2": 50, "PA3": 32}

    leads = _carregar_leads()

    def lt(modal: str, o: str, d: str) -> int | None:
        if o == d:
            return 0
        return leads.get(modal, {}).get(o, {}).get(d)

    def km(modal: str, o: str, d: str) -> float:
        if o == d:
            return 0.0
        try:
            v = cfg.distancias[modal].at[o, d]
            return float(v) if v and v > 0 else 0.0
        except (KeyError, ValueError):
            return 0.0

    fab = estado.fab_cidade
    cds_info = estado.cds_info
    cds = list(cds_info.keys())
    cidades_op = sorted({o["cidade"] for o in ops})

    # Pré-processamento: para cada OP, todas as rotas viáveis (t_prod, cd, m1, m2)
    # com t_prod + lt(m1) + lt(m2) == dia_entrega
    op_rotas: Dict[int, List[Dict]] = {}
    for i, op in enumerate(ops):
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

    # Fornecedores: para cada MP, lista dos fornecedores com seu lead time cam
    forn_info: Dict[str, List[Tuple[str, float, int]]] = {}  # mp -> [(cidade, custo/ton, lt)]
    for mp in MPS:
        lst = []
        for f, c in cfg.fornecedores[mp]:
            l = lt("Caminhão", f, fab)
            if l is not None:
                lst.append((f, float(c), l))
        forn_info[mp] = lst

    # ============ MODELO ============
    m = mip.Model(name=f"FLAMENGO_R{estado.rodada}")
    m.verbose = 1 if verbose else 0

    # --- Variáveis ---
    # x_op[i] ∈ {0,1} atende OP i no dia exato (todo ou nada)
    x_op = [m.add_var(name=f"x_{i}", var_type=mip.BINARY) for i in range(len(ops))]

    # prod[t, pa] ∈ ℤ+
    prod = {(t, pa): m.add_var(name=f"prod_{t}_{pa}", var_type=mip.INTEGER, lb=0)
            for t in DIAS for pa in PAS}

    # Compra MP: n_buy[t, mp, forn_idx] ∈ ℤ+, qty_buy ∈ ℝ+
    # forn_idx é o índice na lista forn_info[mp]
    n_buy = {}
    qty_buy = {}
    for mp in MPS:
        for fi, (forn, custo, ltf) in enumerate(forn_info[mp]):
            for t in DIAS:
                n_buy[(t, mp, fi)] = m.add_var(name=f"nbuy_{t}_{mp}_{fi}", var_type=mip.INTEGER, lb=0)
                qty_buy[(t, mp, fi)] = m.add_var(name=f"qbuy_{t}_{mp}_{fi}", lb=0)

    # F1 → CD: n_f1cd[t, cd, pa, modal] ∈ ℤ+
    n_f1cd = {}
    qty_f1cd = {}
    for t in DIAS:
        for cd in cds:
            for pa in PAS:
                for mod in MODAIS:
                    lt_v = lt(mod, fab, cds_info[cd])
                    if lt_v is None:
                        continue
                    n_f1cd[(t, cd, pa, mod)] = m.add_var(name=f"nf1cd_{t}_{cd}_{pa}_{mod}",
                                                          var_type=mip.INTEGER, lb=0)
                    qty_f1cd[(t, cd, pa, mod)] = m.add_var(name=f"qf1cd_{t}_{cd}_{pa}_{mod}", lb=0)

    # CD → Varejo: n_cdv[t, cd, c, pa, modal]
    # MAS apenas para combinações que o pe-processamento mostra serem rota de alguma OP
    n_cdv = {}
    qty_cdv = {}
    for i, op in enumerate(ops):
        cidade = op["cidade"]; pa = op["pa"]
        for rota in op_rotas[i]:
            cd = rota["cd"]; m2 = rota["m2"]; t_envio = rota["t_envio_cd"]
            key = (t_envio, cd, cidade, pa, m2)
            if key not in n_cdv:
                n_cdv[key] = m.add_var(name=f"ncdv_{t_envio}_{cd}_{cidade}_{pa}_{m2}",
                                        var_type=mip.INTEGER, lb=0)
                qty_cdv[key] = m.add_var(name=f"qcdv_{t_envio}_{cd}_{cidade}_{pa}_{m2}", lb=0)

    # Estoques
    stk_mp = {(t, mp): m.add_var(name=f"stk_mp_{t}_{mp}", lb=0) for t in [0] + list(DIAS) for mp in MPS}
    stk_pa = {(t, cd, pa): m.add_var(name=f"stk_pa_{t}_{cd}_{pa}", lb=0)
              for t in [0] + list(DIAS) for cd in cds for pa in PAS}

    # Fix estoques iniciais
    for mp in MPS:
        m += stk_mp[(0, mp)] == estado.estoque_mp_ton.get(mp, 0)
    for cd in cds:
        for pa in PAS:
            m += stk_pa[(0, cd, pa)] == estado.estoque_pa_cd.get(cd, {}).get(pa, 0)

    # --- Restrições ---

    # 1. Cap fábrica
    for t in DIAS:
        m += mip.xsum(prod[(t, pa)] / VEL_UN_MIN[pa] for pa in PAS) <= estado.cap_min_dia

    # 2. Cap modal F1→CD: qty ≤ n × cap_un
    for key, var_q in qty_f1cd.items():
        t, cd, pa, mod = key
        m += var_q <= n_f1cd[key] * _cap_un(mod, pa)

    # 3. Cap modal CD→V
    for key, var_q in qty_cdv.items():
        t, cd, c, pa, mod = key
        m += var_q <= n_cdv[key] * _cap_un(mod, pa)

    # 4. Cap modal Forn→F1 (em ton)
    for key, var_q in qty_buy.items():
        m += var_q <= n_buy[key] * CAP_MODAL_TON["Caminhão"]

    # 5. PA sai da F1 no MESMO dia em que é produzido
    for t in DIAS:
        for pa in PAS:
            m += prod[(t, pa)] == mip.xsum(
                qty_f1cd[(t, cd, pa, mod)]
                for cd in cds for mod in MODAIS
                if (t, cd, pa, mod) in qty_f1cd
            )

    # 6. Balance estoque MP F1
    # arrivals MP em-trânsito (de rodadas anteriores)
    em_transito = {(d, mp): 0.0 for d in DIAS for mp in MPS}
    for x in estado.mp_em_transito:
        em_transito[(int(x["dia_rel"]), x["mp"])] += float(x["qtd"])

    for t in DIAS:
        for mp in MPS:
            # Compras de t' que chegam em t: t' + lt_forn[forn] == t
            chegadas_compras = []
            for fi, (forn, custo, ltf) in enumerate(forn_info[mp]):
                t_part = t - ltf
                if t_part in DIAS:
                    chegadas_compras.append(qty_buy[(t_part, mp, fi)])
            consumo = mip.xsum(prod[(t, pa)] * BOM[pa][mp] / 1_000_000 for pa in PAS)
            m += stk_mp[(t, mp)] == (
                stk_mp[(t-1, mp)] + em_transito[(t, mp)]
                + (mip.xsum(chegadas_compras) if chegadas_compras else 0)
                - consumo
            )

    # 7. Cap MP F1
    for t in DIAS:
        for mp in MPS:
            m += stk_mp[(t, mp)] <= estado.cap_mp_ton[mp]

    # 8. Balance PA nos CDs
    for t in DIAS:
        for cd in cds:
            for pa in PAS:
                # Chegadas: qty_f1cd com t_part + lt == t
                chegadas = []
                for mod in MODAIS:
                    lt_v = lt(mod, fab, cds_info[cd])
                    if lt_v is None:
                        continue
                    t_part = t - lt_v
                    if t_part in DIAS:
                        chegadas.append(qty_f1cd[(t_part, cd, pa, mod)])
                # Saídas: qty_cdv[(t, cd, c, pa, mod)]
                saidas = [v for key, v in qty_cdv.items()
                          if key[0] == t and key[1] == cd and key[3] == pa]
                m += stk_pa[(t, cd, pa)] == (
                    stk_pa[(t-1, cd, pa)]
                    + (mip.xsum(chegadas) if chegadas else 0)
                    - (mip.xsum(saidas) if saidas else 0)
                )

    # 9. Cap PA nos CDs
    for t in DIAS:
        for cd in cds:
            for pa in PAS:
                m += stk_pa[(t, cd, pa)] <= estado.cap_pa_cd_un[cd][pa]

    # 10. Entrega no DIA EXATO: para cada OP, soma das qtys das rotas viáveis = qtd × x_op
    # IMPORTANTE: usar set para evitar contar 2x a mesma key (rotas com m1 diferente mas m2,t,cd iguais).
    for i, op in enumerate(ops):
        rotas = op_rotas[i]
        if not rotas:
            m += x_op[i] == 0
            continue
        keys_unicas = {(r["t_envio_cd"], r["cd"], op["cidade"], op["pa"], r["m2"])
                       for r in rotas}
        soma = mip.xsum(qty_cdv[k] for k in keys_unicas)
        m += soma == op["qtd"] * x_op[i]

    # 11. NS mínimo
    total_qty = sum(op["qtd"] for op in ops)
    m += mip.xsum(x_op[i] * ops[i]["qtd"] for i in range(len(ops))) >= ns_min * total_qty

    # 12. Buffer PA próxima rodada (estoque final no Dia 5)
    if pa_proxima_rodada and buffer_pa_proxima_min > 0:
        m += mip.xsum(stk_pa[(5, cd, pa_proxima_rodada)] for cd in cds) >= buffer_pa_proxima_min

    # 13. Total transportes ≤ 220
    total_trips = (
        mip.xsum(n_buy[k] for k in n_buy)
        + mip.xsum(n_f1cd[k] for k in n_f1cd)
        + mip.xsum(n_cdv[k] for k in n_cdv)
    )
    m += total_trips <= MAX_TRANSPORTES

    # --- Função objetivo ---
    # Compra MP
    custo_compra_mp_expr = mip.xsum(
        qty_buy[(t, mp, fi)] * forn_info[mp][fi][1]
        for t in DIAS for mp in MPS for fi in range(len(forn_info[mp]))
    )
    # Frete — PROXY LINEAR do objetivo: cada viagem despachada custa frete-viagem
    # cheio (frete_viagem × km × n_viagens). É linear em n, incentiva encher
    # veículos e bate com o custo realizado quando a carga é cheia (caso dominante).
    # O custo EXATO (≥80% → viagem; <80% → frete-peso puro) é recomputado pós-solve
    # em frete_realizado. Sem CT-e/doc nem meia-viagem (calibrado vs DRE real R3).
    custo_frete_buy = mip.xsum(
        n_buy[(t, mp, fi)] * FRETE_VIAGEM["Caminhão"] * km("Caminhão", forn_info[mp][fi][0], fab)
        for t in DIAS for mp in MPS for fi in range(len(forn_info[mp]))
    )

    def frete_pa(key, var_q, var_n, modal, o, d, pa):
        k = km(modal, o, d)
        return var_n * FRETE_VIAGEM[modal] * k

    custo_frete_f1cd = mip.xsum(
        frete_pa(key, qty_f1cd[key], n_f1cd[key], key[3], fab, cds_info[key[1]], key[2])
        for key in qty_f1cd
    )
    custo_frete_cdv = mip.xsum(
        frete_pa(key, qty_cdv[key], n_cdv[key], key[4], cds_info[key[1]], key[2], key[3])
        for key in qty_cdv
    )

    # Carregamento final (1%)
    maior_mp = {"MP1": 56000, "MP2": 22000, "MP3": 41000}
    custo_carreg_mp = mip.xsum(stk_mp[(5, mp)] * maior_mp[mp] * 0.01 for mp in MPS)
    custo_carreg_pa = mip.xsum(
        stk_pa[(5, cd, pa)] * preco_pa_rodada[pa] * 0.01
        for cd in cds for pa in PAS
    )

    # Custo TOTAL — só variáveis (fixos não dependem das decisões)
    custo_total_expr = (custo_compra_mp_expr + custo_frete_buy + custo_frete_f1cd
                        + custo_frete_cdv + custo_carreg_mp + custo_carreg_pa)

    # Receita = Σ x_op × qtd × preço_pa
    receita_expr = mip.xsum(
        x_op[i] * ops[i]["qtd"] * preco_pa_rodada[ops[i]["pa"]]
        for i in range(len(ops))
    )

    if objetivo == "max_lucro":
        # max (receita − custo) ↔ min (custo − receita)
        m.objective = mip.minimize(custo_total_expr - receita_expr)
    elif objetivo == "min_custo":
        m.objective = mip.minimize(custo_total_expr)
    else:
        raise ValueError(f"Objetivo desconhecido: {objetivo}")

    # --- Resolver ---
    print(f"[MILP] Modelo: {m.num_cols} variáveis, {m.num_rows} restrições")
    print(f"[MILP] Resolvendo (limite {time_limit_s}s)...")
    t0 = time.time()
    status = m.optimize(max_seconds=time_limit_s)
    runtime = time.time() - t0
    print(f"[MILP] Status: {status}  ({runtime:.1f}s)")

    if status not in (mip.OptimizationStatus.OPTIMAL, mip.OptimizationStatus.FEASIBLE):
        return ResultadoSolver(
            status=str(status), objetivo=float("inf"), ns_pct=0,
            custo_compra_mp=0, custo_frete=0, custo_carregamento=0,
            receita=0, resultado_rodada=0, n_transportes=0,
            df_sol_transp=pd.DataFrame(),
            df_op_fabricas=pd.DataFrame(),
            ops_atendidas=[], ops_descartadas=[],
            estoque_mp_final={}, estoque_pa_cd_final={},
            minutos_usados_por_dia={},
            runtime_s=runtime,
        )

    # ============ EXTRAIR SOLUÇÃO ============
    def get(var):
        return var.x if var.x is not None else 0.0

    # OPs
    ops_atend = []
    ops_desc = []
    for i, op in enumerate(ops):
        if get(x_op[i]) > 0.5:
            ops_atend.append(op)
        else:
            ops_desc.append({**op, "motivo": "Solver: melhor não atender (NS≥80% atingido)"})

    # Produção
    prod_dia = {t: {pa: int(round(get(prod[(t, pa)]))) for pa in PAS} for t in DIAS}

    # SOL_TRANSP: construir linhas
    linhas = []

    # Fornecedor → F1
    for (t, mp, fi), var_n in n_buy.items():
        nv = int(round(get(var_n)))
        if nv <= 0:
            continue
        qty = get(qty_buy[(t, mp, fi)])
        if qty <= 0.01:
            continue
        forn, _, ltf = forn_info[mp][fi]
        # Quebra em nv viagens (uma por linha, com qty/nv cada)
        q_per = qty / nv
        for _ in range(nv):
            linhas.append({
                "Rodada": f"Rodada_{estado.rodada}",
                "Origem": "Fornecedor", "Cidade": forn,
                "Dia da Coleta": f"Dia {t}",
                "Modal": "Caminhão", "Tipo do Produto": mp,
                "Qtde": round(q_per, 2),
                "Destino": "Fábrica", "Cidade_Destino": fab,
            })

    # F1 → CD
    for key, var_n in n_f1cd.items():
        t, cd, pa, mod = key
        nv = int(round(get(var_n)))
        if nv <= 0:
            continue
        qty = get(qty_f1cd[key])
        if qty <= 0.5:
            continue
        q_per = int(qty / nv) if nv > 0 else qty
        # Distribui: nv-1 viagens com cap cheia + 1 com resto
        cap_un = _cap_un(mod, pa)
        rest = int(round(qty))
        for _ in range(nv):
            q = min(rest, cap_un)
            if q <= 0: continue
            linhas.append({
                "Rodada": f"Rodada_{estado.rodada}",
                "Origem": "Fábrica", "Cidade": fab,
                "Dia da Coleta": f"Dia {t}",
                "Modal": mod, "Tipo do Produto": pa,
                "Qtde": q,
                "Destino": "CD", "Cidade_Destino": cds_info[cd],
            })
            rest -= q

    # CD → Varejo
    for key, var_n in n_cdv.items():
        t, cd, c, pa, mod = key
        nv = int(round(get(var_n)))
        if nv <= 0:
            continue
        qty = get(qty_cdv[key])
        if qty <= 0.5:
            continue
        cap_un = _cap_un(mod, pa)
        rest = int(round(qty))
        for _ in range(nv):
            q = min(rest, cap_un)
            if q <= 0: continue
            linhas.append({
                "Rodada": f"Rodada_{estado.rodada}",
                "Origem": "CD", "Cidade": cds_info[cd],
                "Dia da Coleta": f"Dia {t}",
                "Modal": mod, "Tipo do Produto": pa,
                "Qtde": q,
                "Destino": "Varejista", "Cidade_Destino": c,
            })
            rest -= q

    df_sol = pd.DataFrame(linhas, columns=[
        "Rodada", "Origem", "Cidade", "Dia da Coleta", "Modal",
        "Tipo do Produto", "Qtde", "Destino", "Cidade_Destino",
    ])
    df_op = pd.DataFrame([{
        "Dia": f"Dia {t}",
        **{pa: prod_dia[t][pa] for pa in PAS},
    } for t in DIAS])

    # Cálculos para o resultado — diretamente das variáveis (não do m.objective_value)
    receita = sum(op["qtd"] * preco_pa_rodada[op["pa"]] for op in ops_atend)
    custo_comp = sum(get(qty_buy[(t, mp, fi)]) * forn_info[mp][fi][1]
                     for t in DIAS for mp in MPS for fi in range(len(forn_info[mp])))

    # Frete = soma de cada variável de frete (compra MP + F1→CD + CD→V)
    def frete_realizado(modal, o, d, qty_v, n_v, item):
        # Regra oficial CALIBRADA vs DRE real R3 (erro <0,3%):
        #   ocup/viagem ≥80% → frete-viagem cheio; <80% → frete-peso puro. Sem doc.
        kv = km(modal, o, d)
        if kv is None or kv <= 0 or n_v <= 0:
            return 0.0
        peso = qty_v * PESO_UN_TON[item] if item in PAS else qty_v
        cap = CAP_MODAL_TON[modal]
        ocup = (peso / n_v) / cap if cap > 0 else 0
        if ocup >= 0.8:
            return FRETE_VIAGEM[modal] * kv * n_v
        return FRETE_PESO[modal] * kv * peso

    custo_frete = 0.0
    for (t, mp, fi) in qty_buy:
        forn = forn_info[mp][fi][0]
        custo_frete += frete_realizado("Caminhão", forn, fab, get(qty_buy[(t, mp, fi)]),
                                       get(n_buy[(t, mp, fi)]), mp)
    for key in qty_f1cd:
        t, cd, pa, mod = key
        custo_frete += frete_realizado(mod, fab, cds_info[cd], get(qty_f1cd[key]),
                                       get(n_f1cd[key]), pa)
    for key in qty_cdv:
        t, cd, c, pa, mod = key
        custo_frete += frete_realizado(mod, cds_info[cd], c, get(qty_cdv[key]),
                                       get(n_cdv[key]), pa)

    custo_carreg = (sum(get(stk_mp[(5, mp)]) * maior_mp[mp] * 0.01 for mp in MPS)
                    + sum(get(stk_pa[(5, cd, pa)]) * preco_pa_rodada[pa] * 0.01
                          for cd in cds for pa in PAS))
    ns_pct = sum(op["qtd"] for op in ops_atend) / max(1, total_qty) * 100

    n_transp = len(df_sol)

    estoque_mp_fim = {mp: get(stk_mp[(5, mp)]) for mp in MPS}
    estoque_pa_fim = {cd: {pa: int(round(get(stk_pa[(5, cd, pa)]))) for pa in PAS} for cd in cds}
    min_usados = {t: sum(get(prod[(t, pa)]) / VEL_UN_MIN[pa] for pa in PAS) for t in DIAS}

    custo_total_real = custo_comp + custo_frete + custo_carreg
    lucro_real = receita - custo_total_real

    return ResultadoSolver(
        status=str(status),
        objetivo=float(m.objective_value),
        ns_pct=ns_pct,
        custo_compra_mp=custo_comp,
        custo_frete=custo_frete,
        custo_carregamento=custo_carreg,
        receita=receita,
        resultado_rodada=lucro_real,
        n_transportes=n_transp,
        df_sol_transp=df_sol,
        df_op_fabricas=df_op,
        ops_atendidas=ops_atend,
        ops_descartadas=ops_desc,
        estoque_mp_final=estoque_mp_fim,
        estoque_pa_cd_final=estoque_pa_fim,
        minutos_usados_por_dia=min_usados,
        runtime_s=runtime,
        gap_pct=m.gap if hasattr(m, 'gap') else None,
    )
