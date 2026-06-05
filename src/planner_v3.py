"""Solver V3 — entrega EXATA no dia + minimização de custo.

Regras críticas do jogo:
  - PA tem de chegar EXATAMENTE no dia de entrega; antes ou depois => descartado.
  - PA tem de SAIR da fábrica no mesmo dia em que é produzido.
  - Lead time = max(1, ceil(km / (v_modal * 8h)))  → 1 dia mínimo, "chega no próximo dia útil".
  - Capacidade de transporte por viagem: cam=24t, navio=100t, avião=1t.
  - MP que chega na fábrica sem espaço é descartada.

Modelo:
  Para cada OP (cidade, PA, qtd, dia_entrega) escolhe a rota (CD, modal_f1, modal_cd) tal
  que lt_f1 + lt_cd < dia_entrega (sobrar pelo menos 1 dia para produzir) e cujo custo
  total (frete F1->CD + frete CD->varejo + parcelas de doc) seja mínimo.

  Produção alocada no dia D = dia_entrega - lt_f1 - lt_cd.
  F1 expedição do PA nesse mesmo dia D (modal escolhido).
  CD expede no dia (dia_entrega - lt_cd).

Sobras de capacidade fabril são usadas para o BUFFER do PA da próxima rodada (R+1).
"""
from __future__ import annotations
import json
import math
from collections import defaultdict
from pathlib import Path
from typing import Any, Dict, List, Tuple

import pandas as pd

from src.config import Config


VEL_KMH = {"Avião": 700, "Caminhão": 50, "Navio": 30}
HORAS_DIA = 8


# Lead times do JOGO (lookup oficial da aba Orig_Dest dos arquivos FLAMENGO.xlsm).
# Avião sempre 0 (chega no mesmo dia útil). Caminhão e Navio variam por rota.
_LEAD_TABLE: Dict[str, Dict[str, Dict[str, int]]] | None = None
_LEAD_TABLE_PATH = Path(__file__).resolve().parent.parent / "data" / "lead_times.json"


def _carregar_lead_table() -> Dict[str, Dict[str, Dict[str, int]]]:
    global _LEAD_TABLE
    if _LEAD_TABLE is None:
        _LEAD_TABLE = json.loads(_LEAD_TABLE_PATH.read_text(encoding="utf-8"))
    return _LEAD_TABLE


def lead_dias(cfg: Config, origem: str, destino: str, modal: str) -> int | None:
    """Lead time em dias úteis usando lookup oficial do jogo.

    Retorna None se rota não existe (e.g. Navio entre cidades sem porto).
    Mesma cidade => 0.
    """
    if origem == destino:
        return 0
    tab = _carregar_lead_table()
    return tab.get(modal, {}).get(origem, {}).get(destino)


def km_rota(cfg: Config, origem: str, destino: str, modal: str) -> float | None:
    """Retorna km da rota. None se inexistente. 0 = mesma cidade (rota válida sem frete)."""
    if origem == destino:
        return 0.0
    try:
        km = cfg.distancias[modal].at[origem, destino]
    except (KeyError, ValueError):
        return None
    if km is None or pd.isna(km) or float(km) <= 0:
        return None
    return float(km)


def custo_total_modal(cfg: Config, modal: str, km: float, peso_total_ton: float, n_viagens: int) -> float:
    """Custo total de N viagens — regra oficial CALIBRADA vs DRE real da R3.

    Regra (reproduz o frete realizado com erro <0,3%):
      • ocupação por viagem ≥ 80% → frete-viagem cheio: frete_viagem × km × n
      • ocupação por viagem < 80% → frete-peso puro:     frete_peso  × km × peso_total

    NÃO existe componente fixo de meia-viagem (0,5×frete_viagem) nem CT-e/doc
    separado: ambos foram descartados após bater linha-a-linha com a DRE
    realizada (investigação frete R3 — eram a fonte do erro de +16%).
    """
    if n_viagens <= 0:
        return 0.0
    if km is None or km <= 0:
        return 0.0  # mesma cidade: sem frete
    cap = cfg.cap_modal_ton[modal]
    peso_por_viagem = peso_total_ton / n_viagens
    ocup = peso_por_viagem / cap if cap > 0 else 0
    if ocup >= 0.8:
        return cfg.frete_viagem[modal] * km * n_viagens
    return cfg.frete_peso[modal] * km * peso_total_ton


def n_viagens_pa(cfg: Config, pa: str, modal: str, qtd: int) -> int:
    """Número de viagens para transportar qtd frascos de PA pelo modal."""
    cap_un = cfg.cap_modal_por_item[modal][pa]
    return math.ceil(qtd / cap_un) if qtd > 0 else 0


def custo_rota_pa(cfg: Config, pa: str, qtd: int,
                  fab_cidade: str, cd_cidade: str, varejo: str,
                  modal_f1: str, modal_cd: str) -> float:
    """Custo total da rota F1 -> CD -> Varejo p/ qtd frascos de PA."""
    peso_total_ton = qtd * cfg.peso_un_ton[pa]
    km1 = km_rota(cfg, fab_cidade, cd_cidade, modal_f1)
    km2 = km_rota(cfg, cd_cidade, varejo, modal_cd)
    if km1 is None or km2 is None:
        return math.inf
    n1 = n_viagens_pa(cfg, pa, modal_f1, qtd)
    n2 = n_viagens_pa(cfg, pa, modal_cd, qtd)
    c1 = custo_total_modal(cfg, modal_f1, km1, peso_total_ton, n1)
    c2 = custo_total_modal(cfg, modal_cd, km2, peso_total_ton, n2)
    return c1 + c2


def todas_rotas_op(cfg: Config, op: Dict, fab_cidade: str, cds_info: Dict[str, str]) -> List[Dict]:
    """Retorna TODAS as rotas viáveis para uma OP, ordenadas por custo asc.

    Cada rota: {cd_id, cd_cidade, modal_f1, lt_f1, modal_cd, lt_cd, dia_producao, custo}.
    Lista vazia se nenhuma rota é factível (lead_total >= dia_entrega).
    """
    dia_ent = int(op["dia_entrega"])
    qtd = int(op["qtd"])
    pa = op["pa"]
    cidade = op["cidade"]

    candidatos = []
    for cd_id, cd_cidade in cds_info.items():
        for m1 in ("Caminhão", "Navio", "Avião"):
            lt1 = lead_dias(cfg, fab_cidade, cd_cidade, m1)
            if lt1 is None:
                continue
            for m2 in ("Caminhão", "Navio", "Avião"):
                lt2 = lead_dias(cfg, cd_cidade, cidade, m2)
                if lt2 is None:
                    continue
                dia_prod = dia_ent - lt1 - lt2
                if dia_prod < 1 or dia_prod > 5:
                    continue
                custo = custo_rota_pa(cfg, pa, qtd, fab_cidade, cd_cidade, cidade, m1, m2)
                candidatos.append({
                    "cd_id": cd_id, "cd_cidade": cd_cidade,
                    "modal_f1": m1, "lt_f1": lt1,
                    "modal_cd": m2, "lt_cd": lt2,
                    "dia_producao": dia_prod,
                    "custo": custo,
                })
    candidatos.sort(key=lambda x: x["custo"])
    return candidatos


def melhor_rota_op(cfg: Config, op: Dict, fab_cidade: str, cds_info: Dict[str, str]) -> Dict | None:
    """Wrapper: retorna a rota mais barata, ou None."""
    rotas = todas_rotas_op(cfg, op, fab_cidade, cds_info)
    return rotas[0] if rotas else None


def planejar_v3(
    *,
    rodada_n: int,
    ops_rodada: List[Dict],
    estoque_inicial_mp_ton: Dict[str, float],
    estoque_inicial_pa_cd: Dict[str, Dict[str, int]],
    mp_em_transito_chegando: List[Dict],
    cfg: Config,
    instalacoes: Dict,
    fab_principal: str = "F1",
    pa_proxima_rodada: str | None = None,
    buffer_pa_proxima: int = 0,
    compras_mp_extra_para_r_mais_1: Dict[str, float] | None = None,
) -> Dict[str, Any]:
    """Planeja a rodada otimizando atendimento exato (entrega no dia) e custo.

    Args:
        rodada_n: número da rodada atual (1..15).
        ops_rodada: lista de dicts {cidade, pa, qtd, dia_entrega 1-5}.
        estoque_inicial_mp_ton: MP em F1 no início da rodada (em toneladas).
        estoque_inicial_pa_cd: PA em cada CD no início. {"CD1": {"PA1":0,"PA2":0,"PA3":0}, ...}
        mp_em_transito_chegando: itens chegando DURANTE esta rodada (do final da R-1).
                                 [{"dia": 1..5, "mp": "MP1", "qtd": ton}, ...]
        cfg: Config.
        instalacoes: dict de ler_instalacoes.
        fab_principal: F1.
        pa_proxima_rodada: PA esperado em R+1 (e.g. "PA2") — produz buffer aqui.
        buffer_pa_proxima: quantos frascos de PA proxima estocar nos CDs (split 50/50).
        compras_mp_extra_para_r_mais_1: MP extra a comprar pra cobrir R+1
                                        (chega ainda nesta rodada).

    Returns:
        Dict com df_sol_transp, df_op_fabricas, resumo, ops_descartadas.
    """
    fab_cidade = instalacoes["fabricas"][fab_principal]["cidade"]
    cds_info = {cd: d["cidade"] for cd, d in instalacoes["cds"].items() if d.get("cidade")}
    maquinas = int(instalacoes["fabricas"][fab_principal]["maquinas"])
    turnos = int(instalacoes["fabricas"][fab_principal]["turnos"])
    cap_min_dia = maquinas * turnos * cfg.capacidades["horas_por_turno"] * 60

    # ============ 1. AVALIA TODAS AS ROTAS VIÁVEIS / SEPARA INFACTÍVEIS ============
    descartadas: List[Dict] = []
    ops_com_rotas: List[Dict] = []   # OP + suas rotas viáveis ordenadas por custo

    for op in ops_rodada:
        rotas = todas_rotas_op(cfg, op, fab_cidade, cds_info)
        if not rotas:
            descartadas.append({**op, "motivo": "lead_total >= dia_entrega"})
            continue
        # Anota max_prod_day (rota mais lenta) p/ priorizar OPs rígidas
        max_prod = max(r["dia_producao"] for r in rotas)
        min_prod = min(r["dia_producao"] for r in rotas)
        ops_com_rotas.append({"op": op, "rotas": rotas,
                              "max_prod_day": max_prod, "min_prod_day": min_prod})

    # ============ 2. PRÉ-CALCULA ARRIVALS DE MP DIA A DIA (CUMULATIVO) ============
    # MP cumulativa disponível ao FIM de cada dia.
    # Inclui: estoque inicial + em-trânsito chegando + compras de R3 (apenas as que vão chegar)
    cap_mp_pre = {
        mp: (instalacoes["fabricas"][fab_principal]["area_mp"][mp]
             * cfg.capacidades["pe_direito_deposito_m"]
             * cfg.densidades_mp[mp])
        for mp in ("MP1", "MP2", "MP3")
    }
    # Em-trânsito chegando por dia
    em_transito_dia: Dict[Tuple[int, str], float] = defaultdict(float)
    for it in mp_em_transito_chegando:
        em_transito_dia[(int(it["dia"]), it["mp"])] += float(it["qtd"])
    # Compras programadas em R3 (1 viagem por dia consecutivo a partir do Dia 1)
    # Assumimos: solver compra MAX disponível do fornecedor mais barato.
    # Para constraint check usamos uma estimativa conservadora baseada nos arrivals de R3 buys.
    # Lead times fornecedores
    lt_fornec = {}
    for mp in ("MP1", "MP2", "MP3"):
        forn_cidade, _ = min(cfg.fornecedores[mp], key=lambda x: x[1])
        lt = lead_dias(cfg, forn_cidade, fab_cidade, "Caminhão")
        lt_fornec[mp] = (forn_cidade, lt if lt is not None else 99)

    def mp_cumulativa(mp_buys_estim: Dict[str, float]) -> Dict[int, Dict[str, float]]:
        """Para um dado plano de compras (ton total por MP), retorna MP cumulativa
        disponível ao FIM de cada dia (considera dia_part + lt do fornec)."""
        cum = {d: {} for d in range(0, 6)}
        for mp in ("MP1", "MP2", "MP3"):
            base = estoque_inicial_mp_ton.get(mp, 0.0)
            qtd_total = mp_buys_estim.get(mp, 0.0)
            forn_cidade, lt = lt_fornec[mp]
            cap_cam = cfg.cap_modal_ton["Caminhão"]
            n_viagens = math.ceil(qtd_total / cap_cam) if qtd_total > 0 else 0
            qpv = qtd_total / max(1, n_viagens)
            chega = defaultdict(float)
            for i in range(n_viagens):
                dia_part = 1 + i
                if dia_part > 5: dia_part = 5
                dia_cheg = dia_part + lt
                if 1 <= dia_cheg <= 5:
                    chega[dia_cheg] += qpv
            cum[0][mp] = base
            for d in range(1, 6):
                cum[d][mp] = cum[d-1][mp] + chega[d] + em_transito_dia[(d, mp)]
                cum[d][mp] = min(cum[d][mp], cap_mp_pre[mp])  # respeita cap
        return cum

    # Primeiro chute: compra TODO MP necessário para a demanda total
    demanda_pa_total_estim = {"PA1": 0, "PA2": 0, "PA3": 0}
    for item in ops_com_rotas:
        demanda_pa_total_estim[item["op"]["pa"]] += int(item["op"]["qtd"])
    if pa_proxima_rodada and buffer_pa_proxima > 0:
        demanda_pa_total_estim[pa_proxima_rodada] += buffer_pa_proxima
    mp_need_total = {mp: 0.0 for mp in ("MP1", "MP2", "MP3")}
    for pa, q in demanda_pa_total_estim.items():
        for mp in ("MP1", "MP2", "MP3"):
            mp_need_total[mp] += q * cfg.BoM[pa][mp] / 1_000_000
    mp_buy_estim = {
        mp: max(0, mp_need_total[mp]
                  - estoque_inicial_mp_ton.get(mp, 0.0)
                  - sum(em_transito_dia[(d, mp)] for d in range(1, 6)))
        for mp in ("MP1", "MP2", "MP3")
    }
    if compras_mp_extra_para_r_mais_1:
        for mp, q in compras_mp_extra_para_r_mais_1.items():
            mp_buy_estim[mp] = mp_buy_estim.get(mp, 0.0) + q

    mp_cum_disp = mp_cumulativa(mp_buy_estim)

    # ============ 3. ALOCAR PRODUÇÃO RESPEITANDO CAPACIDADE FABRIL + MP DIA A DIA ============
    producao_diaria: Dict[int, Dict[str, int]] = {d: {"PA1": 0, "PA2": 0, "PA3": 0} for d in range(1, 6)}
    cap_restante = {d: cap_min_dia for d in range(1, 6)}
    velocidades = cfg.velocidades
    rotas_op: List[Dict] = []

    # Consumo cumulativo MP por dia (vai aumentando)
    mp_consumo_cum = {d: {"MP1": 0.0, "MP2": 0.0, "MP3": 0.0} for d in range(0, 6)}

    # Margem de segurança MP (kg) — evita rounding/timing intra-rodada
    # 200 kg = 0,2 ton folga por MP. Cobre o threshold de 0.1t na hora de comprar
    # (se mp_a_comprar < 0.1t, não compra → planner deixa estoque acabar exatamente).
    MP_SAFETY_KG = 200

    def alocar_no_dia(dia: int, pa: str, qtd: int) -> bool:
        """Verifica se cabe a produção (pa, qtd) no dia, respeitando cap_min e MP cum.
        Se sim, ALOCA e retorna True. Se não, False."""
        vel = velocidades[pa]
        min_nec = math.ceil(qtd / vel)
        if cap_restante[dia] < min_nec:
            return False
        # Checa MP: para CADA dia >= dia, o consumo cumulativo+novo não pode exceder mp_cum_disp
        # (com margem de segurança para timing intra-dia)
        for mp in ("MP1", "MP2", "MP3"):
            g = cfg.BoM[pa][mp]
            if g <= 0:
                continue
            adicional = qtd * g / 1_000_000
            for d in range(dia, 6):
                novo_cum = mp_consumo_cum[d][mp] + adicional
                if novo_cum > mp_cum_disp[d][mp] - MP_SAFETY_KG / 1000:
                    return False
        # OK — aloca
        cap_restante[dia] -= min_nec
        producao_diaria[dia][pa] += qtd
        for mp in ("MP1", "MP2", "MP3"):
            adicional = qtd * cfg.BoM[pa][mp] / 1_000_000
            for d in range(dia, 6):
                mp_consumo_cum[d][mp] += adicional
        return True

    # Estratégia: ordena OPs por (max_prod_day asc, -qtd) — inflexíveis primeiro
    ops_com_rotas.sort(key=lambda x: (x["max_prod_day"], -int(x["op"]["qtd"])))
    for item in ops_com_rotas:
        op = item["op"]
        rota_escolhida = None
        # Tenta cada rota (em ordem de custo crescente); para cada, tenta o dia da rota
        for r in item["rotas"]:
            if alocar_no_dia(r["dia_producao"], op["pa"], int(op["qtd"])):
                rota_escolhida = r
                break
        if rota_escolhida is None:
            descartadas.append({**op, "motivo": "sem_capacidade_ou_MP_indisponivel"})
            continue
        rotas_op.append({**op, **rota_escolhida, "alocada": True})

    # ============ 3. ALOCAR PRODUÇÃO DE BUFFER (PA da próxima rodada) ============
    buffer_alocado = 0
    if pa_proxima_rodada and buffer_pa_proxima > 0:
        pa = pa_proxima_rodada
        vel = velocidades[pa]
        restante = buffer_pa_proxima
        # Aloca buffer com MESMA verificação de MP cumulativa.
        # Tenta dias mais tarde primeiro (Navio Joinville→Santos lt=1; dia ≤ 4 chega R3).
        for dia in (4, 5, 3, 2, 1):
            if restante <= 0:
                break
            # Calcula quanto cabe respeitando (a) cap fabril (b) MP cumulativa
            qtd_cabe_cap = cap_restante[dia] * vel
            # Limite por MP (mínimo entre todos os MPs) — desconta safety margin
            qtd_cabe_mp = float("inf")
            for mp in ("MP1", "MP2", "MP3"):
                g = cfg.BoM[pa][mp]
                if g <= 0: continue
                # Quanto MP livre temos a partir do dia até dia 5 (mínimo), descontando safety
                folga = min(mp_cum_disp[d][mp] - mp_consumo_cum[d][mp] - MP_SAFETY_KG/1000
                            for d in range(dia, 6))
                if folga <= 0:
                    qtd_cabe_mp = 0
                else:
                    qtd_cabe_mp = min(qtd_cabe_mp, folga * 1_000_000 / g)
            qtd_cabe = int(min(restante, qtd_cabe_cap, qtd_cabe_mp))
            if qtd_cabe <= 0:
                continue
            # Aloca de fato
            producao_diaria[dia][pa] += qtd_cabe
            cap_restante[dia] -= math.ceil(qtd_cabe / vel)
            for mp in ("MP1", "MP2", "MP3"):
                g = cfg.BoM[pa][mp]
                if g > 0:
                    adicional = qtd_cabe * g / 1_000_000
                    for d in range(dia, 6):
                        mp_consumo_cum[d][mp] += adicional
            restante -= qtd_cabe
            buffer_alocado += qtd_cabe

    # ============ 4. CALCULAR CONSUMO MP DA PRODUÇÃO (TOTAL) ============
    # MP consumida = produção × BoM
    total_producao = {pa: 0 for pa in ("PA1", "PA2", "PA3")}
    for dia in range(1, 6):
        for pa in ("PA1", "PA2", "PA3"):
            total_producao[pa] += producao_diaria[dia][pa]

    mp_consumida_ton = {mp: 0.0 for mp in ("MP1", "MP2", "MP3")}
    for pa, q in total_producao.items():
        for mp in ("MP1", "MP2", "MP3"):
            g = cfg.BoM[pa][mp]
            mp_consumida_ton[mp] += q * g / 1_000_000

    # ============ 5. SIMULAR ESTOQUE MP DIA A DIA (DETECTAR DESCARTE POR FALTA DE ESPAÇO) ============
    cap_mp_ton = {
        mp: (instalacoes["fabricas"][fab_principal]["area_mp"][mp]
             * cfg.capacidades["pe_direito_deposito_m"]
             * cfg.densidades_mp[mp])
        for mp in ("MP1", "MP2", "MP3")
    }
    # MP em trânsito chegando: agrupa por (dia, mp)
    mp_chegando_por_dia: Dict[Tuple[int, str], float] = defaultdict(float)
    for it in mp_em_transito_chegando:
        mp_chegando_por_dia[(int(it["dia"]), it["mp"])] += float(it["qtd"])

    # Consumo diário de cada MP (em toneladas)
    consumo_diario_mp = {(d, mp): 0.0 for d in range(1, 6) for mp in ("MP1", "MP2", "MP3")}
    for dia in range(1, 6):
        for pa in ("PA1", "PA2", "PA3"):
            q = producao_diaria[dia][pa]
            for mp in ("MP1", "MP2", "MP3"):
                consumo_diario_mp[(dia, mp)] += q * cfg.BoM[pa][mp] / 1_000_000

    # ============ 6. PLANEJAR COMPRAS DE MP (para R atual + R+1) ============
    # MP necessária total - estoque inicial - em-trânsito-chegando
    em_transito_total = {mp: 0.0 for mp in ("MP1", "MP2", "MP3")}
    for (d, mp), q in mp_chegando_por_dia.items():
        em_transito_total[mp] += q

    mp_a_comprar = {}
    for mp in ("MP1", "MP2", "MP3"):
        falta = mp_consumida_ton[mp] - estoque_inicial_mp_ton.get(mp, 0.0) - em_transito_total[mp]
        mp_a_comprar[mp] = max(0.0, falta)

    if compras_mp_extra_para_r_mais_1:
        for mp, q in compras_mp_extra_para_r_mais_1.items():
            if q > 0:
                mp_a_comprar[mp] = mp_a_comprar.get(mp, 0.0) + q

    # Limita compras pra não estourar a capacidade do depósito ao fim da rodada
    # estoque_final = estoque_inicial + chegando + comprado - consumido
    for mp in ("MP1", "MP2", "MP3"):
        est_final_max = (estoque_inicial_mp_ton.get(mp, 0.0) + em_transito_total[mp]
                         + mp_a_comprar[mp] - mp_consumida_ton[mp])
        if est_final_max > cap_mp_ton[mp]:
            excedente = est_final_max - cap_mp_ton[mp]
            mp_a_comprar[mp] = max(0.0, mp_a_comprar[mp] - excedente)

    # Lead times fornecedores
    lt_fornec = {}
    for mp in ("MP1", "MP2", "MP3"):
        for forn, custo in cfg.fornecedores[mp]:
            lt = lead_dias(cfg, forn, fab_cidade, "Caminhão")
            lt_fornec[(mp, forn, "Caminhão")] = (lt, custo)

    # Gera transportes Fornecedor -> Fábrica.
    # Dia de partida tal que a MP chegue durante a rodada (sai dia_part, chega dia_part + lt;
    # precisa chegar até o dia em que consumimos / dia 5).
    sol_transp: List[Dict] = []

    # Para R atual: precisamos da MP em F1 ANTES do consumo. Simplifica: tenta dia 1.
    # Estoque MP por dia (simulando):
    estoque_mp_dia = {(0, mp): estoque_inicial_mp_ton.get(mp, 0.0) for mp in ("MP1", "MP2", "MP3")}
    for mp in ("MP1", "MP2", "MP3"):
        qtd_falta = mp_a_comprar[mp]
        if qtd_falta <= 0.1:
            continue
        # Fornecedor mais barato
        opcoes = sorted(cfg.fornecedores[mp], key=lambda x: x[1])
        forn_cidade, custo_ton = opcoes[0]
        lt = lead_dias(cfg, forn_cidade, fab_cidade, "Caminhão") or 99
        cap_cam = cfg.cap_modal_ton["Caminhão"]
        # Divide em viagens (cada cap = 24 ton). Distribui dia 1, 2, 3...
        n_viagens = math.ceil(qtd_falta / cap_cam)
        qtd_por_viagem = qtd_falta / n_viagens
        for i in range(n_viagens):
            dia_part = 1 + i  # uma viagem por dia consecutivamente
            if dia_part > 5:
                # Não cabe na rodada — manda no último dia mesmo (chega depois)
                dia_part = 5
            sol_transp.append({
                "Rodada": f"Rodada_{rodada_n}",
                "Origem": "Fornecedor",
                "Cidade": forn_cidade,
                "Dia da Coleta": f"Dia {dia_part}",
                "Modal": "Caminhão",
                "Tipo do Produto": mp,
                "Qtde": round(qtd_por_viagem, 2),
                "Destino": "Fábrica",
                "Cidade_Destino": fab_cidade,
            })

    # ============ 7. TRANSPORTES F1->CD e CD->Varejo (apenas OPs alocadas) ============
    # F1 -> CD: agrupa por (dia, cd_id, pa, modal_f1) e quebra em viagens de cap_modal
    fluxo_f1_cd: Dict[Tuple[int, str, str, str], int] = defaultdict(int)
    for r in rotas_op:
        if not r.get("alocada"):
            continue
        chave = (r["dia_producao"], r["cd_id"], r["pa"], r["modal_f1"])
        fluxo_f1_cd[chave] += int(r["qtd"])

    # Buffer F1 -> CD: vai pro CD mais perto. Modal preferido = Navio (cap maior, frete baixo).
    # Fallback: Caminhão se navio não tem rota; Avião só se nada mais cabe na rodada.
    if pa_proxima_rodada and buffer_alocado > 0:
        cd_perto = min(cds_info.items(),
                       key=lambda x: lead_dias(cfg, fab_cidade, x[1], "Caminhão") or 99)
        cd_id_p, cd_cid_p = cd_perto
        lt_nav = lead_dias(cfg, fab_cidade, cd_cid_p, "Navio")
        lt_cam = lead_dias(cfg, fab_cidade, cd_cid_p, "Caminhão")
        for dia in range(1, 6):
            q = producao_diaria[dia].get(pa_proxima_rodada, 0)
            q_ops = sum(r["qtd"] for r in rotas_op
                         if r.get("alocada") and r["pa"] == pa_proxima_rodada
                         and r["dia_producao"] == dia)
            qbuf = int(q - q_ops)
            if qbuf <= 0:
                continue
            # Escolhe modal: navio > cam > avião por # de viagens
            if lt_nav and dia + lt_nav <= 5:
                modal = "Navio"
            elif lt_cam and dia + lt_cam <= 5:
                modal = "Caminhão"
            else:
                modal = "Avião"
            fluxo_f1_cd[(dia, cd_id_p, pa_proxima_rodada, modal)] += qbuf

    # Converte fluxo_f1_cd em linhas
    for (dia, cd_id, pa, modal), qtd in sorted(fluxo_f1_cd.items()):
        cap_un = int(cfg.cap_modal_por_item[modal][pa])
        restante = qtd
        while restante > 0:
            q = min(restante, cap_un)
            sol_transp.append({
                "Rodada": f"Rodada_{rodada_n}",
                "Origem": "Fábrica",
                "Cidade": fab_cidade,
                "Dia da Coleta": f"Dia {dia}",
                "Modal": modal,
                "Tipo do Produto": pa,
                "Qtde": int(q),
                "Destino": "CD",
                "Cidade_Destino": cds_info[cd_id],
            })
            restante -= q

    # CD -> Varejo (apenas OPs alocadas)
    for r in rotas_op:
        if not r.get("alocada"):
            continue
        dia_envio_cd = r["dia_entrega"] - r["lt_cd"]
        cap_un = int(cfg.cap_modal_por_item[r["modal_cd"]][r["pa"]])
        restante = int(r["qtd"])
        while restante > 0:
            q = min(restante, cap_un)
            sol_transp.append({
                "Rodada": f"Rodada_{rodada_n}",
                "Origem": "CD",
                "Cidade": r["cd_cidade"],
                "Dia da Coleta": f"Dia {dia_envio_cd}",
                "Modal": r["modal_cd"],
                "Tipo do Produto": r["pa"],
                "Qtde": int(q),
                "Destino": "Varejista",
                "Cidade_Destino": r["cidade"],
            })
            restante -= q

    # ============ 8. DATAFRAMES FINAIS ============
    df_sol_transp = pd.DataFrame(sol_transp, columns=[
        "Rodada", "Origem", "Cidade", "Dia da Coleta", "Modal",
        "Tipo do Produto", "Qtde", "Destino", "Cidade_Destino"
    ])

    df_op_fabricas = pd.DataFrame([
        {"Dia": f"Dia {d}",
         "PA1": producao_diaria[d]["PA1"],
         "PA2": producao_diaria[d]["PA2"],
         "PA3": producao_diaria[d]["PA3"]}
        for d in range(1, 6)
    ])

    # ============ 9. RESUMO ============
    ops_atendidas = [r for r in rotas_op if r.get("alocada")]
    qtd_atendida = sum(int(r["qtd"]) for r in ops_atendidas)
    qtd_descartada = sum(int(d.get("qtd", 0)) for d in descartadas)
    custo_logistico = sum(custo_rota_pa(
        cfg, r["pa"], int(r["qtd"]), fab_cidade, r["cd_cidade"], r["cidade"],
        r["modal_f1"], r["modal_cd"]
    ) for r in ops_atendidas)

    resumo = {
        "rodada": rodada_n,
        "ops_total": len(ops_rodada),
        "ops_atendidas": len(ops_atendidas),
        "ops_descartadas": len(descartadas),
        "qtd_atendida": qtd_atendida,
        "qtd_descartada": qtd_descartada,
        "taxa_atendimento_pct": qtd_atendida / max(1, qtd_atendida + qtd_descartada) * 100,
        "producao_total_por_pa": total_producao,
        "buffer_pa_proxima_alocado": int(buffer_alocado),
        "mp_a_comprar_ton": mp_a_comprar,
        "mp_consumida_ton": mp_consumida_ton,
        "estoque_mp_final_ton": {
            mp: max(0, estoque_inicial_mp_ton.get(mp, 0.0)
                    + em_transito_total[mp] + mp_a_comprar[mp]
                    - mp_consumida_ton[mp])
            for mp in ("MP1", "MP2", "MP3")
        },
        "cap_mp_ton": cap_mp_ton,
        "min_usados_por_dia": {d: cap_min_dia - cap_restante[d] for d in range(1, 6)},
        "cap_min_dia": cap_min_dia,
        "rotas_op": rotas_op,
        "descartadas": descartadas,
        "custo_logistico_ops": custo_logistico,
        "n_transportes": len(sol_transp),
    }

    return {
        "df_sol_transp": df_sol_transp,
        "df_op_fabricas": df_op_fabricas,
        "resumo": resumo,
    }
