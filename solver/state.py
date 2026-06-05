"""State machine multi-rodada: consolida tudo o que o solver precisa saber
sobre Flamengo no início da rodada N.

Para a rodada N, o estado consiste em:
  - estoque MP em F1 (do PDF ESTOQUES da rodada N)
  - estoque PA em cada CD (do PDF ESTOQUES)
  - MP em-trânsito (ordens de Forn→F1 das rodadas 1..N-1 cujo dia_chegada cai
    em N) — POR DIA da rodada N
  - PA em-trânsito (similar para F1→CD e CD→Varejo, mas em geral o jogo trata
    cada rodada de forma independente para PA porque PA descartado se chega
    fora do dia)
  - histórico de DRE (R1, R2, ..., R(N-1) resultados)

Lê:
  - rodadas/rodada_N/FLAMENGO.xlsm (instalações + SOL_TRANSP histórica)
  - rodadas/FLAMENGO_ALL.xlsm (consolidado se existir)
  - rodadas/rodada_N/ESTOQUES_FLAMENGO.pdf (parsing manual no código)
"""
from __future__ import annotations
import json
import re
import sys
from dataclasses import dataclass, asdict, field
from pathlib import Path
from typing import Any, Dict, List

import openpyxl

BASE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE))
from src.config import Config
from src.io_xlsm import ler_instalacoes

_DIA = re.compile(r"Dia\s*(\d+)")
_ROD = re.compile(r"Rodada_(\d+)")


@dataclass
class EstadoRodada:
    """Estado conhecido no INÍCIO da rodada N (= fim da rodada N-1)."""

    rodada: int
    # Estoques no dia (N-1)*5 (fim da rodada anterior)
    estoque_mp_ton: Dict[str, float] = field(default_factory=dict)        # MP1/MP2/MP3
    estoque_pa_cd: Dict[str, Dict[str, int]] = field(default_factory=dict) # cd → pa → qty

    # MP em-trânsito chegando DURANTE a rodada N (de ordens de N-1 ou antes)
    # Lista de dicts: {dia_rel, mp, qtd, origem, modal}
    mp_em_transito: List[Dict[str, Any]] = field(default_factory=list)

    # DREs históricas (R1, R2, ..., R(N-1))
    historico_dre: List[float] = field(default_factory=list)

    # Capacidades derivadas (read-only)
    cap_mp_ton: Dict[str, float] = field(default_factory=dict)
    cap_pa_cd_un: Dict[str, Dict[str, int]] = field(default_factory=dict)
    cap_min_dia: int = 0
    fab_principal: str = "F1"
    fab_cidade: str = ""
    cds_info: Dict[str, str] = field(default_factory=dict)

    def to_json(self) -> str:
        return json.dumps(asdict(self), ensure_ascii=False, indent=2)

    @classmethod
    def from_json(cls, s: str) -> "EstadoRodada":
        d = json.loads(s)
        return cls(**d)


def _parse_dia(value) -> int | None:
    if value is None:
        return None
    m = _DIA.search(str(value))
    return int(m.group(1)) if m else None


def _parse_rodada(value) -> int | None:
    if value is None:
        return None
    m = _ROD.search(str(value))
    return int(m.group(1)) if m else None


def consolidar_estado(rodada_n: int, flamengo_path: Path,
                      cfg: Config,
                      estoque_mp_pdf: Dict[str, float],
                      estoque_pa_cd_pdf: Dict[str, Dict[str, int]],
                      historico_dre: List[float],
                      lead_table_path: Path | None = None) -> EstadoRodada:
    """Constrói o EstadoRodada para a rodada N.

    Args:
        rodada_n: número da rodada atual (e.g. 3)
        flamengo_path: caminho para o FLAMENGO.xlsm desta rodada
                       (contém SOL_TRANSP histórico R1..R(N-1))
        cfg: Config (parâmetros do jogo)
        estoque_mp_pdf: do PDF ESTOQUES (fim da rodada N-1)
        estoque_pa_cd_pdf: do PDF ESTOQUES
        historico_dre: lista de resultados acumulados R1..R(N-1)
        lead_table_path: caminho data/lead_times.json (default usa BASE/data/)
    """
    # Lookup leads
    lt_path = lead_table_path or BASE / "data" / "lead_times.json"
    lead_tab = json.loads(lt_path.read_text(encoding="utf-8"))

    def lt(modal, o, d):
        if o == d:
            return 0
        return lead_tab.get(modal, {}).get(o, {}).get(d)

    # Instalações
    inst = ler_instalacoes(flamengo_path)
    f1 = inst["fabricas"]["F1"]
    cds_info = {cd: d["cidade"] for cd, d in inst["cds"].items()}

    cap_mp_ton = {
        mp: f1["area_mp"][mp] * cfg.capacidades["pe_direito_deposito_m"] * cfg.densidades_mp[mp]
        for mp in ("MP1", "MP2", "MP3")
    }
    cap_pa_cd_un = {
        cd: {pa: int(d["area_pa"][pa] * cfg.capacidades["pe_direito_deposito_m"]
                     * cfg.densidades_pa[pa] / cfg.peso_un_ton[pa])
             for pa in ("PA1", "PA2", "PA3")}
        for cd, d in inst["cds"].items()
    }
    cap_min_dia = f1["maquinas"] * f1["turnos"] * 8 * 60

    # Parse SOL_TRANSP do FLAMENGO.xlsm. Cada linha Forn→F1 de rodada anterior
    # cuja data_chegada cai DENTRO da rodada N entra em mp_em_transito.
    wb = openpyxl.load_workbook(flamengo_path, keep_vba=True, data_only=True)
    ws = wb["SOL_TRANSP"]

    mp_em_transito: List[Dict[str, Any]] = []
    dia_inicio_rodada_n_abs = (rodada_n - 1) * 5 + 1  # e.g. R3 → abs 11
    dia_fim_rodada_n_abs = rodada_n * 5               # e.g. R3 → abs 15

    for r in range(5, ws.max_row + 1):
        val = ws.cell(r, 1).value
        if not val:
            continue
        rod = _parse_rodada(val)
        if rod is None or rod >= rodada_n:
            continue
        origem_tipo = ws.cell(r, 2).value
        if (origem_tipo or "").strip() != "Fornecedor":
            continue
        origem_cid = ws.cell(r, 3).value
        dia_raw = _parse_dia(ws.cell(r, 4).value)
        if dia_raw is None:
            continue
        # Detecta absoluto vs relativo
        dia_abs_part = dia_raw if dia_raw > 5 else (rod - 1) * 5 + dia_raw
        modal = ws.cell(r, 5).value
        item = ws.cell(r, 6).value
        try:
            qtd = float(ws.cell(r, 7).value or 0)
        except (TypeError, ValueError):
            continue
        if not item or not item.startswith("MP"):
            continue
        lt_v = lt(modal, origem_cid, f1["cidade"])
        if lt_v is None:
            continue
        dia_abs_cheg = dia_abs_part + lt_v
        # Cai dentro da rodada N?
        if dia_inicio_rodada_n_abs <= dia_abs_cheg <= dia_fim_rodada_n_abs:
            dia_rel = dia_abs_cheg - (rodada_n - 1) * 5  # 1..5 dentro de N
            mp_em_transito.append({
                "dia_rel": dia_rel,
                "dia_abs": dia_abs_cheg,
                "mp": item,
                "qtd": qtd,
                "origem": origem_cid,
                "modal": modal,
                "lt": lt_v,
                "rodada_origem": rod,
            })

    # Ordena
    mp_em_transito.sort(key=lambda x: (x["dia_rel"], x["mp"]))

    return EstadoRodada(
        rodada=rodada_n,
        estoque_mp_ton=dict(estoque_mp_pdf),
        estoque_pa_cd=dict(estoque_pa_cd_pdf),
        mp_em_transito=mp_em_transito,
        historico_dre=list(historico_dre),
        cap_mp_ton=cap_mp_ton,
        cap_pa_cd_un=cap_pa_cd_un,
        cap_min_dia=cap_min_dia,
        fab_principal="F1",
        fab_cidade=f1["cidade"],
        cds_info=cds_info,
    )


def estado_r3_flamengo() -> EstadoRodada:
    """Helper: constrói o estado conhecido para Flamengo no início de R3."""
    cfg = Config.load(BASE)
    flam = BASE / "rodadas" / "rodada_3" / "FLAMENGO.xlsm"
    # Do PDF ESTOQUES R3 (fim R2 = Dia 10)
    estoque_mp = {"MP1": 78.98, "MP2": 50.36, "MP3": 48.14}
    estoque_pa = {cd: {"PA1": 0, "PA2": 0, "PA3": 0} for cd in ("CD1", "CD2")}
    historico = [-5_602_321.0, -1_128_560.0]  # DRE oficial (R2 ainda subestimado)
    return consolidar_estado(3, flam, cfg, estoque_mp, estoque_pa, historico)


def estado_r4_flamengo() -> EstadoRodada:
    """Helper: estado conhecido para Flamengo no início de R4 (= fim de R3).

    Fonte: rodadas/rodada_4/ESTOQUES_FLAMENGO.pdf (saldos no Dia 15).
      MP F1 Joinville: MP1≈0, MP2=0,02t, MP3=4,81t
      PA em CD: CD2 (Santos) PA2 = 105.106; restante 0.

    NOTA: além dos 105.106 PA2 em CD2, há ~359k PA2 que foram embarcados F1→CD
    nos Dias 14/15 de R3 (São Luís 70.948 + Santos 288.339) e estavam EM TRÂNSITO
    no fim de R3. Se o jogo os entregar como estoque utilizável em R4, a posição
    de PA2 sobe pra ~464k. Isso NÃO está incluído aqui (conservador: só o saldo
    confirmado no PDF). A verificar contra o realizado de R4.
    """
    cfg = Config.load(BASE)
    flam = BASE / "rodadas" / "rodada_4" / "FLAMENGO.xlsm"
    estoque_mp = {"MP1": 0.0, "MP2": 0.02, "MP3": 4.81}
    estoque_pa = {
        "CD1": {"PA1": 0, "PA2": 0, "PA3": 0},          # São Luís
        "CD2": {"PA1": 0, "PA2": 105_106, "PA3": 0},    # Santos (buffer PA2 confirmado)
    }
    # DRE oficial realizada (rodada_4/DRE_FLAMENGO.pdf): R1, R2, R3
    historico = [-5_602_321.0, -11_554_929.0, 35_617_989.0]
    return consolidar_estado(4, flam, cfg, estoque_mp, estoque_pa, historico)


def estado_r5_flamengo() -> EstadoRodada:
    """Estado de início de R5 (= fim de R4). R4 NÃO foi submetida (vendemos 0),
    então o estoque é o que carregou de R3 (o em-trânsito de PA2 chegou: 464k).

    Fonte: rodadas/rodada_5/ESTOQUES_FLAMENGO.pdf (saldos no Dia 20).
      MP F1: MP1=7,20t, MP2=12,02t, MP3=4,81t (o em-trânsito de R3 chegou; nada consumido)
      PA: CD1 (São Luís) PA2=70.948 ; CD2 (Santos) PA2=393.359 ; resto 0.
      MP em-trânsito p/ R5: NENHUM (R4 não comprou nada).
    R5 = PA1 @ R$69.
    """
    cfg = Config.load(BASE)
    flam = BASE / "rodadas" / "rodada_5" / "FLAMENGO.xlsm"
    estoque_mp = {"MP1": 7.20, "MP2": 12.02, "MP3": 4.81}
    estoque_pa = {
        "CD1": {"PA1": 0, "PA2": 70_948, "PA3": 0},      # São Luís
        "CD2": {"PA1": 0, "PA2": 393_359, "PA3": 0},     # Santos (98,3% do cap PA2)
    }
    # R4 não submetida → resultado R4 ≈ só custos fixos + carregamento (negativo)
    historico = [-5_602_321.0, -11_554_929.0, 35_617_989.0, -1_355_000.0]
    return consolidar_estado(5, flam, cfg, estoque_mp, estoque_pa, historico)


def estado_r6_flamengo() -> EstadoRodada:
    """Estado de início de R6 (= fim de R5). R5 FOI submetida — a previsão do
    solver cravou o estado inicial de R6 (MP1 66,4→66,41; MP2 38,7→38,71;
    MP3 23,6→23,57; PA idênticos), confirmando que o buffer de MP é REAL e a
    cascata da R4 foi quebrada (R6 começa abastecida).

    Fonte: rodadas/rodada_6/ESTOQUES_FLAMENGO.pdf (saldos no Dia 25).
      MP F1 Joinville: MP1=66,41t, MP2=38,71t, MP3=23,57t
      PA: CD1 (São Luís) PA2=70.948 ; CD2 (Santos) PA1=32.622, PA2=393.359, PA3=462.358.
      MP em-trânsito p/ R6: NENHUM — todos os pedidos de R5 (último Dia 24, lead≤3)
      chegam até o Dia 25, dentro de R5 (verificado contra lead_times).
    R6 = PA2 @ R$48 → a rodada que finalmente usa o buffer de 464k PA2 em estoque.
    """
    cfg = Config.load(BASE)
    flam = BASE / "rodadas" / "rodada_6" / "FLAMENGO.xlsm"
    estoque_mp = {"MP1": 66.41, "MP2": 38.71, "MP3": 23.57}
    estoque_pa = {
        "CD1": {"PA1": 0, "PA2": 70_948, "PA3": 0},              # São Luís
        "CD2": {"PA1": 32_622, "PA2": 393_359, "PA3": 462_358},  # Santos
    }
    # DRE oficial realizada (rodadas/rodada_6/DRE_FLAMENGO.pdf): R1..R5.
    historico = [-5_602_321.0, -11_554_929.0, 35_617_989.0, -1_356_169.0, 1_603_752.0]
    return consolidar_estado(6, flam, cfg, estoque_mp, estoque_pa, historico)


if __name__ == "__main__":
    import io
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
    if "--r6" in sys.argv:
        estado = estado_r6_flamengo()
    elif "--r4" in sys.argv:
        estado = estado_r4_flamengo()
    else:
        estado = estado_r3_flamengo()
    print(f"=== ESTADO R{estado.rodada} ===")
    print(f"Estoque MP: {estado.estoque_mp_ton}")
    print(f"Estoque PA: {estado.estoque_pa_cd}")
    print(f"Cap MP F1: {estado.cap_mp_ton}")
    print(f"Cap min/dia: {estado.cap_min_dia}")
    print(f"\nMP em-trânsito (de R1..R{estado.rodada-1} chegando em R{estado.rodada}):")
    if not estado.mp_em_transito:
        print("  (nenhuma)")
    for x in estado.mp_em_transito:
        print(f"  Dia rel {x['dia_rel']} (abs {x['dia_abs']}): {x['qtd']:.1f}t {x['mp']} "
              f"de {x['origem']} via {x['modal']} (lt={x['lt']}d, shipped R{x['rodada_origem']})")
    print(f"\nHistórico DRE: {estado.historico_dre}")
