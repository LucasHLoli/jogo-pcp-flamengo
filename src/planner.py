"""Planner heurístico de 4 passos."""
from __future__ import annotations
import math
from typing import Dict, List, Tuple

from src.config import Config
from src.domain import (
    Estado, OP, OPDescartada, PlanoProducao, TarefaTransporte, TransitItem,
)


def _lead_time_dias(cfg: Config, origem: str, destino: str, modal: str) -> float:
    """Dias úteis de viagem (arredondado pra cima de 8h/dia)."""
    try:
        km = cfg.distancias[modal].at[origem, destino]
    except (KeyError, ValueError):
        return math.inf
    if km is None or (isinstance(km, float) and (km != km)):
        return math.inf
    if float(km) <= 0:
        return math.inf
    vel = {"Avião": 700, "Caminhão": 50, "Navio": 30}[modal]
    horas = float(km) / vel
    return max(1, math.ceil(horas / 8))


def passo1_entregas_cd_varejo(
    estado: Estado,
    ops: List[OP],
    cfg: Config,
    cds_info: Dict[str, str],
    rodada_n: int,
) -> Tuple[List[TarefaTransporte], List[OPDescartada]]:
    tarefas: List[TarefaTransporte] = []
    descartadas: List[OPDescartada] = []
    estoque_trab = {cd: dict(estado.estoque_pa_cd[cd]) for cd in cds_info}

    for op in ops:
        if op.rodada != rodada_n:
            continue
        candidatos = []
        for cd, cidade_cd in cds_info.items():
            lts = []
            for modal in ("Caminhão", "Navio", "Avião"):
                if modal == "Navio" and (cidade_cd, op.cidade) not in cfg.rotas_navio_validas:
                    continue
                lt = _lead_time_dias(cfg, cidade_cd, op.cidade, modal)
                if lt != math.inf:
                    lts.append(lt)
            if not lts:
                continue
            lt_min = min(lts)
            if lt_min > op.dia_entrega - 1:
                continue
            estoque_disp = estoque_trab[cd].get(op.pa, 0)
            if estoque_disp < op.qtd:
                continue
            candidatos.append((lt_min, -estoque_disp, cd, cidade_cd))

        if not candidatos:
            tem_estoque = any(
                estoque_trab[cd].get(op.pa, 0) >= op.qtd for cd in cds_info
            )
            motivo = "lead_time_inviavel" if tem_estoque else "sem_estoque_CD"
            descartadas.append(OPDescartada(op=op, motivo=motivo, rodada_descarte=rodada_n))
            continue

        candidatos.sort()
        lt_min, _, cd, cidade_cd = candidatos[0]
        estoque_trab[cd][op.pa] -= op.qtd
        janela = list(range(1, op.dia_entrega - lt_min + 1)) or [1]
        tarefas.append(TarefaTransporte(
            origem_cidade=cidade_cd, destino_cidade=op.cidade,
            item=op.pa, qtd=op.qtd, janela_dias=janela,
            rodada=rodada_n, motivo=f"OP_{op.cidade}_{op.pa}_d{op.dia_entrega}",
            origem_tipo="CD", destino_tipo="Varejista",
        ))
    return tarefas, descartadas


def passo2_reposicao_fabrica_cd(
    estado: Estado,
    forecast: Dict[Tuple[str, str], List[float]],
    cfg: Config,
    cds_info: Dict[str, str],
    cidades_por_cd: Dict[str, List[str]],
    saidas_cd: Dict[str, Dict[str, float]],
    rodada_n: int,
    fabrica_cidade: str = "Joinville",
    cap_pa_cd_frascos: Dict[str, Dict[str, int]] | None = None,
) -> Dict[str, Dict[str, float]]:
    necessidades: Dict[str, Dict[str, float]] = {cd: {} for cd in cds_info}
    for cd, cidade_cd in cds_info.items():
        lt_dias = _lead_time_dias(cfg, fabrica_cidade, cidade_cd, "Caminhão")
        if lt_dias == math.inf:
            lt_dias = _lead_time_dias(cfg, fabrica_cidade, cidade_cd, "Navio")
            if lt_dias == math.inf:
                lt_dias = _lead_time_dias(cfg, fabrica_cidade, cidade_cd, "Avião")
        lt_rodadas = max(1, math.ceil(lt_dias / 5))

        # Atenção: `_aplicar_chegadas` já moveu para o estoque tudo com rod_cheg <= rodada_n.
        # Aqui só contamos o que AINDA está em trânsito (rod_cheg > rodada_n) e chegará dentro
        # da janela de lead_time. Sem o filtro inferior haveria dupla contagem.
        chegadas_pa = {pa: 0.0 for pa in ("PA1", "PA2", "PA3")}
        for t in estado.transit:
            if t.destino_tipo == "CD" and t.destino_cidade == cidade_cd and t.item.startswith("PA"):
                if rodada_n < t.rod_cheg <= rodada_n + lt_rodadas:
                    chegadas_pa[t.item] = chegadas_pa.get(t.item, 0.0) + t.qtd

        for pa in ("PA1", "PA2", "PA3"):
            demanda_janela = 0.0
            for cidade in cidades_por_cd.get(cd, []):
                fc = forecast.get((cidade, pa), [0.0, 0.0, 0.0, 0.0])
                idx_a = min(lt_rodadas, len(fc) - 1)
                idx_b = min(lt_rodadas + 1, len(fc) - 1)
                demanda_janela += fc[idx_a] + (fc[idx_b] if idx_a != idx_b else 0)

            saida = saidas_cd.get(cd, {}).get(pa, 0.0)
            estoque_pos = estado.estoque_pa_cd[cd][pa] - saida + chegadas_pa[pa]
            necessidade_bruta = max(0.0, demanda_janela - estoque_pos)
            # Clipa pela capacidade livre no CD para não estourar (PA descarta se chega
            # ao CD sem espaço — melhor produzir menos do que descartar carga inteira).
            if cap_pa_cd_frascos and cd in cap_pa_cd_frascos:
                cap_livre = max(0.0, cap_pa_cd_frascos[cd][pa] - estoque_pos)
                necessidade_bruta = min(necessidade_bruta, cap_livre)
            necessidades[cd][pa] = necessidade_bruta
    return necessidades


def passo3_producao(
    necessidades: Dict[str, Dict[str, float]],
    cfg: Config,
    cds_info: Dict[str, str],
    rodada_n: int,
    fabrica: str = "F1",
    fabrica_cidade: str = "Joinville",
    maquinas: int = 7,
    turnos: int = 3,
) -> Tuple[List[PlanoProducao], List[TarefaTransporte]]:
    min_por_dia = maquinas * turnos * 8 * 60
    velocidades = cfg.velocidades

    total_por_pa: Dict[str, float] = {}
    for cd, d in necessidades.items():
        for pa, qtd in d.items():
            total_por_pa[pa] = total_por_pa.get(pa, 0.0) + qtd

    ordem_pa = sorted(total_por_pa.keys(),
                      key=lambda pa: -total_por_pa[pa] / velocidades[pa])
    capacidade_por_dia = [min_por_dia] * 5
    producao: Dict[int, Dict[str, int]] = {d: {} for d in range(1, 6)}

    for pa in ordem_pa:
        restante = total_por_pa[pa]
        for dia in range(1, 6):
            if restante <= 0:
                break
            cap_min = capacidade_por_dia[dia - 1]
            qtd_que_cabe = int(min(restante, cap_min * velocidades[pa]))
            if qtd_que_cabe <= 0:
                continue
            producao[dia][pa] = producao[dia].get(pa, 0) + qtd_que_cabe
            capacidade_por_dia[dia - 1] -= math.ceil(qtd_que_cabe / velocidades[pa])
            restante -= qtd_que_cabe

    planos: List[PlanoProducao] = []
    tarefas: List[TarefaTransporte] = []
    for dia in range(1, 6):
        for pa, qtd_total_dia in producao[dia].items():
            if qtd_total_dia <= 0:
                continue
            planos.append(PlanoProducao(rodada=rodada_n, fabrica=fabrica,
                                         dia=dia, pa=pa, qtd=qtd_total_dia))
            total_nec_pa = sum(necessidades[cd].get(pa, 0.0) for cd in cds_info)
            if total_nec_pa <= 0:
                continue
            for cd, cidade_cd in cds_info.items():
                fracao = necessidades[cd].get(pa, 0.0) / total_nec_pa
                qtd_cd = int(round(qtd_total_dia * fracao))
                if qtd_cd <= 0:
                    continue
                tarefas.append(TarefaTransporte(
                    origem_cidade=fabrica_cidade, destino_cidade=cidade_cd,
                    item=pa, qtd=qtd_cd, janela_dias=[dia],
                    rodada=rodada_n, motivo=f"reposição_{cd}_{pa}_d{dia}",
                    origem_tipo="Fábrica", destino_tipo="CD",
                ))
    return planos, tarefas


def passo4_compras_mp(
    planos_prod: List[PlanoProducao],
    estoque_inicial_mp: Dict[str, float],
    cfg: Config,
    cap_mp: Dict[str, float],
    rodada_n: int,
    fabrica_cidade: str,
    transit_atual: List[TransitItem],
) -> Tuple[List[TarefaTransporte], List[OPDescartada]]:
    consumo: Dict[int, Dict[str, float]] = {
        d: {"MP1": 0.0, "MP2": 0.0, "MP3": 0.0} for d in range(1, 6)
    }
    for p in planos_prod:
        for mp in ("MP1", "MP2", "MP3"):
            g = cfg.BoM[p.pa][mp]
            consumo[p.dia][mp] += p.qtd * g / 1_000_000

    chegadas_pre: Dict[int, Dict[str, float]] = {
        d: {"MP1": 0.0, "MP2": 0.0, "MP3": 0.0} for d in range(1, 6)
    }
    for t in transit_atual:
        if t.rod_cheg == rodada_n and t.item.startswith("MP") and t.destino_tipo == "Fábrica":
            chegadas_pre[t.dia_cheg][t.item] = chegadas_pre[t.dia_cheg].get(t.item, 0.0) + t.qtd

    tarefas: List[TarefaTransporte] = []
    descartadas: List[OPDescartada] = []

    for mp in ("MP1", "MP2", "MP3"):
        fornecedor, _custo = min(cfg.fornecedores[mp], key=lambda x: x[1])
        lt_min = _lead_time_dias(cfg, fornecedor, fabrica_cidade, "Caminhão")
        if lt_min == math.inf:
            continue

        estoque_atual = estoque_inicial_mp.get(mp, 0.0)
        for dia in range(1, 6):
            estoque_atual += chegadas_pre[dia][mp]
            falta = consumo[dia][mp] - estoque_atual
            if falta > 1e-6:
                dia_partida_raw = dia - int(lt_min)
                if dia_partida_raw < 1:
                    # LT maior que janela: registra como inviável mas envia ASAP
                    descartadas.append(OPDescartada(
                        op=OP(rodada=rodada_n, cidade=fornecedor, pa=mp,
                              qtd=int(math.ceil(falta * 1000)), dia_entrega=dia),
                        motivo="lead_time_inviavel_mp",
                        rodada_descarte=rodada_n,
                    ))
                    dia_partida = 1
                else:
                    dia_partida = dia_partida_raw
                qtd_compra = min(falta, cap_mp[mp] - estoque_atual)
                if qtd_compra <= 0:
                    descartadas.append(OPDescartada(
                        op=OP(rodada=rodada_n, cidade=fornecedor, pa=mp,
                              qtd=int(math.ceil(falta * 1000)), dia_entrega=dia),
                        motivo="cap_mp_excedida",
                        rodada_descarte=rodada_n,
                    ))
                    estoque_atual -= consumo[dia][mp]
                    continue
                tarefas.append(TarefaTransporte(
                    origem_cidade=fornecedor, destino_cidade=fabrica_cidade,
                    item=mp, qtd=qtd_compra, janela_dias=[dia_partida],
                    rodada=rodada_n, motivo=f"compra_{mp}_d{dia}",
                    origem_tipo="Fornecedor", destino_tipo="Fábrica",
                ))
                estoque_atual += qtd_compra
            estoque_atual -= consumo[dia][mp]
    return tarefas, descartadas
