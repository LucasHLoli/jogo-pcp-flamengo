"""Módulo de factibilidade (cockpit) do Jogo PCP 2.

Gera um relatório legível por rodada com checks de capacidade, lead time,
financeiro e atendimento. Chamado depois do planner+LP.

Aproximações documentadas:
- Custo estrutural é tratado como rateio fixo placeholder (R$ 850k/rodada).
  TODO: detalhar terreno/máquina/MO/água/EE/manutenção por NE.
- Lead time arredondado para cima de 8h úteis/dia (igual ao planner).
- Frete por viagem: regra do briefing (>=80% ocup. → cheio; <80% → meio + peso).
"""
from __future__ import annotations
import math
from typing import Any, Dict, List, Optional, Tuple

from src.config import Config
from src.domain import (
    Estado, OP, OPDescartada, PlanoProducao, PlanoTransporte,
)

# Custo estrutural por rodada, conforme DRE real do prof na Rodada 1:
#   Parcela terrenos:        R$  506.968
#   Parcela máquinas:        R$  415.567
#   Parcela contratação:     R$       84
#   Manutenção fábricas:     R$    1.313
#   Salário operários:       R$      450
#   Custo de produção:       R$  172.086
#   Manutenção CDs:          R$   26.683
#   Carregamento estoque MP: R$    5.410
#   TOTAL:                   R$ 1.128.561 (sem MP/frete, que entram por fora)
_CUSTO_ESTRUTURAL_PLACEHOLDER = 1_128_561.0

_PA_LIST = ("PA1", "PA2", "PA3")
_MP_LIST = ("MP1", "MP2", "MP3")


# ----------------------------- utilitários -----------------------------

def _km(cfg: Config, modal: str, origem: str, destino: str) -> float:
    try:
        v = cfg.distancias[modal].at[origem, destino]
    except (KeyError, ValueError):
        return 0.0
    if v is None:
        return 0.0
    try:
        f = float(v)
    except (TypeError, ValueError):
        return 0.0
    if math.isnan(f) or f < 0:
        return 0.0
    return f


def _lead_time_dias(cfg: Config, modal: str, km: float) -> int:
    if km <= 0:
        return 0
    vel = {"Avião": 700, "Caminhão": 50, "Navio": 30}[modal]
    horas = km / vel
    return max(1, math.ceil(horas / 8))


def _qtd_ton(item: str, qtd: float, cfg: Config) -> float:
    if item.startswith("PA"):
        return qtd * cfg.peso_un_ton[item]
    return float(qtd)  # MP já em ton


def _cap_pa_frascos(area_m2: float, cfg: Config, pa: str) -> int:
    ton = area_m2 * cfg.capacidades["pe_direito_deposito_m"] * cfg.densidades_pa[pa]
    return int(ton / cfg.peso_un_ton[pa])


def _cap_mp_ton(area_m2: float, cfg: Config, mp: str) -> float:
    return area_m2 * cfg.capacidades["pe_direito_deposito_m"] * cfg.densidades_mp[mp]


def _custo_viagem(modal: str, km: float, qtd_ton: float, cfg: Config) -> float:
    """Custo de uma viagem — regra oficial calibrada vs DRE real R3:
    ≥80% paga frete-viagem cheio; <80% paga frete-peso puro. Sem CT-e/doc
    nem meia-viagem fixa (descartados por bater com o frete realizado)."""
    cap_ton = cfg.cap_modal_ton[modal]
    if cap_ton <= 0:
        return 0.0
    ocup = qtd_ton / cap_ton
    fv = cfg.frete_viagem[modal]
    fp = cfg.frete_peso[modal]
    if ocup >= 0.8:
        return fv * km
    return fp * km * qtd_ton


# ----------------------------- seções -----------------------------

def _secao_producao(
    planos_prod: List[PlanoProducao],
    planos_transp: List[PlanoTransporte],
    cfg: Config,
    fabrica_cidade: str,
    maquinas: int,
    turnos: int,
) -> Dict[str, Any]:
    minutos_por_dia = [0] * 5
    qtd_por_dia_pa: Dict[int, Dict[str, int]] = {d: {} for d in range(1, 6)}
    for p in planos_prod:
        vel = cfg.velocidades[p.pa]
        minutos = math.ceil(p.qtd / vel) if vel > 0 else 0
        minutos_por_dia[p.dia - 1] += minutos
        qtd_por_dia_pa[p.dia][p.pa] = qtd_por_dia_pa[p.dia].get(p.pa, 0) + p.qtd

    minutos_max = maquinas * turnos * 60 * cfg.capacidades.get("horas_por_turno", 8)
    if minutos_max <= 0:
        minutos_max = 10080
    ok_capacidade = all(m <= minutos_max for m in minutos_por_dia)

    # pa_dorme_fabrica: True se algum PA produzido NÃO tem transporte saindo da fábrica
    # no mesmo dia (e mesmo PA) cobrindo a quantidade.
    pa_dorme = False
    for dia in range(1, 6):
        for pa, qtd_prod in qtd_por_dia_pa[dia].items():
            qtd_saindo = sum(
                t.qtd for t in planos_transp
                if t.origem_tipo == "Fábrica"
                and t.origem_cidade == fabrica_cidade
                and t.item == pa
                and t.dia_coleta == dia
            )
            if qtd_prod > qtd_saindo + 1e-6:
                pa_dorme = True
                break
        if pa_dorme:
            break

    total_frascos = sum(p.qtd for p in planos_prod)
    return {
        "minutos_por_dia": [int(m) for m in minutos_por_dia],
        "minutos_max": int(minutos_max),
        "ok_capacidade": bool(ok_capacidade),
        "pa_dorme_fabrica": bool(pa_dorme),
        "total_frascos": int(total_frascos),
    }


def _secao_armazenagem(
    planos_transp: List[PlanoTransporte],
    planos_prod: List[PlanoProducao],
    estado_abertura: Estado,
    cfg: Config,
    instalacoes: Dict,
    fabrica_cidade: str,
    rodada_n: int,
) -> Tuple[Dict[str, Any], Dict[str, Dict[str, int]]]:
    """Simula estoque dia a dia para tracking de pico.

    Retorna (secao_armazenagem, estoque_final_pa_por_cd) — o último é usado
    pelo cálculo de carregamento.
    """
    cap_mp = {mp: _cap_mp_ton(instalacoes["fabricas"]["F1"]["area_mp"][mp], cfg, mp)
              for mp in _MP_LIST}

    cds_info = {cd: info["cidade"] for cd, info in instalacoes["cds"].items()
                if info.get("cidade")}
    cap_pa_cd = {
        cd: {pa: _cap_pa_frascos(instalacoes["cds"][cd]["area_pa"][pa], cfg, pa)
             for pa in _PA_LIST}
        for cd in cds_info
    }

    # ---- MP em F1 ----
    estoque_mp = dict(estado_abertura.estoque_mp_fabrica.get("F1", {mp: 0.0 for mp in _MP_LIST}))
    for mp in _MP_LIST:
        estoque_mp.setdefault(mp, 0.0)
    pico_mp = {mp: estoque_mp[mp] for mp in _MP_LIST}

    # Chegadas de MP por dia (pelos planos de transporte fornecedor→fábrica)
    chegadas_mp: Dict[int, Dict[str, float]] = {d: {mp: 0.0 for mp in _MP_LIST}
                                                 for d in range(1, 6)}
    for p in planos_transp:
        if not p.item.startswith("MP"):
            continue
        if p.origem_tipo != "Fornecedor" or p.destino_tipo != "Fábrica":
            continue
        km = _km(cfg, p.modal, p.origem_cidade, p.destino_cidade)
        lt = _lead_time_dias(cfg, p.modal, km)
        dia_cheg = p.dia_coleta + lt
        if 1 <= dia_cheg <= 5:
            chegadas_mp[dia_cheg][p.item] += float(p.qtd)

    # Consumo de MP por dia (via BoM)
    consumo_mp: Dict[int, Dict[str, float]] = {d: {mp: 0.0 for mp in _MP_LIST}
                                                for d in range(1, 6)}
    for pp in planos_prod:
        for mp in _MP_LIST:
            g = cfg.BoM[pp.pa][mp]
            consumo_mp[pp.dia][mp] += pp.qtd * g / 1_000_000

    for dia in range(1, 6):
        for mp in _MP_LIST:
            estoque_mp[mp] += chegadas_mp[dia][mp]
            if estoque_mp[mp] > pico_mp[mp]:
                pico_mp[mp] = estoque_mp[mp]
            estoque_mp[mp] = max(0.0, estoque_mp[mp] - consumo_mp[dia][mp])

    mp_f1 = {}
    for mp in _MP_LIST:
        cap = cap_mp[mp]
        pct = (pico_mp[mp] / cap * 100.0) if cap > 0 else 0.0
        mp_f1[mp] = {
            "pico_ton": float(pico_mp[mp]),
            "cap_ton": float(cap),
            "ocup_max_pct": float(pct),
            "ok": bool(pico_mp[mp] <= cap + 1e-6),
        }

    # ---- PA em CDs ----
    # Estoque inicial = estado_abertura.estoque_pa_cd[cd]
    estoque_pa = {cd: {pa: int(estado_abertura.estoque_pa_cd.get(cd, {}).get(pa, 0))
                       for pa in _PA_LIST} for cd in cds_info}
    pico_pa = {cd: {pa: estoque_pa[cd][pa] for pa in _PA_LIST} for cd in cds_info}

    # Chegadas no CD: F1→CD e transit pre-existente (rod_cheg == rodada_n)
    chegadas_pa: Dict[str, Dict[int, Dict[str, int]]] = {
        cd: {d: {pa: 0 for pa in _PA_LIST} for d in range(1, 6)}
        for cd in cds_info
    }
    saidas_pa: Dict[str, Dict[int, Dict[str, int]]] = {
        cd: {d: {pa: 0 for pa in _PA_LIST} for d in range(1, 6)}
        for cd in cds_info
    }

    cidade_to_cd = {v: k for k, v in cds_info.items()}

    # Trânsito pré-existente
    for t in estado_abertura.transit:
        if not t.item.startswith("PA"):
            continue
        if t.destino_tipo != "CD":
            continue
        cd = cidade_to_cd.get(t.destino_cidade)
        if cd is None or cd not in chegadas_pa:
            continue
        if t.rod_cheg == rodada_n and 1 <= t.dia_cheg <= 5:
            chegadas_pa[cd][t.dia_cheg][t.item] += int(t.qtd)

    # Planos de transporte desta rodada
    for p in planos_transp:
        if not p.item.startswith("PA"):
            continue
        km = _km(cfg, p.modal, p.origem_cidade, p.destino_cidade)
        lt = _lead_time_dias(cfg, p.modal, km)
        dia_cheg = p.dia_coleta + lt

        # Chegada num CD (F1→CD)
        if p.destino_tipo == "CD":
            cd = cidade_to_cd.get(p.destino_cidade)
            if cd is not None and 1 <= dia_cheg <= 5:
                chegadas_pa[cd][dia_cheg][p.item] += int(p.qtd)

        # Saída de um CD (CD→Varejista)
        if p.origem_tipo == "CD":
            cd = cidade_to_cd.get(p.origem_cidade)
            if cd is not None and 1 <= p.dia_coleta <= 5:
                saidas_pa[cd][p.dia_coleta][p.item] += int(p.qtd)

    for dia in range(1, 6):
        for cd in cds_info:
            for pa in _PA_LIST:
                estoque_pa[cd][pa] += chegadas_pa[cd][dia][pa]
                if estoque_pa[cd][pa] > pico_pa[cd][pa]:
                    pico_pa[cd][pa] = estoque_pa[cd][pa]
                estoque_pa[cd][pa] = max(0, estoque_pa[cd][pa] - saidas_pa[cd][dia][pa])

    pa_secoes: Dict[str, Dict[str, Any]] = {}
    for cd in cds_info:
        chave = "pa_cd1" if cd == "CD1" else "pa_cd2" if cd == "CD2" else f"pa_{cd.lower()}"
        d = {}
        for pa in _PA_LIST:
            cap = cap_pa_cd[cd][pa]
            pico = pico_pa[cd][pa]
            pct = (pico / cap * 100.0) if cap > 0 else 0.0
            d[pa] = {
                "pico_frascos": int(pico),
                "cap_frascos": int(cap),
                "ocup_max_pct": float(pct),
                "ok": bool(pico <= cap),
            }
        pa_secoes[chave] = d

    secao: Dict[str, Any] = {"mp_f1": mp_f1}
    secao.update(pa_secoes)
    if "pa_cd1" not in secao:
        secao["pa_cd1"] = {}
    if "pa_cd2" not in secao:
        secao["pa_cd2"] = {}
    return secao, estoque_pa


def _secao_transporte(planos_transp: List[PlanoTransporte], cfg: Config) -> Dict[str, Any]:
    total = len(planos_transp)
    limite = int(cfg.capacidades.get("max_transportes_semana", 220))
    ok_cap = True
    ok_rotas_navio = True
    por_cat = {"fornecedor_f1": 0, "f1_cd": 0, "cd_varejo": 0}
    for p in planos_transp:
        cap = cfg.cap_modal_por_item.get(p.modal, {}).get(p.item)
        if cap is not None and float(p.qtd) > float(cap) + 1e-6:
            ok_cap = False
        if p.modal == "Navio":
            if (p.origem_cidade, p.destino_cidade) not in cfg.rotas_navio_validas:
                ok_rotas_navio = False
        if p.origem_tipo == "Fornecedor" and p.destino_tipo == "Fábrica":
            por_cat["fornecedor_f1"] += 1
        elif p.origem_tipo == "Fábrica" and p.destino_tipo == "CD":
            por_cat["f1_cd"] += 1
        elif p.origem_tipo == "CD" and p.destino_tipo == "Varejista":
            por_cat["cd_varejo"] += 1
    return {
        "total_viagens": total,
        "limite_220": limite,
        "ok_220": total <= limite,
        "ok_cap_modal": ok_cap,
        "ok_rotas_navio": ok_rotas_navio,
        "por_categoria": por_cat,
    }


def _secao_lead_time(
    planos_transp: List[PlanoTransporte],
    ops: List[OP],
    descartadas: List[OPDescartada],
    cfg: Config,
    fabrica_cidade: str,
) -> Dict[str, Any]:
    # CD→Varejo: para cada OP atendida, achar plano e verificar lead time.
    op_keys_descartadas = {(d.op.cidade, d.op.pa, d.op.qtd, d.op.dia_entrega)
                           for d in descartadas}
    ok_count = 0
    fail_count = 0
    for op in ops:
        if (op.cidade, op.pa, op.qtd, op.dia_entrega) in op_keys_descartadas:
            continue
        plano = next(
            (p for p in planos_transp
             if p.origem_tipo == "CD"
             and p.destino_tipo == "Varejista"
             and p.destino_cidade == op.cidade
             and p.item == op.pa),
            None,
        )
        if plano is None:
            fail_count += 1
            continue
        km = _km(cfg, plano.modal, plano.origem_cidade, plano.destino_cidade)
        lt = _lead_time_dias(cfg, plano.modal, km)
        if plano.dia_coleta + lt <= op.dia_entrega:
            ok_count += 1
        else:
            fail_count += 1

    # F1→CD: ok se todos planos chegam até dia 5 (dentro da rodada).
    ok_f1_cd = True
    for p in planos_transp:
        if p.origem_tipo == "Fábrica" and p.destino_tipo == "CD":
            km = _km(cfg, p.modal, p.origem_cidade, p.destino_cidade)
            lt = _lead_time_dias(cfg, p.modal, km)
            if p.dia_coleta + lt > 5:
                # chega na rodada seguinte — não é erro fatal, mas marcamos como warn
                ok_f1_cd = False
                break

    # Fornecedor→F1: idem.
    ok_forn = True
    for p in planos_transp:
        if p.origem_tipo == "Fornecedor" and p.destino_tipo == "Fábrica":
            km = _km(cfg, p.modal, p.origem_cidade, p.destino_cidade)
            lt = _lead_time_dias(cfg, p.modal, km)
            if p.dia_coleta + lt > 5:
                ok_forn = False
                break

    return {
        "cd_varejo": {"ok": ok_count, "fail": fail_count},
        "f1_cd": {"ok": bool(ok_f1_cd)},
        "fornecedor_f1": {"ok": bool(ok_forn)},
    }


def _secao_ops(
    ops: List[OP],
    descartadas: List[OPDescartada],
    planos_transp: List[PlanoTransporte],
    precos_mercado: Dict[str, float],
    cfg: Config,
) -> Tuple[List[Dict[str, Any]], Dict[str, int]]:
    desc_map = {(d.op.cidade, d.op.pa, d.op.qtd, d.op.dia_entrega): d
                for d in descartadas}
    lista: List[Dict[str, Any]] = []
    atendidas = 0
    desc_count = 0
    for op in ops:
        key = (op.cidade, op.pa, op.qtd, op.dia_entrega)
        if key in desc_map:
            d = desc_map[key]
            lista.append({
                "cidade": op.cidade,
                "pa": op.pa,
                "qtd": op.qtd,
                "dia_entrega": op.dia_entrega,
                "status": "descartada",
                "motivo": d.motivo,
                "receita_R$": 0.0,
                "margem_pct": None,
            })
            desc_count += 1
            continue
        preco = float(precos_mercado.get(op.pa, 0.0))
        receita = op.qtd * preco
        plano = next(
            (p for p in planos_transp
             if p.origem_tipo == "CD"
             and p.destino_tipo == "Varejista"
             and p.destino_cidade == op.cidade
             and p.item == op.pa),
            None,
        )
        margem_pct: Optional[float] = None
        if plano is not None:
            km = _km(cfg, plano.modal, plano.origem_cidade, plano.destino_cidade)
            qtd_ton = _qtd_ton(plano.item, float(plano.qtd), cfg)
            custo_frete = _custo_viagem(plano.modal, km, qtd_ton, cfg)
            # Rateio do frete pela fração da OP no plano
            frac = (op.qtd / float(plano.qtd)) if plano.qtd > 0 else 1.0
            custo_op = custo_frete * frac
            if receita > 0:
                margem_pct = (receita - custo_op) / receita * 100.0
        lista.append({
            "cidade": op.cidade,
            "pa": op.pa,
            "qtd": op.qtd,
            "dia_entrega": op.dia_entrega,
            "status": "atendida",
            "motivo": None,
            "receita_R$": float(receita),
            "margem_pct": margem_pct,
        })
        atendidas += 1

    # Também adiciona OPs descartadas que não estavam em `ops` (caso a lista
    # de ops seja apenas pendentes, descartadas podem vir só em `descartadas`).
    seen = {(o.cidade, o.pa, o.qtd, o.dia_entrega) for o in ops}
    for d in descartadas:
        k = (d.op.cidade, d.op.pa, d.op.qtd, d.op.dia_entrega)
        if k in seen:
            continue
        lista.append({
            "cidade": d.op.cidade,
            "pa": d.op.pa,
            "qtd": d.op.qtd,
            "dia_entrega": d.op.dia_entrega,
            "status": "descartada",
            "motivo": d.motivo,
            "receita_R$": 0.0,
            "margem_pct": None,
        })
        desc_count += 1
    total = atendidas + desc_count
    taxa = (atendidas / total * 100.0) if total > 0 else 0.0
    return lista, {
        "total_ops": total,
        "atendidas": atendidas,
        "descartadas": desc_count,
        "taxa_pct": taxa,
    }


def _secao_financeiro(
    planos_transp: List[PlanoTransporte],
    ops_lista: List[Dict[str, Any]],
    estoque_final_pa: Dict[str, Dict[str, int]],
    estoque_final_mp: Dict[str, float],
    cfg: Config,
    precos_mercado: Dict[str, float],
) -> Dict[str, Any]:
    receita = sum(op["receita_R$"] for op in ops_lista if op["status"] == "atendida")

    custo_frete_forn = 0.0
    custo_frete_f1_cd = 0.0
    custo_frete_cd_varejo = 0.0
    custo_mp_comprada = 0.0

    # custos por fornecedor (lookup)
    custo_mp_por_fornecedor: Dict[Tuple[str, str], float] = {}
    for mp, lista in cfg.fornecedores.items():
        for cidade, custo in lista:
            custo_mp_por_fornecedor[(mp, cidade)] = float(custo)

    for p in planos_transp:
        km = _km(cfg, p.modal, p.origem_cidade, p.destino_cidade)
        qtd_ton = _qtd_ton(p.item, float(p.qtd), cfg)
        custo = _custo_viagem(p.modal, km, qtd_ton, cfg)

        if p.origem_tipo == "Fornecedor" and p.destino_tipo == "Fábrica":
            custo_frete_forn += custo
            if p.item.startswith("MP"):
                custo_un = custo_mp_por_fornecedor.get((p.item, p.origem_cidade), 0.0)
                custo_mp_comprada += qtd_ton * custo_un
        elif p.origem_tipo == "Fábrica" and p.destino_tipo == "CD":
            custo_frete_f1_cd += custo
        elif p.origem_tipo == "CD" and p.destino_tipo == "Varejista":
            custo_frete_cd_varejo += custo

    # Carregamento de estoque final
    carreg_pct = float(cfg.capacidades.get("carregamento_mp_pct", 0.01))
    carreg_pa_pct = float(cfg.capacidades.get("carregamento_pa_pct", 0.01))

    # Maior preço MP entre fornecedores
    maior_preco_mp = {mp: max((c for _, c in lst), default=0.0)
                      for mp, lst in cfg.fornecedores.items()}
    custo_carreg_mp = 0.0
    for mp in _MP_LIST:
        custo_carreg_mp += estoque_final_mp.get(mp, 0.0) * maior_preco_mp.get(mp, 0.0) * carreg_pct

    custo_carreg_pa = 0.0
    for cd, dpa in estoque_final_pa.items():
        for pa, qtd in dpa.items():
            preco_ref = cfg.precos_referencia.get(pa, 0.0)
            custo_carreg_pa += qtd * preco_ref * carreg_pa_pct

    custo_estr = _CUSTO_ESTRUTURAL_PLACEHOLDER

    custo_total = (
        custo_frete_forn + custo_frete_f1_cd + custo_frete_cd_varejo
        + custo_mp_comprada + custo_carreg_mp + custo_carreg_pa + custo_estr
    )
    margem = receita - custo_total
    margem_pct = (margem / receita * 100.0) if receita > 0 else 0.0

    return {
        "receita": float(receita),
        "custo_frete_fornecedor_f1": float(custo_frete_forn),
        "custo_frete_f1_cd": float(custo_frete_f1_cd),
        "custo_frete_cd_varejo": float(custo_frete_cd_varejo),
        "custo_mp_comprada": float(custo_mp_comprada),
        "custo_carregamento_mp": float(custo_carreg_mp),
        "custo_carregamento_pa": float(custo_carreg_pa),
        "custo_estruturais": float(custo_estr),
        "custo_total": float(custo_total),
        "margem_R$": float(margem),
        "margem_pct": float(margem_pct),
    }


def _gerar_alertas(
    armazenagem: Dict[str, Any],
    atendimento: Dict[str, Any],
    financeiro: Dict[str, Any],
    transporte: Dict[str, Any],
    ops_lista: List[Dict[str, Any]],
) -> List[str]:
    alertas: List[str] = []

    # Ocupação
    for chave, label in (("mp_f1", "MP em F1"),
                        ("pa_cd1", "PA em CD1"),
                        ("pa_cd2", "PA em CD2")):
        bloco = armazenagem.get(chave, {})
        for item, info in bloco.items():
            pct = info.get("ocup_max_pct", 0.0)
            if pct > 80:
                alertas.append(
                    f"⚠ {item} em {label.split(' em ')[-1]} chegará a {pct:.0f}% da cap"
                )

    if atendimento.get("total_ops", 0) > 0 and atendimento.get("taxa_pct", 100) < 80:
        alertas.append(
            f"⚠ Taxa de atendimento baixa ({atendimento['taxa_pct']:.0f}%)"
        )

    if financeiro.get("receita", 0) > 0 and financeiro.get("margem_pct", 0) < 10:
        alertas.append(f"⚠ Margem apertada ({financeiro['margem_pct']:.1f}%)")

    if transporte.get("total_viagens", 0) > 200:
        alertas.append(
            f"⚠ Próximo do limite 220 transportes/semana "
            f"({transporte['total_viagens']})"
        )

    n_lt = sum(1 for o in ops_lista
               if o["status"] == "descartada" and o["motivo"] == "lead_time_inviavel")
    if n_lt > 0:
        alertas.append(f"⚠ {n_lt} OP(s) descartada(s) por lead time")

    if not transporte.get("ok_cap_modal", True):
        alertas.append("⚠ Há viagens excedendo a capacidade do modal")

    if not transporte.get("ok_rotas_navio", True):
        alertas.append("⚠ Navio em rota inválida")

    return alertas


# ----------------------------- principal -----------------------------

def gerar_cockpit(
    planos_transporte: List[PlanoTransporte],
    planos_producao: List[PlanoProducao],
    estado_abertura: Estado,
    ops_recebidas: List[OP],
    ops_descartadas: List[OPDescartada],
    precos_mercado: Dict[str, float],
    cfg: Config,
    instalacoes: Dict,
    rodada_n: int,
) -> Dict[str, Any]:
    """Gera o dict-relatório de factibilidade da rodada."""
    fabrica_info = instalacoes["fabricas"].get("F1", {})
    fabrica_cidade = fabrica_info.get("cidade", "Joinville")
    maquinas = int(fabrica_info.get("maquinas", 7))
    turnos = int(fabrica_info.get("turnos", 3))

    producao = _secao_producao(
        planos_producao, planos_transporte, cfg,
        fabrica_cidade, maquinas, turnos,
    )

    armazenagem, estoque_final_pa = _secao_armazenagem(
        planos_transporte, planos_producao, estado_abertura,
        cfg, instalacoes, fabrica_cidade, rodada_n,
    )

    # Estoque final MP: simula novamente (rápido) ou reusa do estado_abertura
    # como aproximação — recalculamos via simulação acima também.
    estoque_final_mp = dict(estado_abertura.estoque_mp_fabrica.get("F1", {mp: 0.0 for mp in _MP_LIST}))
    for mp in _MP_LIST:
        estoque_final_mp.setdefault(mp, 0.0)
    # Aplicar chegadas e consumo para obter estoque ao fim do dia 5.
    chegadas: Dict[str, float] = {mp: 0.0 for mp in _MP_LIST}
    for p in planos_transporte:
        if p.item.startswith("MP") and p.origem_tipo == "Fornecedor" and p.destino_tipo == "Fábrica":
            km = _km(cfg, p.modal, p.origem_cidade, p.destino_cidade)
            lt = _lead_time_dias(cfg, p.modal, km)
            if p.dia_coleta + lt <= 5:
                chegadas[p.item] += float(p.qtd)
    consumo: Dict[str, float] = {mp: 0.0 for mp in _MP_LIST}
    for pp in planos_producao:
        for mp in _MP_LIST:
            g = cfg.BoM[pp.pa][mp]
            consumo[mp] += pp.qtd * g / 1_000_000
    for mp in _MP_LIST:
        estoque_final_mp[mp] = max(0.0, estoque_final_mp[mp] + chegadas[mp] - consumo[mp])

    transporte = _secao_transporte(planos_transporte, cfg)

    lead_time = _secao_lead_time(
        planos_transporte, ops_recebidas, ops_descartadas, cfg, fabrica_cidade,
    )

    ops_lista, atendimento = _secao_ops(
        ops_recebidas, ops_descartadas, planos_transporte, precos_mercado, cfg,
    )

    financeiro = _secao_financeiro(
        planos_transporte, ops_lista, estoque_final_pa, estoque_final_mp,
        cfg, precos_mercado,
    )

    alertas = _gerar_alertas(armazenagem, atendimento, financeiro, transporte, ops_lista)

    return {
        "rodada": int(rodada_n),
        "alertas": alertas,
        "producao": producao,
        "armazenagem": armazenagem,
        "transporte": transporte,
        "lead_time": lead_time,
        "ops": ops_lista,
        "atendimento": atendimento,
        "financeiro": financeiro,
    }
