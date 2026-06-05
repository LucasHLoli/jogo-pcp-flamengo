"""MILP de alocação modal (PuLP + CBC)."""
from __future__ import annotations
from pathlib import Path
from typing import List

import pulp

from src.config import Config
from src.domain import PlanoTransporte, TarefaTransporte


def otimizar_modal(
    tarefas: List[TarefaTransporte],
    cfg: Config,
    rodada_n: int,
    max_transportes: int = 220,
    time_limit_s: int = 30,
) -> List[PlanoTransporte]:
    if not tarefas:
        return []

    prob = pulp.LpProblem("modal_alloc", pulp.LpMinimize)
    modais = ("Avião", "Caminhão", "Navio")

    x = {}
    n = {}
    o80 = {}
    xl_lo = {}
    used = {}
    pares_ativos = []

    for i, t in enumerate(tarefas):
        for m in modais:
            if m == "Navio" and (t.origem_cidade, t.destino_cidade) not in cfg.rotas_navio_validas:
                continue
            try:
                km = float(cfg.distancias[m].at[t.origem_cidade, t.destino_cidade])
            except Exception:
                continue
            if not (km and km > 0):
                continue
            cap = cfg.cap_modal_por_item[m][t.item]
            if cap <= 0:
                continue
            for d in t.janela_dias:
                key = (i, m, d)
                pares_ativos.append(key)
                x[key]    = pulp.LpVariable(f"x_{i}_{m}_{d}", lowBound=0)
                n[key]    = pulp.LpVariable(f"n_{i}_{m}_{d}", lowBound=0, cat=pulp.LpInteger)
                o80[key]  = pulp.LpVariable(f"o80_{i}_{m}_{d}", cat=pulp.LpBinary)
                xl_lo[key] = pulp.LpVariable(f"xllo_{i}_{m}_{d}", lowBound=0)
                used[key] = pulp.LpVariable(f"used_{i}_{m}_{d}", cat=pulp.LpBinary)

    if not pares_ativos:
        return []

    # objetivo
    custo_terms = []
    for (i, m, d) in pares_ativos:
        t = tarefas[i]
        km = float(cfg.distancias[m].at[t.origem_cidade, t.destino_cidade])
        peso = cfg.peso_un_ton.get(t.item, 1.0) if t.item.startswith("PA") else 1.0
        # Regra oficial calibrada vs DRE real R3: ≥80% → frete-viagem cheio;
        # <80% → frete-peso puro. SEM parcela fixa de meia-viagem e SEM CT-e/doc.
        custo_terms.append(cfg.frete_viagem[m] * km * (n[(i,m,d)] - used[(i,m,d)]))  # n-used cheias
        custo_terms.append(cfg.frete_viagem[m] * km * o80[(i,m,d)])                   # última ≥80%
        custo_terms.append(cfg.frete_peso[m] * km * peso * xl_lo[(i,m,d)])           # última <80% (só peso)
    prob += pulp.lpSum(custo_terms)

    # 1) Conservação por tarefa
    for i, t in enumerate(tarefas):
        soma = [x[(j, m, d)] for (j, m, d) in pares_ativos if j == i]
        if soma:
            prob += pulp.lpSum(soma) == t.qtd, f"conserv_{i}"

    # 2) Cap, used, cota inferior, acoplamento o80
    BIG_N = 50
    for (i, m, d) in pares_ativos:
        t = tarefas[i]
        cap = cfg.cap_modal_por_item[m][t.item]
        eps = 1.0 if t.item.startswith("PA") else 0.01
        # used = 1 sse n ≥ 1
        prob += n[(i,m,d)] <= BIG_N * used[(i,m,d)], f"used_up_{i}_{m}_{d}"
        prob += n[(i,m,d)] >= used[(i,m,d)], f"used_lo_{i}_{m}_{d}"
        # cap
        prob += x[(i,m,d)] <= n[(i,m,d)] * cap, f"upper_{i}_{m}_{d}"
        # cota inferior só quando used=1
        prob += x[(i,m,d)] >= (n[(i,m,d)] - 1) * cap + eps - cap * (1 - used[(i,m,d)]), f"lower_{i}_{m}_{d}"
        # se o80=1, x_last ≥ 0.8*cap
        prob += x[(i,m,d)] - (n[(i,m,d)] - 1) * cap >= 0.8 * cap * o80[(i,m,d)] - cap * (1 - used[(i,m,d)]), f"o80_lo_{i}_{m}_{d}"
        # se o80=0, x_last < 0.8*cap (implicador inverso)
        prob += x[(i,m,d)] - (n[(i,m,d)] - 1) * cap <= 0.8 * cap - eps + cap * o80[(i,m,d)] + cap * (1 - used[(i,m,d)]), f"o80_hi_{i}_{m}_{d}"
        # o80 só faz sentido se used=1
        prob += o80[(i,m,d)] <= used[(i,m,d)], f"o80_used_{i}_{m}_{d}"
        # xl_lo = (x - (n-1)*cap) * (1 - o80) via big-M
        prob += xl_lo[(i,m,d)] <= x[(i,m,d)] - (n[(i,m,d)] - 1) * cap + cap * (1 - used[(i,m,d)]), f"xllo1_{i}_{m}_{d}"
        prob += xl_lo[(i,m,d)] <= cap * (1 - o80[(i,m,d)]), f"xllo2_{i}_{m}_{d}"
        prob += xl_lo[(i,m,d)] >= (x[(i,m,d)] - (n[(i,m,d)] - 1) * cap) - cap * o80[(i,m,d)] - cap * (1 - used[(i,m,d)]), f"xllo3_{i}_{m}_{d}"

    # 3) Limite semanal
    prob += pulp.lpSum([n[(i,m,d)] for (i,m,d) in pares_ativos]) <= max_transportes, "max_220"

    # PuLP 3.x removeu tmpDir do PULP_CBC_CMD — usa o tempdir do sistema.
    solver = pulp.PULP_CBC_CMD(timeLimit=time_limit_s, msg=False)
    prob.solve(solver)

    planos: List[PlanoTransporte] = []
    for (i, m, d) in pares_ativos:
        n_val = int(round(pulp.value(n[(i,m,d)]) or 0))
        x_val = float(pulp.value(x[(i,m,d)]) or 0)
        if n_val == 0:
            continue
        t = tarefas[i]
        cap = cfg.cap_modal_por_item[m][t.item]
        for _ in range(n_val - 1):
            planos.append(PlanoTransporte(
                rodada=rodada_n, origem_tipo=t.origem_tipo, origem_cidade=t.origem_cidade,
                dia_coleta=d, modal=m, item=t.item, qtd=cap,
                destino_tipo=t.destino_tipo, destino_cidade=t.destino_cidade,
            ))
        x_last = x_val - (n_val - 1) * cap
        if x_last > 1e-3:
            planos.append(PlanoTransporte(
                rodada=rodada_n, origem_tipo=t.origem_tipo, origem_cidade=t.origem_cidade,
                dia_coleta=d, modal=m, item=t.item, qtd=x_last,
                destino_tipo=t.destino_tipo, destino_cidade=t.destino_cidade,
            ))
    return planos
