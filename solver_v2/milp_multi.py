"""MILP multi-rodada com cenários — solver_v2.

Decide TUDO numa otimização só (compra MP → produção → transporte → entrega no
dia exato → buffer de MP), em horizonte de N rodadas. A rodada atual tem demanda
CONHECIDA; as futuras entram como CENÁRIOS (1/3 PA1/PA2/PA3, rodada cheia), com
o estoque carregado entre rodadas (buffer endógeno). NS entra como RECEITA
(penalidade α por frasco não atendido), com α alto, em vez de restrição dura.

Reusa as constantes e a regra de frete calibrada do solver v1 (solver/milp.py).
"""
from __future__ import annotations
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List

import mip

BASE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE))
from src.config import Config
from solver.state import EstadoRodada
from solver.milp import (
    MODAIS, PAS, MPS, BOM, VEL_UN_MIN, CAP_MODAL_TON,
    FRETE_VIAGEM, FRETE_PESO, PESO_UN_TON, MAX_TRANSPORTES,
    _cap_un, _carregar_leads,
)

DIAS = (1, 2, 3, 4, 5)


@dataclass
class BlocoRodada:
    """Variáveis e expressões de um bloco-rodada dentro do modelo."""
    label: str
    x_op: list
    prod: dict
    qty_buy: dict
    n_buy: dict
    qty_f1cd: dict
    n_f1cd: dict
    qty_cdv: dict
    n_cdv: dict
    stk_mp: dict          # (t,mp) -> var ; t ∈ 0..5
    stk_pa: dict          # (t,cd,pa) -> var
    ops: list
    receita_expr: Any
    custo_expr: Any
    unmet_expr: Any       # frascos não atendidos (p/ penalidade NS)
    lucro_expr: Any       # receita - custo  (sem penalidade NS)
    trips_expr: Any
    fab: str = ""
    cds_info: dict = field(default_factory=dict)
    forn_info: dict = field(default_factory=dict)


def _freight_expr(cfg, modal, o, d, qty_var, n_var, pa_or_mp, km_fn):
    """Frete LINEAR p/ objetivo: n_viagens × frete_viagem × km (calibrado).
    (custo exato ≥80%/<80% é recomputado pós-solve)."""
    k = km_fn(modal, o, d)
    if k <= 0:
        return 0.0
    return n_var * FRETE_VIAGEM[modal] * k


def construir_bloco(
    m: mip.Model, label: str, ops: List[Dict], precos: Dict[str, float],
    estado: EstadoRodada, cfg: Config,
    stk_mp_ini: Dict[str, Any], stk_pa_ini: Dict[tuple, Any],
    mp_em_transito: List[Dict[str, Any]], lt_fn, km_fn, relax: bool = False,
) -> BlocoRodada:
    """Monta um bloco-rodada. stk_*_ini podem ser floats (rodada atual) ou
    vars/exprs (cenários, ligados ao fim da rodada anterior).

    relax=True → bloco LP (atende-fração contínuo, viagens contínuas): usado nos
    CENÁRIOS futuros (só valoram o buffer; não geram plano executável). A rodada
    ATUAL usa relax=False (MILP exato, viagens inteiras, atende tudo-ou-nada)."""
    VT_X = mip.CONTINUOUS if relax else mip.BINARY
    VT_N = mip.CONTINUOUS if relax else mip.INTEGER
    fab = estado.fab_cidade
    cds_info = estado.cds_info
    cds = list(cds_info.keys())
    P = label  # prefixo único de nomes

    # Rotas viáveis por OP
    op_rotas: Dict[int, List[Dict]] = {}
    for i, op in enumerate(ops):
        rotas = []
        for cd in cds:
            cd_cid = cds_info[cd]
            for m1 in MODAIS:
                lt1 = lt_fn(m1, fab, cd_cid)
                if lt1 is None:
                    continue
                for m2 in MODAIS:
                    lt2 = lt_fn(m2, cd_cid, op["cidade"])
                    if lt2 is None:
                        continue
                    tprod = op["dia_entrega"] - lt1 - lt2
                    if 1 <= tprod <= 5:
                        rotas.append({"cd": cd, "m2": m2, "t_envio": op["dia_entrega"] - lt2})
        op_rotas[i] = rotas

    forn_info = {}
    for mp in MPS:
        lst = []
        for f, c in cfg.fornecedores[mp]:
            l = lt_fn("Caminhão", f, fab)
            if l is not None:
                lst.append((f, float(c), l))
        forn_info[mp] = lst

    # --- Variáveis ---
    x_op = [m.add_var(name=f"x_{P}_{i}", var_type=VT_X, ub=1.0) for i in range(len(ops))]
    prod = {(t, pa): m.add_var(name=f"prod_{P}_{t}_{pa}", var_type=VT_N, lb=0)
            for t in DIAS for pa in PAS}
    n_buy, qty_buy = {}, {}
    for mp in MPS:
        for fi, (forn, custo, ltf) in enumerate(forn_info[mp]):
            for t in DIAS:
                n_buy[(t, mp, fi)] = m.add_var(name=f"nbuy_{P}_{t}_{mp}_{fi}", var_type=VT_N, lb=0)
                qty_buy[(t, mp, fi)] = m.add_var(name=f"qbuy_{P}_{t}_{mp}_{fi}", lb=0)
    n_f1cd, qty_f1cd = {}, {}
    for t in DIAS:
        for cd in cds:
            for pa in PAS:
                for mod in MODAIS:
                    if lt_fn(mod, fab, cds_info[cd]) is None:
                        continue
                    n_f1cd[(t, cd, pa, mod)] = m.add_var(name=f"nf_{P}_{t}_{cd}_{pa}_{mod}", var_type=VT_N, lb=0)
                    qty_f1cd[(t, cd, pa, mod)] = m.add_var(name=f"qf_{P}_{t}_{cd}_{pa}_{mod}", lb=0)
    n_cdv, qty_cdv = {}, {}
    for i, op in enumerate(ops):
        for r in op_rotas[i]:
            key = (r["t_envio"], r["cd"], op["cidade"], op["pa"], r["m2"])
            if key not in n_cdv:
                n_cdv[key] = m.add_var(name=f"nc_{P}_{key[0]}_{key[1]}_{key[2]}_{key[3]}_{key[4]}", var_type=VT_N, lb=0)
                qty_cdv[key] = m.add_var(name=f"qc_{P}_{key[0]}_{key[1]}_{key[2]}_{key[3]}_{key[4]}", lb=0)

    stk_mp = {(t, mp): m.add_var(name=f"smp_{P}_{t}_{mp}", lb=0) for t in [0, *DIAS] for mp in MPS}
    stk_pa = {(t, cd, pa): m.add_var(name=f"spa_{P}_{t}_{cd}_{pa}", lb=0)
              for t in [0, *DIAS] for cd in cds for pa in PAS}

    # Estoque inicial (float fixo ou ligado à rodada anterior)
    for mp in MPS:
        m += stk_mp[(0, mp)] == stk_mp_ini[mp]
    for cd in cds:
        for pa in PAS:
            m += stk_pa[(0, cd, pa)] == stk_pa_ini[(cd, pa)]

    # --- Restrições (as 13 do v1) ---
    for t in DIAS:                                   # 1 cap fábrica
        m += mip.xsum(prod[(t, pa)] / VEL_UN_MIN[pa] for pa in PAS) <= estado.cap_min_dia
    for key, q in qty_f1cd.items():                  # 2 cap modal F1->CD
        m += q <= n_f1cd[key] * _cap_un(key[3], key[2])
    for key, q in qty_cdv.items():                   # 3 cap modal CD->V
        m += q <= n_cdv[key] * _cap_un(key[4], key[3])
    for key, q in qty_buy.items():                   # 4 cap modal Forn->F1
        m += q <= n_buy[key] * CAP_MODAL_TON["Caminhão"]
    for t in DIAS:                                   # 5 PA sai no mesmo dia
        for pa in PAS:
            m += prod[(t, pa)] == mip.xsum(qty_f1cd[(t, cd, pa, mod)] for cd in cds for mod in MODAIS
                                           if (t, cd, pa, mod) in qty_f1cd)
    em_transito = {(d, mp): 0.0 for d in DIAS for mp in MPS}
    for x in mp_em_transito:
        em_transito[(int(x["dia_rel"]), x["mp"])] += float(x["qtd"])
    for t in DIAS:                                   # 6 balanço MP
        for mp in MPS:
            cheg = [qty_buy[(t - ltf, mp, fi)] for fi, (f, c, ltf) in enumerate(forn_info[mp]) if (t - ltf) in DIAS]
            consumo = mip.xsum(prod[(t, pa)] * BOM[pa][mp] / 1_000_000 for pa in PAS)
            m += stk_mp[(t, mp)] == stk_mp[(t - 1, mp)] + em_transito[(t, mp)] + (mip.xsum(cheg) if cheg else 0) - consumo
    for t in DIAS:                                   # 7 cap MP F1
        for mp in MPS:
            m += stk_mp[(t, mp)] <= estado.cap_mp_ton[mp]
    for t in DIAS:                                   # 8 balanço PA nos CDs
        for cd in cds:
            for pa in PAS:
                cheg = []
                for mod in MODAIS:
                    lt_v = lt_fn(mod, fab, cds_info[cd])
                    if lt_v is not None and (t - lt_v) in DIAS:
                        cheg.append(qty_f1cd[(t - lt_v, cd, pa, mod)])
                saidas = [v for k, v in qty_cdv.items() if k[0] == t and k[1] == cd and k[3] == pa]
                m += stk_pa[(t, cd, pa)] == stk_pa[(t - 1, cd, pa)] + (mip.xsum(cheg) if cheg else 0) - (mip.xsum(saidas) if saidas else 0)
    for t in DIAS:                                   # 9 cap PA CDs
        for cd in cds:
            for pa in PAS:
                m += stk_pa[(t, cd, pa)] <= estado.cap_pa_cd_un[cd][pa]
    for i, op in enumerate(ops):                     # 10 entrega no dia exato
        if not op_rotas[i]:
            m += x_op[i] == 0
            continue
        keys = {(r["t_envio"], r["cd"], op["cidade"], op["pa"], r["m2"]) for r in op_rotas[i]}
        m += mip.xsum(qty_cdv[k] for k in keys) == op["qtd"] * x_op[i]

    # --- Expressões econômicas ---
    receita = mip.xsum(x_op[i] * ops[i]["qtd"] * precos[ops[i]["pa"]] for i in range(len(ops)))
    custo_mp = mip.xsum(qty_buy[(t, mp, fi)] * forn_info[mp][fi][1]
                        for mp in MPS for fi in range(len(forn_info[mp])) for t in DIAS)
    frete = mip.xsum(_freight_expr(cfg, "Caminhão", forn_info[mp][fi][0], fab, qty_buy[(t, mp, fi)], n_buy[(t, mp, fi)], mp, km_fn)
                     for mp in MPS for fi in range(len(forn_info[mp])) for t in DIAS)
    frete += mip.xsum(_freight_expr(cfg, k[3], fab, cds_info[k[1]], qty_f1cd[k], n_f1cd[k], k[2], km_fn) for k in qty_f1cd)
    frete += mip.xsum(_freight_expr(cfg, k[4], cds_info[k[1]], k[2], qty_cdv[k], n_cdv[k], k[3], km_fn) for k in qty_cdv)
    maior_mp = {"MP1": 56000, "MP2": 22000, "MP3": 41000}
    carreg = mip.xsum(stk_mp[(5, mp)] * maior_mp[mp] * 0.01 for mp in MPS)
    carreg += mip.xsum(stk_pa[(5, cd, pa)] * precos[pa] * 0.01 for cd in cds for pa in PAS)
    unmet = mip.xsum(ops[i]["qtd"] * (1 - x_op[i]) for i in range(len(ops)))
    trips = mip.xsum(n_buy[k] for k in n_buy) + mip.xsum(n_f1cd[k] for k in n_f1cd) + mip.xsum(n_cdv[k] for k in n_cdv)
    m += trips <= MAX_TRANSPORTES                    # 13 ≤220 viagens

    return BlocoRodada(label, x_op, prod, qty_buy, n_buy, qty_f1cd, n_f1cd, qty_cdv, n_cdv,
                       stk_mp, stk_pa, ops, receita, custo_mp + frete + carreg, unmet,
                       receita - (custo_mp + frete + carreg), trips,
                       fab=fab, cds_info=dict(cds_info), forn_info=forn_info)


@dataclass
class ResultadoMulti:
    status: str
    runtime_s: float
    blocos: Dict[str, Dict[str, Any]] = field(default_factory=dict)
    bloco_R: Any = None
    cenarios: Dict[str, Any] = field(default_factory=dict)
    lt_fn: Any = None
    km_fn: Any = None


def _make_lt_km(cfg):
    leads = _carregar_leads()

    def lt_fn(modal, o, d):
        return 0 if o == d else leads.get(modal, {}).get(o, {}).get(d)

    def km_fn(modal, o, d):
        if o == d:
            return 0.0
        try:
            v = cfg.distancias[modal].at[o, d]
            return float(v) if v and v > 0 else 0.0
        except (KeyError, ValueError):
            return 0.0
    return lt_fn, km_fn


def _ops_cenario(forecast_pa: Dict[str, List[float]], pa: str, day_map: Dict[str, int],
                 idx: int) -> List[Dict]:
    """OPs de um cenário (rodada cheia do produto pa), usando o forecast por cidade
    e o mapa de dia-de-entrega (proxy: dias relativos observados em R4)."""
    ops = []
    for cidade, vals in forecast_pa.items():
        q = int(round(vals[idx])) if idx < len(vals) else 0
        if q > 0:
            ops.append({"cidade": cidade, "pa": pa, "qtd": q,
                        "dia_entrega": day_map.get(cidade, 3)})
    return ops


def resolver_multi(
    estado: EstadoRodada, ops_atual: List[Dict], precos_atual: Dict[str, float],
    cfg: Config, forecast: Dict[str, Dict[str, List[float]]] | None = None,
    day_map: Dict[str, int] | None = None,
    precos_futuro: Dict[str, float] | None = None,
    alpha: float = 100.0, time_limit_s: float = 240, verbose: bool = False,
    relax_cenarios: bool = True, n_future: int = 1, solver_name: str = mip.CBC,
) -> ResultadoMulti:
    """Modelo multi-rodada. Rodada atual (demanda conhecida) + R+1 como 3 cenários
    (1/3 PA1/PA2/PA3, rodada cheia do forecast), com estoque de MP do fim da rodada
    atual COMPARTILHADO pelos cenários (buffer endógeno). NS = receita (penalidade α).
    Se forecast=None, roda só a rodada atual (modo base)."""
    lt_fn, km_fn = _make_lt_km(cfg)
    precos_futuro = precos_futuro or {"PA1": 80, "PA2": 50, "PA3": 32}
    m = mip.Model(name="FLAMENGO_V2", solver_name=solver_name)
    m.verbose = 1 if verbose else 0

    stk_mp_ini = {mp: estado.estoque_mp_ton.get(mp, 0.0) for mp in MPS}
    stk_pa_ini = {(cd, pa): estado.estoque_pa_cd.get(cd, {}).get(pa, 0) for cd in estado.cds_info for pa in PAS}

    # Bloco da rodada ATUAL (R4)
    b = construir_bloco(m, "R", ops_atual, precos_atual, estado, cfg,
                        stk_mp_ini, stk_pa_ini, estado.mp_em_transito, lt_fn, km_fn)
    obj = b.lucro_expr - alpha * b.unmet_expr

    # Cenários futuros encadeados (R5, R6, R7...) por BUFFER MÉDIO (mean-chain):
    # cada rodada futura = 3 cenários (1/3 PA1/PA2/PA3) partindo do estoque do fim
    # da rodada anterior; o próximo round parte da MÉDIA dos 3 (evita árvore 3^k).
    cenarios = {}
    if forecast is not None:
        prev_mp = {mp: b.stk_mp[(5, mp)] for mp in MPS}
        prev_pa = {(cd, pa): b.stk_pa[(5, cd, pa)] for cd in estado.cds_info for pa in PAS}
        for k in range(n_future):                       # k=0→R(atual+1), ...
            rod = estado.rodada + 1 + k
            blocos_rod = {}
            for pa in PAS:
                ops_s = _ops_cenario(forecast[pa], pa, day_map or {}, k)
                if not ops_s:
                    continue
                bs = construir_bloco(m, f"R{rod}{pa}", ops_s, precos_futuro, estado, cfg,
                                     prev_mp, prev_pa, [], lt_fn, km_fn, relax=relax_cenarios)
                blocos_rod[pa] = bs
                cenarios[f"R{rod}_{pa}"] = bs
                obj += (1.0 / 3.0) * (bs.lucro_expr - alpha * bs.unmet_expr)
            if not blocos_rod:
                break
            pas_ok = list(blocos_rod.keys()); nb = len(pas_ok)
            prev_mp = {mp: mip.xsum(blocos_rod[p].stk_mp[(5, mp)] for p in pas_ok) / nb for mp in MPS}
            prev_pa = {(cd, pa): mip.xsum(blocos_rod[p].stk_pa[(5, cd, pa)] for p in pas_ok) / nb
                       for cd in estado.cds_info for pa in PAS}

    m.objective = mip.maximize(obj)
    t0 = time.time()
    status = m.optimize(max_seconds=time_limit_s)
    rt = time.time() - t0

    res = ResultadoMulti(status=str(status), runtime_s=rt)
    res.bloco_R = b
    res.cenarios = cenarios
    res.lt_fn, res.km_fn = lt_fn, km_fn

    def g(v):
        try:
            return v.x or 0.0
        except Exception:
            return 0.0

    if m.num_solutions:
        def resumo(bl):
            served = sum(bl.ops[i]["qtd"] for i in range(len(bl.ops)) if g(bl.x_op[i]) > 0.5)
            total = sum(o["qtd"] for o in bl.ops)
            return {
                "ns_pct": served / total * 100 if total else 0, "served": served, "total": total,
                "receita": float(g(bl.receita_expr)), "custo": float(g(bl.custo_expr)),
                "lucro": float(g(bl.lucro_expr)), "trips": float(g(bl.trips_expr)),
                "stk_mp_fim": {mp: round(g(bl.stk_mp[(5, mp)]), 2) for mp in MPS},
                "prod_dia": {t: {pa: round(g(bl.prod[(t, pa)])) for pa in PAS} for t in DIAS},
            }
        res.blocos["R"] = resumo(b)
        for lbl, bs in cenarios.items():
            res.blocos[lbl] = resumo(bs)
    return res


if __name__ == "__main__":
    import io, warnings
    warnings.filterwarnings("ignore")
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
    from solver.state import estado_r4_flamengo
    from solver.solve import ops_r4
    cfg = Config.load(BASE)
    estado = estado_r4_flamengo()
    res = resolver_multi(estado, ops_r4(), {"PA1": 80, "PA2": 50, "PA3": 20},
                         cfg, alpha=60.0, time_limit_s=120, verbose=False)
    print(f"Status: {res.status} ({res.runtime_s:.1f}s)")
    for lbl, d in res.blocos.items():
        print(f"\n[{lbl}] NS={d['ns_pct']:.1f}% ({d['served']:,}/{d['total']:,})")
        print(f"  Receita R$ {d['receita']:,.0f} | Custo R$ {d['custo']:,.0f} | Lucro R$ {d['lucro']:,.0f}")
        print(f"  Trips {d['trips']:.0f}/220 | MP fim {d['stk_mp_fim']}")
