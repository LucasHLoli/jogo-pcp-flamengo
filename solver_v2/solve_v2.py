"""Entry point do solver_v2 — resolve R4 + cenários R5, grava Excel e relata
DRE/indicadores/estoque final completos.

Uso: python solver_v2/solve_v2.py [--time_limit 240] [--alpha 100]
"""
from __future__ import annotations
import argparse
import io
import shutil
import sys
import warnings
from pathlib import Path

warnings.filterwarnings("ignore")
BASE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE))

import pandas as pd
from src.config import Config
from src.io_xlsm import escrever_planos_de_df
from solver.state import (estado_r4_flamengo, estado_r5_flamengo,
                           estado_r6_flamengo, estado_r7_flamengo,
                           estado_r8_flamengo, estado_r9_flamengo, estado_r10_flamengo,
                           estado_r11_flamengo)
from solver.solve import ops_r4, ops_r5, ops_r6, ops_r7, ops_r8, ops_r9, ops_r10, ops_r11
from solver.milp import (PAS, MPS, MODAIS, BOM, VEL_UN_MIN, CAP_MODAL_TON,
                         FRETE_VIAGEM, FRETE_PESO, PESO_UN_TON, DOC_MODAL, _cap_un)
from solver_v2.milp_multi import resolver_multi, DIAS
from solver_v2.forecast_v2 import prever_proximas  # gerador exato (curva × peso_jogo); HW em forecast.py

# preço do produto da rodada (o resto não vende) + preços assumidos p/ cenários futuros
PRECO_POR_RODADA = {4: {"PA1": 80, "PA2": 50, "PA3": 20},
                    5: {"PA1": 69, "PA2": 50, "PA3": 32},
                    6: {"PA1": 69, "PA2": 48, "PA3": 32},  # PA2 R6 = R$48 (IND)
                    7: {"PA1": 80, "PA2": 44, "PA3": 32},  # PA2 R7 = R$44 (IND rodada_7)
                    8: {"PA1": 80, "PA2": 50, "PA3": 24},  # PA3 R8 = R$24 (IND rodada_8)
                    9: {"PA1": 80, "PA2": 55, "PA3": 32},  # PA2 R9 = R$55 (IND rodada_9)
                    10: {"PA1": 80, "PA2": 55, "PA3": 27},  # PA3 R10 = R$27 (IND rodada_10)
                    11: {"PA1": 77, "PA2": 55, "PA3": 27}}  # PA1 R11 = R$77 (IND rodada_11)
ESTADO_OPS = {4: (estado_r4_flamengo, ops_r4), 5: (estado_r5_flamengo, ops_r5),
              6: (estado_r6_flamengo, ops_r6), 7: (estado_r7_flamengo, ops_r7),
              8: (estado_r8_flamengo, ops_r8), 9: (estado_r9_flamengo, ops_r9),
              10: (estado_r10_flamengo, ops_r10), 11: (estado_r11_flamengo, ops_r11)}
PRECO_FUT = {"PA1": 80, "PA2": 50, "PA3": 32}
FIX = {"Parcela terrenos": -506968, "Parcela máquinas": -415567, "Contratação MO": -84,
       "Manut fábricas": -1313, "Salário operários": -450, "Custo produção": -172086,
       "Manut CDs": -26683}
MAIOR_MP = {"MP1": 56000, "MP2": 22000, "MP3": 41000}
# Valor de referência FIXO p/ carregamento de PA (1% = R$/frasco/rodada), independente
# do preço de venda da rodada. Calibrado vs Estoques R6: PA1 R$0,80 / PA2 R$0,50 / PA3 R$0,25.
MAIOR_PA = {"PA1": 80, "PA2": 50, "PA3": 25}


def g(v):
    try:
        return float(v.x or 0.0)
    except Exception:
        return float(v or 0.0)


# Frete CALIBRADO vs DRE realizada R6/R7/R8/R9 (4 rodadas).
# EVOLUÇÃO: o fudge "avião=11,6 sem doc" cravava rodadas de demanda ESPALHADA (R6/R7, PA2),
# mas SUBESTIMAVA ~8-10% as rodadas de ENTREGA-NUM-DIA-SÓ (R8/R9, muita carga parcial).
# Como R8/R9/R10 são todas entrega-num-dia (novo padrão do jogo), revertemos pro modelo
# PRINCIPISTA do rulebook: taxa de viagem NOMINAL + CT-e/documento por transporte (que
# estávamos ignorando). Resultado nas 4 rodadas (erro do frete de PA): R6 +3,0% · R7 +5,5%
# · R8 -4,5% · R9 -2,4% (pior 5,5%, vs 9,8% antes). O doc estava "embutido" no 11,6;
# explicitá-lo + voltar ao nominal corrige o viés nas rodadas de carga parcial. Meia-viagem
# do rulebook foi testada e ESTOURA (jogo não aplica). Ver project_regra_frete_calibrada.
FRETE_VIAGEM_CAL = dict(FRETE_VIAGEM)   # nominal (avião=12); doc tratado à parte


def frete_exato(modal, kv, qty, n, item):
    """Frete POR-TRANSPORTE (não pela média do grupo): cada veículo é carregado até a
    capacidade e o último leva o resto; ocup≥80%→frete-viagem, ocup<80%→frete-peso puro.
    SOMA o CT-e/documento (DOC_MODAL) por veículo — custo real do rulebook. Meia-viagem
    do rulebook NÃO é aplicada (testada vs DRE real: estoura)."""
    if kv <= 0 or n <= 0:
        return 0.0
    cap_un = _cap_un(modal, item)                      # unidades (PA) ou ton (MP) por viagem
    peso_un = PESO_UN_TON[item] if item in PAS else 1.0
    cap_ton = CAP_MODAL_TON[modal]
    fv, fp, doc = FRETE_VIAGEM_CAL[modal], FRETE_PESO[modal], DOC_MODAL[modal]
    rest, total = qty, 0.0
    for _ in range(n):
        carga = min(rest, cap_un)
        if carga <= 0:
            break
        peso_v = carga * peso_un                       # peso do veículo em ton
        total += (fv * kv if (peso_v / cap_ton) >= 0.8 else fp * kv * peso_v) + doc
        rest -= carga
    return total


def extrair_plano(b, rodada, km_fn):
    """Constrói df_sol_transp e df_op_fabricas do bloco R4 + frete exato total."""
    fab, cds_info, forn_info = b.fab, b.cds_info, b.forn_info
    linhas = []
    frete_tot = 0.0
    # Fornecedor -> F1
    for (t, mp, fi), vn in b.n_buy.items():
        nv = int(round(g(vn)))
        qty = g(b.qty_buy[(t, mp, fi)])
        if nv <= 0 or qty <= 0.01:
            continue
        forn = forn_info[mp][fi][0]
        modal_mp = forn_info[mp][fi][2]                # MP multimodal (Caminhão/Avião/Navio)
        frete_tot += frete_exato(modal_mp, km_fn(modal_mp, forn, fab), qty, nv, mp)
        qp = qty / nv
        for _ in range(nv):
            linhas.append({"Rodada": f"Rodada_{rodada}", "Origem": "Fornecedor", "Cidade": forn,
                           "Dia da Coleta": f"Dia {t}", "Modal": modal_mp, "Tipo do Produto": mp,
                           "Qtde": round(qp, 2), "Destino": "Fábrica", "Cidade_Destino": fab})
    # F1 -> CD
    for key, vn in b.n_f1cd.items():
        t, cd, pa, mod = key
        nv = int(round(g(vn)))
        qty = g(b.qty_f1cd[key])
        if nv <= 0 or qty <= 0.5:
            continue
        frete_tot += frete_exato(mod, km_fn(mod, fab, cds_info[cd]), qty, nv, pa)
        cap = _cap_un(mod, pa); rest = int(round(qty))
        for _ in range(nv):
            q = min(rest, cap)
            if q <= 0: continue
            linhas.append({"Rodada": f"Rodada_{rodada}", "Origem": "Fábrica", "Cidade": fab,
                           "Dia da Coleta": f"Dia {t}", "Modal": mod, "Tipo do Produto": pa,
                           "Qtde": q, "Destino": "CD", "Cidade_Destino": cds_info[cd]})
            rest -= q
    # CD -> Varejo
    for key, vn in b.n_cdv.items():
        t, cd, c, pa, mod = key
        nv = int(round(g(vn)))
        qty = g(b.qty_cdv[key])
        if nv <= 0 or qty <= 0.5:
            continue
        frete_tot += frete_exato(mod, km_fn(mod, cds_info[cd], c), qty, nv, pa)
        cap = _cap_un(mod, pa); rest = int(round(qty))
        for _ in range(nv):
            q = min(rest, cap)
            if q <= 0: continue
            linhas.append({"Rodada": f"Rodada_{rodada}", "Origem": "CD", "Cidade": cds_info[cd],
                           "Dia da Coleta": f"Dia {t}", "Modal": mod, "Tipo do Produto": pa,
                           "Qtde": q, "Destino": "Varejista", "Cidade_Destino": c})
            rest -= q
    df_sol = pd.DataFrame(linhas, columns=["Rodada", "Origem", "Cidade", "Dia da Coleta",
                                           "Modal", "Tipo do Produto", "Qtde", "Destino", "Cidade_Destino"])
    df_op = pd.DataFrame([{"Dia": f"Dia {t}", **{pa: int(round(g(b.prod[(t, pa)]))) for pa in PAS}} for t in DIAS])
    return df_sol, df_op, frete_tot


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--time_limit", type=float, default=240)
    p.add_argument("--alpha", type=float, default=100.0)
    p.add_argument("--no_write", action="store_true")
    p.add_argument("--no_relax", action="store_true", help="cenários MILP cheio (sem relaxar) — comparação")
    p.add_argument("--horizonte", type=int, default=3, help="rodadas futuras (1=R5, 3=R5+R6+R7)")
    p.add_argument("--gurobi", action="store_true", help="usa Gurobi (licença WLS) em vez do CBC")
    p.add_argument("--rodada", type=int, default=5, help="rodada a resolver (4 ou 5)")
    args = p.parse_args()

    cfg = Config.load(BASE)
    rodada = args.rodada
    estado = ESTADO_OPS[rodada][0]()
    ops = ESTADO_OPS[rodada][1]()
    precos = PRECO_POR_RODADA[rodada]
    produto = ops[0]["pa"]                          # produto da rodada (todos iguais)
    preco_prod = precos[produto]
    day_map = {o["cidade"]: o["dia_entrega"] for o in ops}
    fc = prever_proximas(3, rodada_atual=rodada)  # gerador exato: prevê rodada+1..+3

    res = resolver_multi(estado, ops, precos, cfg, forecast=fc, day_map=day_map,
                         precos_futuro=PRECO_FUT, alpha=args.alpha,
                         time_limit_s=args.time_limit, verbose=False,
                         relax_cenarios=not args.no_relax, n_future=args.horizonte,
                         solver_name=(__import__("mip").GUROBI if args.gurobi else __import__("mip").CBC))
    b = res.bloco_R
    df_sol, df_op, frete = extrair_plano(b, rodada, res.km_fn)

    # DRE exata
    receita = sum(o["qtd"] * precos[o["pa"]] for i, o in enumerate(b.ops) if g(b.x_op[i]) > 0.5)
    served = sum(o["qtd"] for i, o in enumerate(b.ops) if g(b.x_op[i]) > 0.5)
    total = sum(o["qtd"] for o in b.ops)
    # Custo MP ROBUSTO: derivado do BALANÇO de estoque (confiável) e não da leitura
    # de qty_buy (que pode vir inconsistente em solução FEASIBLE). Preço = forn mais barato.
    CHEAP = {mp: min(c for _, c in __import__("src.config", fromlist=["Config"]).Config.load(BASE).fornecedores[mp]) for mp in MPS}
    _consumo = {mp: sum(g(b.prod[(t, pa)]) * BOM[pa][mp] / 1e6 for t in DIAS for pa in PAS) for mp in MPS}
    _transito = {mp: sum(float(x["qtd"]) for x in estado.mp_em_transito if x["mp"] == mp) for mp in MPS}
    _ini = {mp: estado.estoque_mp_ton.get(mp, 0.0) for mp in MPS}
    _comprado_bal = {mp: max(0.0, g(b.stk_mp[(5, mp)]) + _consumo[mp] - _ini[mp] - _transito[mp]) for mp in MPS}
    _comprado_qbuy = {mp: sum(g(b.qty_buy[(t, mp, fi)]) for fi in range(len(b.forn_info[mp])) for t in DIAS) for mp in MPS}
    custo_mp = sum(_comprado_bal[mp] * CHEAP[mp] for mp in MPS)
    _mp_diag = {mp: (_comprado_bal[mp], _comprado_bal[mp] * CHEAP[mp]) for mp in MPS}
    stk_mp5 = {mp: g(b.stk_mp[(5, mp)]) for mp in MPS}
    stk_pa5 = {(cd, pa): g(b.stk_pa[(5, cd, pa)]) for cd in b.cds_info for pa in PAS}
    # Carregamento de MP: 0,1%/rodada (×0.001) sobre o estoque do último dia EXCLUINDO a MP
    # que CHEGOU no dia 5 (compra-buffer recém-recebida não paga carregamento). Validado vs
    # DRE real R8 (MP1 cravou 420,09; total 2.355 vs 2.340 real). Base fixa = MAIOR_MP, não preço.
    _consumo5 = {mp: sum(g(b.prod[(5, pa)]) * BOM[pa][mp] / 1e6 for pa in PAS) for mp in MPS}
    _receb5_mp = {mp: max(0.0, stk_mp5[mp] - g(b.stk_mp[(4, mp)]) + _consumo5[mp]) for mp in MPS}
    base_carreg_mp = {mp: max(0.0, stk_mp5[mp] - _receb5_mp[mp]) for mp in MPS}
    carreg_mp = sum(base_carreg_mp[mp] * MAIOR_MP[mp] * 0.001 for mp in MPS)
    carreg_pa = sum(stk_pa5[(cd, pa)] * MAIOR_PA[pa] * 0.01 for cd in b.cds_info for pa in PAS)  # PA: base fixa MAIOR_PA, dia-5 cheio (cravou)
    fix_tot = sum(FIX.values())
    resultado = receita - custo_mp - frete - carreg_mp - carreg_pa + fix_tot

    # Indicadores
    minutos = {t: sum(g(b.prod[(t, pa)]) / VEL_UN_MIN[pa] for pa in PAS) for t in DIAS}
    util = sum(minutos.values()) / (5 * estado.cap_min_dia) * 100
    # Transportes REAIS = linhas efetivamente escritas no envio (df_sol), e não a
    # leitura crua de n_buy/n_f1cd/n_cdv: o MILP pode deixar caminhões "fantasma"
    # (n>0 com carga ≈0 ton) que NÃO vão pro envio mas inflavam a contagem (bug do
    # "220/220" / "MP 166"). df_sol é a fonte da verdade — 1 linha = 1 caminhão.
    trips_mp = int((df_sol["Origem"] == "Fornecedor").sum())
    trips_f1 = int((df_sol["Origem"] == "Fábrica").sum())
    trips_cd = int((df_sol["Origem"] == "CD").sum())

    out = io.StringIO()
    P = lambda s="": out.write(s + "\n")
    P("=" * 64); P(f"  SOLVER v2 — RODADA {rodada} — PLANO E PREVISÃO"); P("=" * 64)
    P(f"  Status: {res.status}  ({res.runtime_s:.0f}s)  alpha={args.alpha:.0f}")
    P("")
    P("─" * 64); P(f"  DRE PREVISTA — R{rodada}"); P("─" * 64)
    P(f"  Receita {produto} ({served:,} un × R${preco_prod})    R$ {receita:>15,.0f}")
    P(f"  (-) Compra MP                            R$ {-custo_mp:>15,.0f}")
    P(f"  (-) Frete (regra calibrada)              R$ {-frete:>15,.0f}")
    P(f"  (-) Carregamento MP (buffer)             R$ {-carreg_mp:>15,.0f}")
    P(f"  (-) Carregamento PA (PA2 parado)         R$ {-carreg_pa:>15,.0f}")
    for k, v in FIX.items():
        P(f"  (-) {k:<36} R$ {v:>15,.0f}")
    P("  " + "-" * 58)
    P(f"  RESULTADO R{rodada}                             R$ {resultado:>15,.0f}")
    P("")
    P("─" * 64); P(f"  INDICADORES PREVISTOS — R{rodada}"); P("─" * 64)
    P(f"  Nível de Serviço (NS)        {served/total*100:>6.1f}%   ({served:,} de {total:,} frascos)")
    P(f"  Utilização fábrica média     {util:>6.1f}%")
    P(f"  Min usados/dia               {dict((t, round(v)) for t, v in minutos.items())}")
    P(f"  Transportes                  {trips_mp+trips_f1+trips_cd}/220  (MP {trips_mp} | F1→CD {trips_f1} | CD→V {trips_cd})")
    P("")
    P("─" * 64); P(f"  ESTOQUE FINAL R{rodada} (= buffer pra próxima)"); P("─" * 64)
    P(f"  MP no F1 (ton):  MP1 {stk_mp5['MP1']:.1f}  MP2 {stk_mp5['MP2']:.1f}  MP3 {stk_mp5['MP3']:.1f}")
    P("  [balanço MP]  comprado(balanço,t) | qty_buy lida(t) | consumo(t) | fim(t)")
    for mp in MPS:
        flag = "ok" if abs(_comprado_bal[mp] - _comprado_qbuy[mp]) < 2 else "≠qty_buy"
        P(f"    {mp}: compra {_comprado_bal[mp]:.1f}t (R$ {_mp_diag[mp][1]:,.0f}) | qty_buy {_comprado_qbuy[mp]:.1f}t [{flag}] | consumo {_consumo[mp]:.1f} | fim {stk_mp5[mp]:.1f}")
    for cd in b.cds_info:
        pas = {pa: int(stk_pa5[(cd, pa)]) for pa in PAS if stk_pa5[(cd, pa)] > 1}
        if pas:
            P(f"  PA em {cd} ({b.cds_info[cd]}): {pas}")
    P("")
    P("─" * 64); P("  PREVISÃO DOS CENÁRIOS FUTUROS (com o buffer; 1/3 cada)"); P("─" * 64)
    for rod in range(rodada + 1, rodada + 1 + args.horizonte):
        partes = []
        for pa in PAS:
            d = res.blocos.get(f"R{rod}_{pa}")
            if d:
                partes.append(f"{pa}: NS {d['ns_pct']:.0f}% (R$ {d['lucro']/1e6:.1f}M)")
        if partes:
            P(f"  R{rod}  →  " + "  |  ".join(partes))
    relatorio = out.getvalue()
    (BASE / "solver_v2" / f"RELATORIO_R{rodada}.txt").write_text(relatorio, encoding="utf-8")
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
    print(relatorio)

    if not args.no_write:
        outdir = BASE / "solver_v2" / "rodadas" / f"rodada_{rodada}"
        outdir.mkdir(parents=True, exist_ok=True)
        dest = outdir / "FLAMENGO.xlsm"
        shutil.copy(BASE / "rodadas" / f"rodada_{rodada}" / "FLAMENGO.xlsm", dest)
        n = escrever_planos_de_df(dest, df_sol, df_op, rodada_n=rodada)
        print(f"\n✅ Excel gerado: {dest}  ({n} linhas SOL_TRANSP R{rodada})")


if __name__ == "__main__":
    main()
