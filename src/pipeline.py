"""Orquestração: roda uma rodada completa do jogo."""
from __future__ import annotations
import copy
import math
from pathlib import Path
from typing import Any, Dict, List, Optional, Union

import pandas as pd

from src.config import Config
from src.domain import Estado, OP, OPDescartada, TransitItem
from src.estado import carregar_estado, salvar_estado, snapshot_rodada
from src.factibilidade import gerar_cockpit
from src.forecast import (
    treinar_inicial, refit, prever,
    salvar_modelos, carregar_modelos, agregar_op_para_serie,
)
from src.io_xlsm import (
    ler_instalacoes, ler_op_rodada, ler_sol_transp,
    escrever_plano, calcular_rod_dia_chegada,
)
from src.lp_modal import otimizar_modal
from src.planner import (
    passo1_entregas_cd_varejo,
    passo2_reposicao_fabrica_cd,
    passo3_producao,
    passo4_compras_mp,
)


def _construir_cidades_por_cd(cfg: Config, cds_info: Dict[str, str]) -> Dict[str, List[str]]:
    cidades_por_cd: Dict[str, List[str]] = {cd: [] for cd in cds_info}
    for cidade in cfg.ne_por_cidade:
        melhor_cd = None
        melhor_dist = float("inf")
        for cd, cidade_cd in cds_info.items():
            try:
                d = float(cfg.distancias["Caminhão"].at[cidade_cd, cidade])
            except Exception:
                continue
            if d < melhor_dist:
                melhor_dist = d
                melhor_cd = cd
        if melhor_cd:
            cidades_por_cd[melhor_cd].append(cidade)
    return cidades_por_cd


def _capacidade_pa_frascos(area_m2: float, cfg: Config, pa: str) -> int:
    ton = area_m2 * cfg.capacidades["pe_direito_deposito_m"] * cfg.densidades_pa[pa]
    return int(ton / cfg.peso_un_ton[pa])


def _aplicar_chegadas(estado: Estado, rodada_n: int, cfg: Config, instalacoes: Dict) -> Estado:
    cap_mp_F1 = {
        mp: (instalacoes["fabricas"]["F1"]["area_mp"][mp]
             * cfg.capacidades["pe_direito_deposito_m"]
             * cfg.densidades_mp[mp])
        for mp in ("MP1", "MP2", "MP3")
    }
    cap_pa_cd = {
        cd: {pa: _capacidade_pa_frascos(instalacoes["cds"][cd]["area_pa"][pa], cfg, pa)
             for pa in ("PA1", "PA2", "PA3")}
        for cd in instalacoes["cds"]
        if instalacoes["cds"][cd].get("cidade")
    }
    novos_transit = []
    for t in estado.transit:
        if t.rod_cheg > rodada_n:
            novos_transit.append(t)
            continue
        if t.item.startswith("MP") and t.destino_tipo == "Fábrica":
            atual = estado.estoque_mp_fabrica.get("F1", {}).get(t.item, 0.0)
            cap = cap_mp_F1[t.item]
            aceita = min(t.qtd, max(0.0, cap - atual))
            estado.estoque_mp_fabrica["F1"][t.item] = atual + aceita
        elif t.item.startswith("PA") and t.destino_tipo == "CD":
            cd_dest = next((cd for cd, info in instalacoes["cds"].items()
                            if info.get("cidade") == t.destino_cidade), None)
            if cd_dest is None:
                continue
            atual = estado.estoque_pa_cd[cd_dest].get(t.item, 0)
            cap = cap_pa_cd[cd_dest][t.item]
            aceita = min(int(t.qtd), max(0, cap - atual))
            estado.estoque_pa_cd[cd_dest][t.item] = atual + aceita
    estado.transit = novos_transit
    return estado


def _agregar_saidas_cd(tarefas, cds_info):
    saidas = {cd: {"PA1": 0, "PA2": 0, "PA3": 0} for cd in cds_info}
    for t in tarefas:
        for cd, cidade in cds_info.items():
            if cidade == t.origem_cidade:
                saidas[cd][t.item] = saidas[cd].get(t.item, 0) + t.qtd
                break
    return saidas


def _atualizar_estado_pos_planejamento(estado, planos_transporte, ops, descartadas, rodada_n, cfg):
    for p in planos_transporte:
        try:
            km = float(cfg.distancias[p.modal].at[p.origem_cidade, p.destino_cidade])
        except Exception:
            km = 0
        vel = {"Avião": 700, "Caminhão": 50, "Navio": 30}[p.modal]
        horas = km / vel if vel else 0
        lead = max(1, math.ceil(horas / 8))
        rc, dc = calcular_rod_dia_chegada(rodada_n, p.dia_coleta, lead)
        estado.transit.append(TransitItem(
            rod_part=rodada_n, dia_part=p.dia_coleta, rod_cheg=rc, dia_cheg=dc,
            origem_tipo=p.origem_tipo, origem_cidade=p.origem_cidade,
            destino_tipo=p.destino_tipo, destino_cidade=p.destino_cidade,
            modal=p.modal, item=p.item, qtd=p.qtd,
        ))
    for op in ops:
        if op.rodada == rodada_n:
            estado.ops_atendidas.append(op)
    estado.ops_descartadas.extend(descartadas)
    return estado


def _normalizar_ops(ops: Optional[List], rodada_n: int) -> List[OP]:
    """Converte uma lista heterogênea (OP ou dict) numa lista de OP."""
    if ops is None:
        return []
    resultado: List[OP] = []
    for o in ops:
        if isinstance(o, OP):
            resultado.append(o)
        elif isinstance(o, dict):
            resultado.append(OP(
                rodada=o.get("rodada", rodada_n),
                cidade=o["cidade"],
                pa=o["pa"],
                qtd=int(o["qtd"]),
                dia_entrega=int(o["dia_entrega"]),
            ))
    return resultado


def _estimar_margem_op(
    op: OP,
    precos: Dict[str, float],
    cfg: Config,
    cds_info: Dict[str, str],
) -> float:
    """Estima margem (%) de uma OP usando CD mais próximo + frete cheio em Caminhão.

    Aproximação para filtragem inicial — o LP refina depois.
    """
    preco = float(precos.get(op.pa, 0.0))
    receita = op.qtd * preco
    if receita <= 0:
        return -math.inf

    # CD mais próximo por Caminhão
    melhor_dist = float("inf")
    for cd_cidade in cds_info.values():
        try:
            d = float(cfg.distancias["Caminhão"].at[cd_cidade, op.cidade])
        except Exception:
            continue
        if math.isnan(d) or d < 0:
            continue
        if d < melhor_dist:
            melhor_dist = d
    if melhor_dist == float("inf"):
        melhor_dist = 0.0

    custo_frete = (
        cfg.frete_viagem["Caminhão"] * melhor_dist + cfg.doc_modal["Caminhão"]
    )
    margem_pct = (receita - custo_frete) / receita * 100.0
    return margem_pct


def run_rodada(
    rodada_n: int,
    rodada_xlsm_path: Path,
    ops: Optional[List[Union[OP, Dict]]] = None,
    precos: Optional[Dict[str, float]] = None,
    margem_minima_pct: float = 0.0,
) -> Dict[str, Any]:
    base = Path.cwd()
    cfg = Config.load(base)

    estado_path = base / "estado" / "state.json"
    estado = carregar_estado(estado_path)

    instalacoes = ler_instalacoes(rodada_xlsm_path)
    cds_info = {cd: d["cidade"] for cd, d in instalacoes["cds"].items()}
    fabricas_info = {f: d["cidade"] for f, d in instalacoes["fabricas"].items()}
    fabrica_principal = "F1"
    fabrica_cidade = fabricas_info[fabrica_principal]

    # ---- OPs: do parâmetro (Python) ou do arquivo OP_Rodada_N.xlsx ----
    if ops is None:
        op_path = base / "rodadas" / f"OP_Rodada_{rodada_n}.xlsx"
        ops_list: List[OP] = ler_op_rodada(op_path)
    else:
        ops_list = _normalizar_ops(ops, rodada_n)

    # ---- Preços: do parâmetro ou do cfg ----
    precos_final: Dict[str, float] = (
        dict(precos) if precos is not None else dict(cfg.precos_referencia)
    )

    # Reconstrói transit a partir do SOL_TRANSP da rodada atual (preenchido pelo prof/usuário).
    # Crucial para Rodada 1, onde a planilha já tem decisões tomadas pelo usuário e o
    # state.json ainda não existe. Para rodadas N>1, mescla com transit já em state.json
    # (dedup por chave (rod_part, dia_part, modal, item, origem→destino)).
    transit_da_planilha = ler_sol_transp(rodada_xlsm_path, rodada=rodada_n)
    chaves_existentes = {(t.rod_part, t.dia_part, t.modal, t.item,
                          t.origem_cidade, t.destino_cidade) for t in estado.transit}
    for t in transit_da_planilha:
        k = (t.rod_part, t.dia_part, t.modal, t.item, t.origem_cidade, t.destino_cidade)
        if k not in chaves_existentes:
            estado.transit.append(t)

    estado = _aplicar_chegadas(estado, rodada_n, cfg, instalacoes)

    hw_path = base / "estado" / "hw_models.json"
    hist_path = base / "estado" / "historico_demanda_ampliado.parquet"

    if not hist_path.exists():
        # Schema do data/demanda_long.parquet: ano, rodada, pa(minúsculo), cidade, qtd,
        # unique_id, ds, y. Normalizamos para o schema esperado pelo forecast:
        # periodo_global, cidade, PA, qtd.
        hist_raw = pd.read_parquet(base / "data" / "demanda_long.parquet")
        hist = pd.DataFrame({
            "periodo_global": (hist_raw["ano"] - 1) * 48 + hist_raw["rodada"],
            "cidade": hist_raw["cidade"].astype(str),
            "PA": hist_raw["pa"].astype(str),
            "qtd": hist_raw["qtd"].astype(float),
        })
        hist_path.parent.mkdir(parents=True, exist_ok=True)
        hist.to_parquet(hist_path, index=False)
    if not hw_path.exists():
        hist = pd.read_parquet(hist_path)
        modelos = treinar_inicial(hist)
        salvar_modelos(modelos, hw_path)
    else:
        modelos = carregar_modelos(hw_path)

    if ops_list:
        agg = agregar_op_para_serie(ops_list, rodada_n)
        modelos = refit(hist_path, modelos, agg, rodada_n)
        salvar_modelos(modelos, hw_path)

    forecast = prever(modelos, horizonte=4)

    # ---- Snapshot do estado ANTES do planejamento (para cockpit) ----
    estado_antes_planejamento = copy.deepcopy(estado)

    # ---- Margem check: filtra OPs com margem estimada < margem_minima_pct ----
    ops_recusadas_margem: List[OPDescartada] = []
    ops_validas: List[OP] = []
    for op in ops_list:
        if op.rodada != rodada_n:
            ops_validas.append(op)
            continue
        margem_est = _estimar_margem_op(op, precos_final, cfg, cds_info)
        if margem_est < margem_minima_pct:
            ops_recusadas_margem.append(OPDescartada(
                op=op,
                motivo="margem_negativa",
                rodada_descarte=rodada_n,
            ))
        else:
            ops_validas.append(op)

    cidades_por_cd = _construir_cidades_por_cd(cfg, cds_info)
    tarefas_cd_varejo, descartadas1 = passo1_entregas_cd_varejo(
        estado, ops_validas, cfg, cds_info, rodada_n,
    )
    saidas_cd = _agregar_saidas_cd(tarefas_cd_varejo, cds_info)
    cap_pa_cd_frascos = {
        cd: {pa: _capacidade_pa_frascos(instalacoes["cds"][cd]["area_pa"][pa], cfg, pa)
             for pa in ("PA1", "PA2", "PA3")}
        for cd in cds_info
    }
    necessidades = passo2_reposicao_fabrica_cd(
        estado, forecast, cfg, cds_info, cidades_por_cd,
        saidas_cd, rodada_n, fabrica_cidade=fabrica_cidade,
        cap_pa_cd_frascos=cap_pa_cd_frascos,
    )
    planos_prod, tarefas_fab_cd = passo3_producao(
        necessidades, cfg, cds_info, rodada_n,
        fabrica=fabrica_principal, fabrica_cidade=fabrica_cidade,
        maquinas=instalacoes["fabricas"][fabrica_principal]["maquinas"],
        turnos=instalacoes["fabricas"][fabrica_principal]["turnos"],
    )
    cap_mp = {
        mp: (instalacoes["fabricas"][fabrica_principal]["area_mp"][mp]
             * cfg.capacidades["pe_direito_deposito_m"]
             * cfg.densidades_mp[mp])
        for mp in ("MP1", "MP2", "MP3")
    }
    tarefas_mp, descartadas4 = passo4_compras_mp(
        planos_prod, estado.estoque_mp_fabrica[fabrica_principal],
        cfg, cap_mp, rodada_n, fabrica_cidade, estado.transit,
    )

    tarefas_total = tarefas_cd_varejo + tarefas_fab_cd + tarefas_mp
    planos_transporte = otimizar_modal(tarefas_total, cfg, rodada_n)

    todas_descartadas: List[OPDescartada] = (
        ops_recusadas_margem + descartadas1 + descartadas4
    )

    estado = _atualizar_estado_pos_planejamento(
        estado, planos_transporte, ops_validas,
        todas_descartadas, rodada_n, cfg,
    )

    flamengo_path = base / "rodadas" / "FLAMENGO.xlsm"
    escrever_plano(flamengo_path, planos_transporte, planos_prod, rodada_n)

    estado.rodada_atual = rodada_n

    # ---- Cockpit de factibilidade ----
    cockpit = gerar_cockpit(
        planos_transporte, planos_prod, estado_antes_planejamento,
        ops_list, todas_descartadas, precos_final,
        cfg, instalacoes, rodada_n,
    )

    salvar_estado(estado, estado_path)
    extras = {
        "n_transportes": len(planos_transporte),
        "n_descartadas": len(todas_descartadas),
        "n_atendidas": len(tarefas_cd_varejo),
        "ocupacao_cd": {cd: estado.estoque_pa_cd[cd] for cd in cds_info},
        "cockpit": cockpit,
    }
    snapshot_rodada(estado, rodada_n, extras, base / "estado")
    return {
        "rodada": rodada_n,
        "transportes": len(planos_transporte),
        "producao_total": sum(p.qtd for p in planos_prod),
        "ops_atendidas": cockpit["atendimento"]["atendidas"],
        "ops_descartadas": cockpit["atendimento"]["descartadas"],
        "receita": cockpit["financeiro"]["receita"],
        "margem_R$": cockpit["financeiro"]["margem_R$"],
        "margem_pct": cockpit["financeiro"]["margem_pct"],
        "alertas": cockpit["alertas"],
        "cockpit": cockpit,
    }
