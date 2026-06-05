"""Indicadores operacionais e financeiros — DRE + IND + VPL.

Espelha o que está em IND_FLAMENGO.pdf e DRE_FLAMENGO.pdf do prof, calculado
a partir dos planos da rodada e do estado.
"""
from __future__ import annotations
import math
from typing import Any, Dict, List

import pandas as pd

from src.config import Config


# Custos estruturais por rodada (do DRE real R1) — separados por categoria.
CUSTO_PARCELA_TERRENOS    = 506_968.0
CUSTO_PARCELA_MAQUINAS    = 415_567.0
CUSTO_PARCELA_CONTRATACAO = 84.0
CUSTO_MANUT_FABRICAS      = 1_313.0
CUSTO_SALARIO_OPERARIOS   = 450.0
CUSTO_PRODUCAO            = 172_086.0  # água + EE + outras op
CUSTO_MANUT_CDS           = 26_683.0
CUSTO_CARREG_MP           = 5_410.0    # carregamento de estoque MP padrão
CUSTO_ESTRUTURAL_TOTAL    = (
    CUSTO_PARCELA_TERRENOS + CUSTO_PARCELA_MAQUINAS + CUSTO_PARCELA_CONTRATACAO
    + CUSTO_MANUT_FABRICAS + CUSTO_SALARIO_OPERARIOS + CUSTO_PRODUCAO
    + CUSTO_MANUT_CDS + CUSTO_CARREG_MP
)  # = R$ 1.128.561

# Taxa de desconto mensal para VPL (briefing usa 3% para máquinas, 1.5% para terreno).
# Usamos 3% a.m. = ~0.75% por rodada (4 rodadas/mês) como custo de oportunidade.
TAXA_DESCONTO_POR_RODADA = 0.0075


def _peso_ton_modal(modal: str, item: str, qtd: float, cfg: Config) -> float:
    """Calcula peso transportado em toneladas."""
    if item.startswith("MP"):
        return float(qtd)  # MP já em ton
    # PA em frascos → ton
    return float(qtd) * cfg.peso_un_ton[item]


def _custo_viagem(modal: str, dist_km: float, qtd: float, item: str, cfg: Config) -> float:
    """Custo de uma viagem — regra oficial calibrada vs DRE real R3:
    ≥80% paga frete-viagem cheio; <80% paga frete-peso puro. Sem CT-e/doc
    nem meia-viagem fixa (descartados por bater com o frete realizado)."""
    if dist_km is None or dist_km <= 0:
        return 0.0
    cap_modal_ton = cfg.cap_modal_ton[modal]
    peso_ton = _peso_ton_modal(modal, item, qtd, cfg)
    ocupacao = peso_ton / cap_modal_ton if cap_modal_ton > 0 else 0.0
    if ocupacao >= 0.8:
        return cfg.frete_viagem[modal] * dist_km
    return cfg.frete_peso[modal] * dist_km * peso_ton


def calcular_dre_e_ind(
    rodada_n: int,
    df_sol_transp: pd.DataFrame,
    df_op_fabricas: pd.DataFrame,
    qtd_atendida_por_pa: Dict[str, int],
    precos: Dict[str, float],
    estoque_pa_final: Dict[str, Dict[str, int]],
    estoque_mp_final: Dict[str, float],
    cfg: Config,
    instalacoes: Dict,
    historico_resultados: List[float] | None = None,
) -> Dict[str, Any]:
    """Retorna dict com DRE da rodada, indicadores operacionais e VPL.

    Args:
        rodada_n: número da rodada.
        df_sol_transp: DataFrame de transportes (colunas: Origem, Cidade, Modal, Tipo do Produto, Qtde, Cidade_Destino).
        df_op_fabricas: DataFrame de produção (colunas: Dia, PA1, PA2, PA3).
        qtd_atendida_por_pa: {PA1: 267080, PA2: 0, PA3: 0} — frascos efetivamente entregues.
        precos: preços de mercado da rodada (R$/frasco).
        estoque_pa_final: estoque PA nos CDs no fim da rodada.
        estoque_mp_final: estoque MP em F1 no fim da rodada (ton).
        cfg: Config.
        instalacoes: instalações.
        historico_resultados: lista de resultados líquidos das rodadas anteriores (R1, R2, ...).
            Se None, assume só esta rodada. Usado para calcular VPL acumulado.

    Returns:
        Dict com 'dre', 'ind', 'vpl'.
    """
    # =========== RECEITA ===========
    receita_por_pa = {
        pa: int(qtd_atendida_por_pa.get(pa, 0)) * float(precos.get(pa, 0.0))
        for pa in ("PA1", "PA2", "PA3")
    }
    receita_total = sum(receita_por_pa.values())

    # =========== CUSTO DE FRETE ===========
    custo_frete_mp = 0.0
    custo_frete_pa = 0.0
    viagens_por_modal = {"Caminhão": 0, "Navio": 0, "Avião": 0}
    ton_por_modal = {"Caminhão": 0.0, "Navio": 0.0, "Avião": 0.0}
    dists_cache = cfg.distancias

    for _, row in df_sol_transp.iterrows():
        origem_cidade = str(row.get("Cidade", row.get("Cidade_Origem", "")))
        destino_cidade = str(row.get("Cidade_Destino", row.get("Cidade", "")))
        # Se o DataFrame tem só uma coluna 'Cidade', tentar achar a coluna de destino correta
        if "Cidade_Destino" in row:
            destino_cidade = str(row["Cidade_Destino"])
        modal = str(row["Modal"])
        item = str(row["Tipo do Produto"])
        qtd = float(row["Qtde"])
        try:
            dist = float(dists_cache[modal].at[origem_cidade, destino_cidade])
        except Exception:
            dist = 0.0
        custo = _custo_viagem(modal, dist, qtd, item, cfg)
        if item.startswith("MP"):
            custo_frete_mp += custo
        else:
            custo_frete_pa += custo
        viagens_por_modal[modal] = viagens_por_modal.get(modal, 0) + 1
        peso = _peso_ton_modal(modal, item, qtd, cfg)
        ton_por_modal[modal] = ton_por_modal.get(modal, 0.0) + peso

    # =========== CUSTO MP COMPRADA ===========
    # Soma das tonladas × custo unitário do fornecedor para cada linha Fornecedor→Fábrica
    custo_mp_comprada = 0.0
    for _, row in df_sol_transp.iterrows():
        if str(row.get("Origem", "")) != "Fornecedor":
            continue
        mp = str(row["Tipo do Produto"])
        cidade_forn = str(row.get("Cidade", ""))
        qtd_ton = float(row["Qtde"])
        # Acha custo do fornecedor
        for nome, custo_ton in cfg.fornecedores.get(mp, []):
            if nome == cidade_forn:
                custo_mp_comprada += qtd_ton * custo_ton
                break

    # =========== CUSTO CARREGAMENTO (estoque final × 1%) ===========
    # MP: usa MAIOR preço de mercado da MP
    maior_preco_mp = {
        mp: max(c for _, c in cfg.fornecedores.get(mp, [(None, 0.0)]))
        for mp in ("MP1", "MP2", "MP3")
    }
    carreg_mp = sum(
        estoque_mp_final.get(mp, 0.0) * maior_preco_mp[mp] * 0.01
        for mp in ("MP1", "MP2", "MP3")
    )
    carreg_pa = sum(
        sum(estoque_pa_final.get(cd, {}).values()) * cfg.precos_referencia.get("PA1", 80) * 0.01
        for cd in estoque_pa_final
    )

    # =========== CUSTOS ESTRUTURAIS ===========
    custo_estr_total = CUSTO_ESTRUTURAL_TOTAL

    # =========== DRE ===========
    custo_total = (custo_frete_mp + custo_frete_pa + custo_mp_comprada
                   + carreg_mp + carreg_pa + custo_estr_total)
    resultado_rodada = receita_total - custo_total

    dre = {
        "rodada": rodada_n,
        "receita_pa1": round(receita_por_pa["PA1"], 2),
        "receita_pa2": round(receita_por_pa["PA2"], 2),
        "receita_pa3": round(receita_por_pa["PA3"], 2),
        "receita_total": round(receita_total, 2),
        "custos": {
            "parcela_terrenos": CUSTO_PARCELA_TERRENOS,
            "parcela_maquinas": CUSTO_PARCELA_MAQUINAS,
            "parcela_contratacao": CUSTO_PARCELA_CONTRATACAO,
            "manut_fabricas": CUSTO_MANUT_FABRICAS,
            "salario_operarios": CUSTO_SALARIO_OPERARIOS,
            "custo_producao": CUSTO_PRODUCAO,
            "manut_cds": CUSTO_MANUT_CDS,
            "frete_mp": round(custo_frete_mp, 2),
            "frete_pa": round(custo_frete_pa, 2),
            "mp_comprada": round(custo_mp_comprada, 2),
            "carreg_mp": round(carreg_mp, 2),
            "carreg_pa": round(carreg_pa, 2),
            "estruturais_total": CUSTO_ESTRUTURAL_TOTAL,
        },
        "custo_total": round(custo_total, 2),
        "resultado_rodada": round(resultado_rodada, 2),
    }

    # =========== INDICADORES OPERACIONAIS ===========
    f1 = instalacoes["fabricas"]["F1"]
    cap_min_dia = f1["maquinas"] * f1["turnos"] * cfg.capacidades["horas_por_turno"] * 60
    cap_min_rodada = cap_min_dia * 5
    minutos_usados = 0
    for _, row in df_op_fabricas.iterrows():
        for pa in ("PA1", "PA2", "PA3"):
            qtd = int(row.get(pa, 0))
            minutos_usados += math.ceil(qtd / cfg.velocidades[pa]) if qtd > 0 else 0
    utilizacao = minutos_usados / cap_min_rodada if cap_min_rodada else 0.0

    custo_medio_por_frasco = (
        custo_total / sum(qtd_atendida_por_pa.values())
        if sum(qtd_atendida_por_pa.values()) > 0 else None
    )

    # Custo médio por ton transportada
    ton_total = sum(ton_por_modal.values())
    custo_medio_por_ton = (custo_frete_mp + custo_frete_pa) / ton_total if ton_total > 0 else None

    # Ocupação por modal (cap semanal × nº viagens vs. ton movimentada)
    # Cap modal semanal: caminhão pode fazer 10 viagens/sem (estimativa), avião 40, navio 3
    # Mas o jogo trata por viagem — vamos usar capacidade média da semana = 5 dias × n viagens estimadas
    cap_semanal = {
        "Caminhão": cfg.cap_modal_ton["Caminhão"] * max(1, viagens_por_modal["Caminhão"]),
        "Navio":    cfg.cap_modal_ton["Navio"] * max(1, viagens_por_modal["Navio"]),
        "Avião":    cfg.cap_modal_ton["Avião"] * max(1, viagens_por_modal["Avião"]),
    }
    ocupacao_modal = {
        m: ton_por_modal[m] / cap_semanal[m] if cap_semanal[m] > 0 else 0.0
        for m in ("Caminhão", "Navio", "Avião")
    }

    pct_modal = {
        m: ton_por_modal[m] / ton_total * 100 if ton_total > 0 else 0.0
        for m in ("Caminhão", "Navio", "Avião")
    }

    ind = {
        "fabrica": {
            "cidade": f1["cidade"],
            "cap_maq_HH_semanal": cap_min_rodada / 60,
            "utilizacao_pct": round(utilizacao * 100, 1),
            "ociosidade_pct": round((1 - utilizacao) * 100, 1),
            "custo_medio_por_frasco": (
                round(custo_medio_por_frasco, 2) if custo_medio_por_frasco else None
            ),
        },
        "transporte": {
            "viagens_por_modal": viagens_por_modal,
            "ton_por_modal": {k: round(v, 2) for k, v in ton_por_modal.items()},
            "ocupacao_modal_pct": {k: round(v * 100, 1) for k, v in ocupacao_modal.items()},
            "pct_modal_movimentacao": {k: round(v, 1) for k, v in pct_modal.items()},
            "custo_medio_por_ton": (
                round(custo_medio_por_ton, 2) if custo_medio_por_ton else None
            ),
        },
        "nivel_servico_realizado": {
            pa: (qtd_atendida_por_pa.get(pa, 0) > 0) for pa in ("PA1", "PA2", "PA3")
        },
    }

    # =========== VPL ===========
    historico = list(historico_resultados or [])
    todos_resultados = historico + [resultado_rodada]
    vpl = sum(r / (1 + TAXA_DESCONTO_POR_RODADA) ** i for i, r in enumerate(todos_resultados))
    vpl_acumulado_ate_rodada = sum(r for r in todos_resultados)  # nominal (sem desconto)

    return {
        "dre": dre,
        "ind": ind,
        "vpl": {
            "taxa_desconto_por_rodada_pct": TAXA_DESCONTO_POR_RODADA * 100,
            "resultado_rodada": round(resultado_rodada, 2),
            "resultado_acumulado_nominal": round(vpl_acumulado_ate_rodada, 2),
            "vpl_descontado": round(vpl, 2),
            "historico_rodadas": [round(r, 2) for r in historico],
        },
    }


def imprimir_painel(indicadores: Dict[str, Any]) -> None:
    """Imprime tabela amigável do DRE/IND/VPL."""
    dre = indicadores["dre"]
    ind = indicadores["ind"]
    vpl = indicadores["vpl"]
    r = dre["rodada"]
    print("=" * 70)
    print(f"  PAINEL — RODADA {r}")
    print("=" * 70)

    # Receita
    print("\n💰 RECEITA")
    for pa in ("PA1", "PA2", "PA3"):
        v = dre[f"receita_{pa.lower()}"]
        if v > 0:
            print(f"  {pa}: R$ {v:>14,.2f}")
    print(f"  TOTAL Receita:  R$ {dre['receita_total']:>14,.2f}")

    # Custos detalhados
    print("\n💸 CUSTOS")
    c = dre["custos"]
    print(f"  Estruturais (fixos):")
    print(f"    Parcelas terrenos:     R$ {c['parcela_terrenos']:>12,.2f}")
    print(f"    Parcelas máquinas:     R$ {c['parcela_maquinas']:>12,.2f}")
    print(f"    Manut fábricas:        R$ {c['manut_fabricas']:>12,.2f}")
    print(f"    Salário operários:     R$ {c['salario_operarios']:>12,.2f}")
    print(f"    Custo produção:        R$ {c['custo_producao']:>12,.2f}")
    print(f"    Manut CDs:             R$ {c['manut_cds']:>12,.2f}")
    print(f"  Variáveis:")
    print(f"    MP comprada:           R$ {c['mp_comprada']:>12,.2f}")
    print(f"    Frete MP:              R$ {c['frete_mp']:>12,.2f}")
    print(f"    Frete PA:              R$ {c['frete_pa']:>12,.2f}")
    print(f"    Carreg MP:             R$ {c['carreg_mp']:>12,.2f}")
    print(f"    Carreg PA:             R$ {c['carreg_pa']:>12,.2f}")
    print(f"  CUSTO TOTAL:             R$ {dre['custo_total']:>12,.2f}")
    sinal = "✅" if dre["resultado_rodada"] > 0 else "❌"
    print(f"\n  RESULTADO DA RODADA:     R$ {dre['resultado_rodada']:>12,.2f}  {sinal}")

    # Indicadores
    print("\n🏭 FÁBRICA F1")
    f = ind["fabrica"]
    print(f"  Cap HH semanal:    {f['cap_maq_HH_semanal']:.0f}")
    print(f"  Utilização:        {f['utilizacao_pct']}% (ociosidade {f['ociosidade_pct']}%)")
    if f["custo_medio_por_frasco"]:
        print(f"  Custo médio/frasco: R$ {f['custo_medio_por_frasco']}")

    print("\n🚛 TRANSPORTE")
    t = ind["transporte"]
    print(f"  Viagens: {t['viagens_por_modal']}")
    print(f"  Ton/modal: {t['ton_por_modal']}")
    print(f"  Distribuição (%): {t['pct_modal_movimentacao']}")
    if t["custo_medio_por_ton"]:
        print(f"  Custo médio/ton: R$ {t['custo_medio_por_ton']}")

    # VPL
    print("\n📊 VPL — VALOR PRESENTE LÍQUIDO")
    print(f"  Taxa desconto: {vpl['taxa_desconto_por_rodada_pct']}% por rodada")
    print(f"  Resultado da rodada:    R$ {vpl['resultado_rodada']:>14,.2f}")
    print(f"  Acumulado nominal:      R$ {vpl['resultado_acumulado_nominal']:>14,.2f}")
    print(f"  VPL descontado:         R$ {vpl['vpl_descontado']:>14,.2f}")
    if vpl["historico_rodadas"]:
        print(f"  Histórico: {vpl['historico_rodadas']}")
