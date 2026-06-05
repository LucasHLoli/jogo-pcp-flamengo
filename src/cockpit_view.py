"""Formata o cockpit (dict de gerar_cockpit) em texto/pandas legível."""
from __future__ import annotations
import sys
from typing import Any, Dict
import pandas as pd


def _ensure_utf8_stdout() -> None:
    """Tenta reconfigurar stdout para UTF-8 (Windows terminal vem em cp1252)."""
    reconfigure = getattr(sys.stdout, "reconfigure", None)
    if reconfigure is None:
        return
    try:
        reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass


def imprimir_cockpit(cockpit: Dict[str, Any]) -> None:
    """Imprime o cockpit de forma humana no notebook."""
    _ensure_utf8_stdout()
    print("=" * 63)
    print(f"  RODADA {cockpit['rodada']} — FLAMENGO — Cockpit de Factibilidade")
    print("=" * 63)
    print()

    # Alertas
    if cockpit["alertas"]:
        print("🚨 ALERTAS")
        for a in cockpit["alertas"]:
            # remove prefixos ⚠/!/etc duplicados que o gerador possa ter incluído
            txt = a.lstrip("⚠️! ").strip()
            print(f"  ⚠ {txt}")
    else:
        print("✅ Sem alertas — tudo verde")
    print()

    # Produção
    prod = cockpit["producao"]
    print(f"🏭 PRODUÇÃO F1 (cap {prod['minutos_max']} min-máq/dia)")
    for d, m in enumerate(prod["minutos_por_dia"], start=1):
        pct = round(m / prod["minutos_max"] * 100, 1)
        sinal = "✅" if m <= prod["minutos_max"] else "❌"
        print(f"  Dia {d}: {m:>5} min ({pct:>5.1f}%)  {sinal}")
    print(f"  Total produzido: {prod['total_frascos']:,} frascos")
    print(f"  PA não dorme na fábrica: {'✅' if not prod.get('pa_dorme_fabrica', False) else '❌'}")
    print()

    # Armazenagem (resumo)
    arm = cockpit["armazenagem"]
    print("📦 ARMAZENAGEM (pico durante a rodada)")
    for mp in ("MP1", "MP2", "MP3"):
        info = arm["mp_f1"][mp]
        sinal = "✅" if info["ok"] else "❌"
        print(f"  F1 {mp}: {info['pico_ton']:>6.1f} / {info['cap_ton']:>5.1f} ton ({info['ocup_max_pct']:>5.1f}%)  {sinal}")
    for cd_key, cd_nome in [("pa_cd1", "CD1"), ("pa_cd2", "CD2")]:
        for pa in ("PA1", "PA2", "PA3"):
            info = arm[cd_key][pa]
            sinal = "✅" if info["ok"] else "❌"
            print(f"  {cd_nome} {pa}: {info['pico_frascos']:>9,} / {info['cap_frascos']:>9,} fr ({info['ocup_max_pct']:>5.1f}%)  {sinal}")
    print()

    # Transporte
    tr = cockpit["transporte"]
    print(f"🚛 TRANSPORTE")
    print(f"  Viagens: {tr['total_viagens']} / {tr['limite_220']}  {'✅' if tr['ok_220'] else '❌'}")
    print(f"  Capacidade modal por viagem: {'✅' if tr['ok_cap_modal'] else '❌'}")
    print(f"  Rotas Navio válidas: {'✅' if tr['ok_rotas_navio'] else '❌'}")
    cat = tr.get("por_categoria", {})
    print(f"    Fornecedor→F1: {cat.get('fornecedor_f1',0)}")
    print(f"    F1→CD: {cat.get('f1_cd',0)}")
    print(f"    CD→Varejo: {cat.get('cd_varejo',0)}")
    print()

    # Lead time
    lt = cockpit["lead_time"]
    print("⏱ LEAD TIME")
    cv = lt.get("cd_varejo", {})
    print(f"  CD→Varejo: ok={cv.get('ok',0)} / fail={cv.get('fail',0)}")
    print(f"  F1→CD: {'✅' if lt.get('f1_cd',{}).get('ok') else '❌'}")
    print(f"  Fornecedor→F1: {'✅' if lt.get('fornecedor_f1',{}).get('ok') else '❌'}")
    print()

    # OPs (só PAs reais — MPs descartados internamente do passo 4 viram outra seção)
    ops_pa = [o for o in cockpit["ops"] if str(o.get("pa", "")).startswith("PA")]
    ops_mp = [o for o in cockpit["ops"] if str(o.get("pa", "")).startswith("MP")]
    print("📋 OPs DO PROFESSOR")
    if ops_pa:
        df = pd.DataFrame(ops_pa)
        for col in ("receita_R$", "margem_pct"):
            if col in df.columns:
                df[col] = df[col].apply(lambda v: round(v, 2) if v is not None else None)
        print(df.to_string(index=False))
    else:
        print("  (nenhuma)")
    # recalcula taxa só sobre PAs reais
    n_pa = len(ops_pa)
    atendidas_pa = sum(1 for o in ops_pa if o.get("status") == "atendida")
    taxa = (atendidas_pa / n_pa * 100) if n_pa else 0.0
    print(f"  Taxa de atendimento: {atendidas_pa}/{n_pa} = {taxa:.1f}%")
    if ops_mp:
        print()
        print(f"⚙ Avisos de MP (passo 4 — {len(ops_mp)} alertas internos):")
        df_mp = pd.DataFrame(ops_mp)[["cidade", "pa", "qtd", "motivo"]]
        print(df_mp.to_string(index=False))
    print()

    # Financeiro
    fin = cockpit["financeiro"]
    print("💰 FINANCEIRO")
    print(f"  Receita:                       R$ {fin['receita']:>14,.2f}")
    print(f"  Frete Fornecedor→F1:           R$ {fin['custo_frete_fornecedor_f1']:>14,.2f}")
    print(f"  Frete F1→CD:                   R$ {fin['custo_frete_f1_cd']:>14,.2f}")
    print(f"  Frete CD→Varejo:               R$ {fin['custo_frete_cd_varejo']:>14,.2f}")
    print(f"  MP comprada:                   R$ {fin['custo_mp_comprada']:>14,.2f}")
    print(f"  Carregamento estoque:          R$ {(fin['custo_carregamento_mp']+fin['custo_carregamento_pa']):>14,.2f}")
    print(f"  Estruturais (rateio):          R$ {fin['custo_estruturais']:>14,.2f}")
    print(f"  ──────────────────────────────────────────────────────")
    print(f"  Custo Total:                   R$ {fin['custo_total']:>14,.2f}")
    print(f"  Margem da rodada:              R$ {fin['margem_R$']:>14,.2f} ({fin['margem_pct']:>5.1f}%)")
    print()


def preview_rodada_xlsm(path) -> None:
    """Imprime as 3 sheets relevantes da Rodada N.xlsm."""
    from src.io_xlsm import ler_instalacoes, ler_sol_transp
    inst = ler_instalacoes(path)
    print("=" * 63)
    print(f"  PREVIEW: {path.name}")
    print("=" * 63)
    print()
    print("📍 INSTALAÇÕES")
    print(f"  Empresa: {inst['empresa']}")
    for nome, f in inst["fabricas"].items():
        if f.get("cidade"):
            print(f"  {nome} em {f['cidade']}: {f['maquinas']} máq × {f['turnos']} turnos × {f['mo']} MO")
            print(f"    Áreas MP: MP1={f['area_mp']['MP1']}m² MP2={f['area_mp']['MP2']}m² MP3={f['area_mp']['MP3']}m²")
    for nome, c in inst["cds"].items():
        if c.get("cidade"):
            print(f"  {nome} em {c['cidade']}: PA1={c['area_pa']['PA1']}m² PA2={c['area_pa']['PA2']}m² PA3={c['area_pa']['PA3']}m² (tot {c['area_total']}m²)")
    print()

    items = ler_sol_transp(path)
    if items:
        df = pd.DataFrame([{
            "Rodada": t.rod_part, "Origem": t.origem_tipo,
            "Cidade Origem": t.origem_cidade, "Dia Coleta": t.dia_part,
            "Modal": t.modal, "Item": t.item, "Qtd": t.qtd,
            "Destino": t.destino_tipo, "Cidade Destino": t.destino_cidade,
            "Lead": (t.rod_cheg, t.dia_cheg),
        } for t in items])
        print(f"📋 SOL_TRANSP ({len(df)} linhas)")
        print(df.to_string(index=False))
    else:
        print("📋 SOL_TRANSP — vazio")
    print()
