"""Planner manual rodada-a-rodada do Jogo PCP 2.

Diferenças do planner.py original:
- Não exige estoque PA pré-existente no CD para atender OPs (considera produção
  + transporte dentro da rodada).
- Usa o forecast HW da PRÓXIMA rodada para definir buffer de PA a estocar nos CDs.
- Retorna DataFrames prontos no formato exato das abas SOL_TRANSP e OP_FABRICAS
  do FLAMENGO.xlsm (sem precisar escrever no arquivo).
"""
from __future__ import annotations
import math
from typing import Any, Dict, List, Tuple

import pandas as pd

from src.config import Config


VEL_MODAL_KMH = {"Avião": 700, "Caminhão": 50, "Navio": 30}
HORAS_UTEIS_DIA = 8


def _lead_dias(cfg: Config, origem: str, destino: str, modal: str) -> float:
    """Lead time em dias úteis (arredondado para cima de 8h/dia)."""
    try:
        km = cfg.distancias[modal].at[origem, destino]
    except (KeyError, ValueError):
        return math.inf
    if km is None or (isinstance(km, float) and km != km) or float(km) <= 0:
        return math.inf
    horas = float(km) / VEL_MODAL_KMH[modal]
    return max(1, math.ceil(horas / HORAS_UTEIS_DIA))


def _melhor_rota_cd_varejo(
    cfg: Config, cd_cidade: str, varejo: str, dias_disponiveis: int,
    estrategia: str = "balanceado",
) -> Tuple[str, int] | None:
    """Acha o modal mais barato CD→Varejo que cabe em `dias_disponiveis`."""
    modais = ("Caminhão", "Navio", "Avião") if estrategia != "conservador" else ("Caminhão", "Navio")
    candidatos = []
    for modal in modais:
        if modal == "Navio" and (cd_cidade, varejo) not in cfg.rotas_navio_validas:
            continue
        lt = _lead_dias(cfg, cd_cidade, varejo, modal)
        if lt <= dias_disponiveis:
            ordem = {"Caminhão": 0, "Navio": 1, "Avião": 2}[modal]
            candidatos.append((ordem, lt, modal))
    if not candidatos:
        return None
    candidatos.sort()
    _, lt, modal = candidatos[0]
    return modal, lt


def _melhor_rota_f1_cd(
    cfg: Config, fabrica_cidade: str, cd_cidade: str, dias_disponiveis: int
) -> Tuple[str, int] | None:
    """F1→CD: prefere caminhão > navio > avião dentro da janela."""
    candidatos = []
    for modal in ("Caminhão", "Navio", "Avião"):
        if modal == "Navio" and (fabrica_cidade, cd_cidade) not in cfg.rotas_navio_validas:
            continue
        lt = _lead_dias(cfg, fabrica_cidade, cd_cidade, modal)
        if lt <= dias_disponiveis:
            ordem = {"Caminhão": 0, "Navio": 1, "Avião": 2}[modal]
            candidatos.append((ordem, lt, modal))
    if not candidatos:
        return None
    candidatos.sort()
    _, lt, modal = candidatos[0]
    return modal, lt


def _viabilidade_op(
    cfg: Config, op: Dict, fabrica_cidade: str, cds_info: Dict[str, str],
    estrategia: str = "balanceado",
) -> Tuple[str, str, str, int, int] | None:
    """Avalia melhor rota F1→CD→Varejo dentro do dia_entrega da OP.

    Retorna: (cd_id, cd_cidade, modal_f1_cd, modal_cd_varejo, dia_producao_max, dia_envio_cd_varejo)
    ou None se inviável.

    Regra: dia_producao + lead_f1_cd + lead_cd_varejo ≤ dia_entrega.

    estrategia:
      - 'conservador': proíbe avião em qualquer perna.
      - 'balanceado': avião só F1→CD se caminhão+navio falham; depois CD→Varejo caminhão preferido.
      - 'agressivo': avião livre.
      - 'smart': avião só pra OPs urgentes (dia_entrega ≤ 3); caminhão pra dia ≥ 4.
                 Reduz consumo do cap avião (172 ton/sem) e total trips (220/sem).
    """
    dia_entrega = int(op["dia_entrega"])
    # Estratégia:
    #  - conservador: nada de avião em qualquer perna (zero descarte por frete alto)
    #  - balanceado: avião proibido em F1→CD (perna mais cara/longa); permitido CD→Varejo
    #  - agressivo: avião livre em qualquer perna
    #  - smart: agressivo só pra urgentes (dia ≤ 3), balanceado pro resto
    if estrategia == "smart":
        if dia_entrega <= 3:
            # Urgente: avião liberado em qualquer perna
            modais_f1_lista = ("Caminhão", "Navio", "Avião")
            estrat_cd_var = "agressivo"
        else:
            # Dia 4-5: bloqueia avião F1→CD (perna longa cara) mas mantém CD→Varejo
            # avião (NE precisa). Poupa cap avião na perna pesada (F1→CD).
            modais_f1_lista = ("Caminhão", "Navio")
            estrat_cd_var = "agressivo"
    elif estrategia == "conservador":
        modais_f1_lista = ("Caminhão", "Navio")
        estrat_cd_var = "conservador"
    elif estrategia == "balanceado":
        modais_f1_lista = ("Caminhão", "Navio")
        estrat_cd_var = "agressivo"  # libera avião apenas CD→Varejo
    else:  # agressivo
        modais_f1_lista = ("Caminhão", "Navio", "Avião")
        estrat_cd_var = "agressivo"

    melhor = None
    for cd_id, cd_cidade in cds_info.items():
        for modal_f1 in modais_f1_lista:
            if modal_f1 == "Navio" and (fabrica_cidade, cd_cidade) not in cfg.rotas_navio_validas:
                continue
            lt_f1 = _lead_dias(cfg, fabrica_cidade, cd_cidade, modal_f1)
            if lt_f1 == math.inf:
                continue
            dias_restantes = dia_entrega - lt_f1
            if dias_restantes < 1:
                continue
            rota_cd = _melhor_rota_cd_varejo(cfg, cd_cidade, op["cidade"], dias_restantes - 1, estrategia=estrat_cd_var)
            if rota_cd is None:
                continue
            modal_cd, lt_cd = rota_cd
            dia_producao_max = dia_entrega - lt_f1 - lt_cd
            if dia_producao_max < 1:
                continue
            dia_envio_cd = dia_entrega - lt_cd
            custo = {"Caminhão": 1, "Navio": 2, "Avião": 5}[modal_f1] + {"Caminhão": 1, "Navio": 2, "Avião": 5}[modal_cd]
            cand_score = (-dia_producao_max, custo)
            cand = (cand_score, cd_id, cd_cidade, modal_f1, modal_cd, dia_producao_max, dia_envio_cd)
            if melhor is None or cand[0] < melhor[0]:
                melhor = cand
    if melhor is None:
        return None
    _, cd_id, cd_cidade, modal_f1, modal_cd, dia_prod, dia_envio_cd = melhor
    return cd_id, cd_cidade, modal_f1, modal_cd, dia_prod, dia_envio_cd


def planejar_rodada(
    *,
    rodada_n: int,
    ops_rodada: List[Dict],
    forecast_proxima: Dict[Tuple[str, str], float],
    estado_inicial_mp_ton: Dict[str, float],
    estado_inicial_pa_cd: Dict[str, Dict[str, int]],
    cfg: Config,
    instalacoes: Dict,
    buffer_pct: float = 0.5,
    fabrica_cidade: str = "Joinville",
    fabrica_principal: str = "F1",
    cds_info: Dict[str, str] | None = None,
    estrategia: str = "balanceado",
    compras_mp_extra: Dict[str, float] | None = None,
    buffer_override: Dict[str, int] | None = None,
) -> Dict[str, Any]:
    """Planeja uma rodada.

    Args:
        estrategia: política de transporte.
            - 'conservador': SÓ caminhão/navio. Descarta OPs que precisam avião.
                             Bom pra rodadas longas (foco VPL, baixo frete).
            - 'balanceado' (default): caminhão pra Sudeste/Sul; avião só pra NE/Norte
                                       quando lead caminhão for inviável.
            - 'agressivo': permite avião pra qualquer OP urgente.
    """
    """Planeja a rodada inteira: atende OPs viáveis + estoca buffer para próxima rodada.

    Args:
        rodada_n: número da rodada atual.
        ops_rodada: lista de dicts {cidade, pa, qtd, dia_entrega}.
        forecast_proxima: previsão da demanda da próxima rodada {(cidade, pa): qtd}.
        estado_inicial_mp_ton: estoque atual de MP em F1 {"MP1": ton, ...}.
        estado_inicial_pa_cd: estoque atual de PA em cada CD {"CD1": {"PA1": un, ...}, ...}.
        cfg: Config carregado.
        instalacoes: dict de ler_instalacoes.
        buffer_pct: fração da forecast da próxima rodada a estocar como buffer (0..1).
        cds_info: mapping {"CD1": "São Luís", ...}.

    Returns:
        Dict com:
            - 'df_sol_transp': DataFrame no formato da aba SOL_TRANSP
            - 'df_op_fabricas': DataFrame no formato da aba OP_FABRICAS
            - 'resumo': dict com {ops_atendidas, ops_descartadas, total_producao, ...}
    """
    if cds_info is None:
        cds_info = {cd: d["cidade"] for cd, d in instalacoes["cds"].items() if d.get("cidade")}

    f1 = instalacoes["fabricas"][fabrica_principal]
    maquinas = int(f1["maquinas"])
    turnos = int(f1["turnos"])
    cap_min_dia = maquinas * turnos * cfg.capacidades["horas_por_turno"] * 60

    # ============ 1. AVALIA VIABILIDADE DE CADA OP ============
    entregas: List[Dict] = []   # OPs atendíveis com rota planejada
    descartadas: List[Dict] = []  # OPs inviáveis
    estoque_trab_cd = {cd: dict(estado_inicial_pa_cd.get(cd, {})) for cd in cds_info}

    for op in ops_rodada:
        # Primeiro tenta atender do estoque já existente no CD
        atendida_estoque = False
        for cd_id, cd_cidade in cds_info.items():
            disp = estoque_trab_cd[cd_id].get(op["pa"], 0)
            if disp >= int(op["qtd"]):
                rota = _melhor_rota_cd_varejo(cfg, cd_cidade, op["cidade"], op["dia_entrega"] - 1, estrategia=estrategia)
                if rota is not None:
                    modal, lt = rota
                    estoque_trab_cd[cd_id][op["pa"]] = disp - int(op["qtd"])
                    entregas.append({
                        "cidade": op["cidade"],
                        "pa": op["pa"],
                        "qtd": int(op["qtd"]),
                        "dia_entrega": int(op["dia_entrega"]),
                        "origem": "estoque_cd",
                        "cd_id": cd_id,
                        "cd_cidade": cd_cidade,
                        "modal_cd_varejo": modal,
                        "dia_envio_cd": op["dia_entrega"] - lt,
                        "modal_f1_cd": None,
                        "dia_producao_max": None,
                    })
                    atendida_estoque = True
                    break
        if atendida_estoque:
            continue

        # Senão, tenta produção urgente nesta rodada
        viab = _viabilidade_op(cfg, op, fabrica_cidade, cds_info, estrategia=estrategia)
        if viab is None:
            descartadas.append({**op, "motivo": "lead_inviavel_ou_sem_rota"})
            continue
        cd_id, cd_cidade, modal_f1, modal_cd, dia_prod, dia_envio_cd = viab
        entregas.append({
            "cidade": op["cidade"],
            "pa": op["pa"],
            "qtd": int(op["qtd"]),
            "dia_entrega": int(op["dia_entrega"]),
            "origem": "producao_urgente",
            "cd_id": cd_id,
            "cd_cidade": cd_cidade,
            "modal_cd_varejo": modal_cd,
            "dia_envio_cd": dia_envio_cd,
            "modal_f1_cd": modal_f1,
            "dia_producao_max": dia_prod,
        })

    # ============ 2. CALCULA PRODUÇÃO TOTAL (R2 + buffer R3) ============
    pa_atender = {pa: 0 for pa in ("PA1", "PA2", "PA3")}
    pas_com_op = set()
    for e in entregas:
        if e["origem"] == "producao_urgente":
            pa_atender[e["pa"]] += e["qtd"]
            pas_com_op.add(e["pa"])

    # Buffer para próxima rodada: SÓ para PAs que tiveram OP nesta rodada
    # (evita produzir milhares de PA2/PA3 sem demanda atual confirmada).
    pa_buffer = {pa: 0 for pa in ("PA1", "PA2", "PA3")}
    if pas_com_op:
        for (cidade, pa), qtd_prev in forecast_proxima.items():
            if pa in pas_com_op:
                pa_buffer[pa] += int(qtd_prev * buffer_pct)
    # buffer_override: força produção de PAs específicos independente de pas_com_op
    # (útil pra estocar PA2 quando R3 só tem PA3 mas HW prevê PA2 em R4).
    if buffer_override:
        for pa, qtd in buffer_override.items():
            if qtd > 0:
                pa_buffer[pa] = max(pa_buffer[pa], int(qtd))
                pas_com_op.add(pa)  # garante que vai entrar nos cálculos de MP/produção

    # Limita produção total pela MP disponível + MP comprável (chega na rodada)
    cap_mp_ton = {
        mp: (instalacoes["fabricas"][fabrica_principal]["area_mp"][mp]
             * cfg.capacidades["pe_direito_deposito_m"]
             * cfg.densidades_mp[mp])
        for mp in ("MP1", "MP2", "MP3")
    }
    # MP máxima utilizável na rodada = estoque atual + cap_mp (se conseguir comprar caminhão cheio)
    # Conservador: assume que dá pra comprar 2 caminhões de cada MP (48 ton) chegando nos primeiros 2 dias
    mp_max_disponivel = {
        mp: estado_inicial_mp_ton.get(mp, 0) + min(48, cap_mp_ton[mp] - estado_inicial_mp_ton.get(mp, 0))
        for mp in ("MP1", "MP2", "MP3")
    }
    # Quantidade max de cada PA possível dado MP disponível
    max_pa_por_mp = {pa: float("inf") for pa in ("PA1", "PA2", "PA3")}
    for pa in ("PA1", "PA2", "PA3"):
        if pa not in pas_com_op and pa_buffer[pa] == 0:
            max_pa_por_mp[pa] = 0
            continue
        for mp in ("MP1", "MP2", "MP3"):
            g = cfg.BoM[pa][mp]
            if g <= 0:
                continue
            # MP disponível para esse PA (heurística simples — divide igualmente entre PAs com OP)
            mp_disp_esse_pa = mp_max_disponivel[mp] / max(1, len(pas_com_op))
            max_pa = (mp_disp_esse_pa * 1_000_000) / g
            max_pa_por_mp[pa] = min(max_pa_por_mp[pa], max_pa)

    # Aplica o limite no buffer (não no atender — atender é prioridade)
    for pa in ("PA1", "PA2", "PA3"):
        limite_buffer = max(0, int(max_pa_por_mp[pa]) - pa_atender[pa])
        if pa_buffer[pa] > limite_buffer:
            pa_buffer[pa] = limite_buffer

    total_producao = {pa: pa_atender[pa] + pa_buffer[pa] for pa in pa_atender}

    # ============ 3. ALOCA PRODUÇÃO POR DIA ============
    # Restrição: minutos por dia ≤ cap_min_dia
    velocidades = cfg.velocidades
    capacidade_restante = [cap_min_dia] * 5
    producao_diaria: Dict[int, Dict[str, int]] = {d: {"PA1": 0, "PA2": 0, "PA3": 0} for d in range(1, 6)}

    # Aloca produção das entregas urgentes:
    # - Ordena por dia_producao_max ASC (mais urgentes primeiro)
    # - Para cada uma, aloca do dia_max para baixo (= dia mais tarde possível primeiro).
    #   Isso porque dia_max = dia que MAIS cedo precisa estar pronto. Dias maiores que dia_max
    #   não servem (PA chegaria depois da entrega). Então aloca do dia_max para o Dia 1.
    # - As OPs MAIS URGENTES (dia_max pequeno) competem por Dia 1; alocá-las primeiro garante
    #   que pegam o Dia 1 antes das menos urgentes (que ainda podem usar dias maiores).
    # Ordena: dia_producao_max ASC (urgentes primeiro), qtd DESC (grandes primeiro)
    entregas_urgentes = sorted(
        [e for e in entregas if e["origem"] == "producao_urgente"],
        key=lambda e: (int(e["dia_producao_max"]), -int(e["qtd"])),
    )
    for e in entregas_urgentes:
        pa = e["pa"]
        qtd_restante = e["qtd"]
        vel = velocidades[pa]
        # Aloca do dia_max para o Dia 1 (cobrindo dias permitidos pra essa entrega)
        for dia in range(int(e["dia_producao_max"]), 0, -1):
            if qtd_restante <= 0:
                break
            min_disp = capacidade_restante[dia - 1]
            qtd_cabe = min(qtd_restante, min_disp * vel)
            if qtd_cabe <= 0:
                continue
            producao_diaria[dia][pa] += int(qtd_cabe)
            capacidade_restante[dia - 1] -= math.ceil(qtd_cabe / vel)
            qtd_restante -= qtd_cabe
        if qtd_restante > 0:
            descartadas.append({"cidade": e["cidade"], "pa": e["pa"], "qtd": e["qtd"],
                                "dia_entrega": e["dia_entrega"], "motivo": "sem_capacidade_producao"})
            e["origem"] = "descartada"

    # Agora distribui o BUFFER nas capacidades restantes
    # PA1 primeiro (maior valor unitário), depois PA2, depois PA3
    for pa in ("PA1", "PA2", "PA3"):
        qtd_restante = pa_buffer[pa]
        vel = velocidades[pa]
        for dia in range(1, 6):
            if qtd_restante <= 0:
                break
            min_disp = capacidade_restante[dia - 1]
            qtd_cabe = min(qtd_restante, min_disp * vel)
            if qtd_cabe <= 0:
                continue
            producao_diaria[dia][pa] += int(qtd_cabe)
            capacidade_restante[dia - 1] -= math.ceil(qtd_cabe / vel)
            qtd_restante -= qtd_cabe
        pa_buffer[pa] -= qtd_restante  # ajusta o que efetivamente coube

    # ============ 4. PLANEJA TRANSPORTES F1→CD ============
    # Para cada dia, agrupar produção por (CD, PA) baseado em qual CD vai atender
    # Para o buffer, dividir 50/50 entre CD1 e CD2 (configurável)
    sol_transp: List[Dict] = []

    # 4a. Transportes F1→CD para ENTREGAS urgentes (cada entrega tem CD definido)
    # Acumula por (dia_producao, CD, PA, modal_f1)
    fluxo_f1_cd: Dict[Tuple[int, str, str, str], int] = {}
    for e in entregas:
        if e["origem"] != "producao_urgente":
            continue
        # Encontrar em quais dias a produção dessa entrega ocorre
        # (precisamos reconstituir, pois a produção foi distribuída)
        # Aproximação: o transporte sai no dia_producao_max - lt_f1_cd
        modal_f1 = e["modal_f1_cd"]
        lt_f1 = int(_lead_dias(cfg, fabrica_cidade, e["cd_cidade"], modal_f1))
        dia_partida = max(1, e["dia_envio_cd"] - lt_f1)
        chave = (dia_partida, e["cd_id"], e["pa"], modal_f1)
        fluxo_f1_cd[chave] = fluxo_f1_cd.get(chave, 0) + e["qtd"]

    # 4b. Transportes F1→CD para BUFFER (dividir entre CDs, modal preferido caminhão)
    cds_list = list(cds_info.items())
    if len(cds_list) >= 2:
        frac_cds = [0.6, 0.4]  # Santos pega mais (mais perto)
    else:
        frac_cds = [1.0]
    for pa in ("PA1", "PA2", "PA3"):
        qtd_buffer = pa_buffer[pa]
        if qtd_buffer <= 0:
            continue
        for (cd_id, cd_cidade), frac in zip(cds_list, frac_cds):
            qtd_cd = int(qtd_buffer * frac)
            if qtd_cd <= 0:
                continue
            rota = _melhor_rota_f1_cd(cfg, fabrica_cidade, cd_cidade, dias_disponiveis=5)
            if rota is None:
                continue
            modal_f1, lt_f1 = rota
            # Distribuir o envio do buffer pelos dias 1-3 (chega ainda na rodada)
            qtd_por_dia = qtd_cd // 3
            for dia_part in (1, 2, 3):
                if qtd_por_dia <= 0:
                    continue
                chave = (dia_part, cd_id, pa, modal_f1)
                fluxo_f1_cd[chave] = fluxo_f1_cd.get(chave, 0) + qtd_por_dia

    # Converte fluxo_f1_cd em linhas SOL_TRANSP, respeitando cap modal por viagem
    for (dia, cd_id, pa, modal), qtd_total in sorted(fluxo_f1_cd.items()):
        cap_modal = cfg.cap_modal_por_item[modal][pa]
        qtd_restante = int(qtd_total)
        while qtd_restante > 0:
            qtd_viagem = min(qtd_restante, int(cap_modal))
            sol_transp.append({
                "Rodada": f"Rodada_{rodada_n}",
                "Origem": "Fábrica",
                "Cidade": fabrica_cidade,
                "Dia da Coleta": f"Dia {dia}",
                "Modal": modal,
                "Tipo do Produto": pa,
                "Qtde": qtd_viagem,
                "Destino": "CD",
                "Cidade_Destino": cds_info[cd_id],
            })
            qtd_restante -= qtd_viagem

    # 4c. Transportes CD→Varejo (apenas entregas atendidas)
    for e in entregas:
        if e["origem"] == "descartada":
            continue
        cap_modal = cfg.cap_modal_por_item[e["modal_cd_varejo"]][e["pa"]]
        qtd_restante = int(e["qtd"])
        while qtd_restante > 0:
            qtd_viagem = min(qtd_restante, int(cap_modal))
            sol_transp.append({
                "Rodada": f"Rodada_{rodada_n}",
                "Origem": "CD",
                "Cidade": e["cd_cidade"],
                "Dia da Coleta": f"Dia {int(e['dia_envio_cd'])}",
                "Modal": e["modal_cd_varejo"],
                "Tipo do Produto": e["pa"],
                "Qtde": qtd_viagem,
                "Destino": "Varejista",
                "Cidade_Destino": e["cidade"],
            })
            qtd_restante -= qtd_viagem

    # ============ 5. COMPRAS DE MP ============
    # Necessidade total: produção total × BoM
    mp_necessaria = {"MP1": 0.0, "MP2": 0.0, "MP3": 0.0}
    for pa, qtd in total_producao.items():
        for mp in ("MP1", "MP2", "MP3"):
            g = cfg.BoM[pa][mp]
            mp_necessaria[mp] += qtd * g / 1_000_000  # toneladas

    mp_comprar = {mp: max(0, mp_necessaria[mp] - estado_inicial_mp_ton.get(mp, 0)) for mp in mp_necessaria}

    # Buffer flexível: compras extras pra próxima rodada (preparação PA2/PA3)
    # Respeita cap MP da fábrica para não descartar excesso na chegada.
    cap_mp_f1 = {
        mp: (instalacoes["fabricas"][fabrica_principal]["area_mp"][mp]
             * cfg.capacidades["pe_direito_deposito_m"]
             * cfg.densidades_mp[mp])
        for mp in ("MP1", "MP2", "MP3")
    }
    if compras_mp_extra:
        for mp, qtd_extra in compras_mp_extra.items():
            if qtd_extra <= 0:
                continue
            estoque_apos_consumo = estado_inicial_mp_ton.get(mp, 0) - mp_necessaria[mp] + mp_comprar[mp]
            cap_livre = cap_mp_f1[mp] - estoque_apos_consumo
            extra_efetivo = min(qtd_extra, cap_livre)
            if extra_efetivo > 0:
                mp_comprar[mp] += extra_efetivo

    # Gera ordens de compra (fornecedor mais barato, lead-time-aware)
    for mp, qtd_ton in mp_comprar.items():
        if qtd_ton <= 0:
            continue
        # Fornecedor mais barato
        fornecedor_cidade, _custo = min(cfg.fornecedores[mp], key=lambda x: x[1])
        # Modal preferencial: caminhão
        lt = _lead_dias(cfg, fornecedor_cidade, fabrica_cidade, "Caminhão")
        cap_cam = cfg.cap_modal_por_item["Caminhão"][mp]  # ton
        # Compra Dia 1 e distribui caminhões cheios
        qtd_restante = qtd_ton
        dia_partida = 1
        while qtd_restante > 0 and dia_partida <= 5:
            qtd_viagem = min(qtd_restante, cap_cam)
            sol_transp.append({
                "Rodada": f"Rodada_{rodada_n}",
                "Origem": "Fornecedor",
                "Cidade": fornecedor_cidade,
                "Dia da Coleta": f"Dia {dia_partida}",
                "Modal": "Caminhão",
                "Tipo do Produto": mp,
                "Qtde": round(qtd_viagem, 1),
                "Destino": "Fábrica",
                "Cidade_Destino": fabrica_cidade,
            })
            qtd_restante -= qtd_viagem
            dia_partida += 1  # uma viagem por dia pra não saturar

    # ============ 6. MONTA DATAFRAMES FINAIS ============
    df_sol_transp = pd.DataFrame(sol_transp, columns=[
        "Rodada", "Origem", "Cidade", "Dia da Coleta", "Modal",
        "Tipo do Produto", "Qtde", "Destino", "Cidade_Destino"
    ])

    op_fabricas_rows = []
    for dia in range(1, 6):
        op_fabricas_rows.append({
            "Dia": f"Dia {dia}",
            "PA1": producao_diaria[dia]["PA1"],
            "PA2": producao_diaria[dia]["PA2"],
            "PA3": producao_diaria[dia]["PA3"],
        })
    df_op_fabricas = pd.DataFrame(op_fabricas_rows)

    # ============ 7. RESUMO ============
    qtd_atendida = sum(e["qtd"] for e in entregas if e["origem"] != "descartada")
    qtd_descartada = sum(d.get("qtd", 0) for d in descartadas)
    resumo = {
        "rodada": rodada_n,
        "ops_total": len(ops_rodada),
        "ops_atendidas": len([e for e in entregas if e["origem"] != "descartada"]),
        "ops_descartadas": len(descartadas),
        "qtd_atendida": qtd_atendida,
        "qtd_descartada": qtd_descartada,
        "taxa_atendimento_pct": qtd_atendida / max(1, qtd_atendida + qtd_descartada) * 100,
        "producao_total_por_pa": total_producao,
        "buffer_acumulado_pa": pa_buffer,
        "mp_a_comprar_ton": mp_comprar,
        "minutos_usados_por_dia": [cap_min_dia - capacidade_restante[d - 1] for d in range(1, 6)],
        "minutos_max_por_dia": cap_min_dia,
        "descartadas": descartadas,
    }

    return {
        "df_sol_transp": df_sol_transp,
        "df_op_fabricas": df_op_fabricas,
        "resumo": resumo,
    }


def forecast_proxima_rodada_via_hw(rodada_n_atual: int, base_dir) -> Dict[Tuple[str, str], float]:
    """Carrega modelos HW e retorna previsão da próxima rodada por (cidade, PA)."""
    from pathlib import Path
    from src.forecast import (
        treinar_inicial, carregar_modelos, salvar_modelos, prever,
    )
    base_dir = Path(base_dir)
    hw_path = base_dir / "estado" / "hw_models.json"
    hist_path = base_dir / "estado" / "historico_demanda_ampliado.parquet"

    if not hist_path.exists():
        hist_raw = pd.read_parquet(base_dir / "data" / "demanda_long.parquet")
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

    # Horizonte: previsão da próxima rodada = índice 0 (h=1)
    fc = prever(modelos, horizonte=1)
    return {k: v[0] for k, v in fc.items()}
