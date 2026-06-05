"""Valida TODOS os fluxos do plano R3 dia a dia.

Para cada dia 1-5 e cada item, simula:
  1. MP em F1: estoque + arrivals - consumo. Verifica >= 0 e <= cap.
  2. Produção PA: respeita cap min/dia E disponibilidade MP cumulativa.
  3. F1 -> CD: PA produzido sai no MESMO dia (regra do jogo).
  4. CD -> Varejo: PA chega no dia EXATO. Não pode antes nem depois.
  5. Cap CD: PA estocado intermediariamente + buffer <= cap CD.
  6. Cap transportes (≤220/semana).
"""
import sys, io, json, re
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
from pathlib import Path
from collections import defaultdict
import math

BASE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE))
from src.config import Config
from src.io_xlsm import ler_instalacoes
from src.planner_v3 import planejar_v3, lead_dias

cfg = Config.load(BASE)
inst = ler_instalacoes(BASE/'rodadas/rodada_3/FLAMENGO.xlsm')
lead_tab = json.loads((BASE/'data/lead_times.json').read_text(encoding='utf-8'))

OPS = [{'cidade':c,'pa':'PA3','qtd':q,'dia_entrega':d} for c,q,d in [
    ('Belém',20155,5),('Belo Horizonte',70544,3),('Brasília',117573,3),
    ('Campinas',56435,2),('Campo Grande',23515,3),('Cuiabá',28218,3),
    ('Curitiba',103464,2),('Fortaleza',68528,5),('Goiânia',65841,3),
    ('João Pessoa',40311,4),('Joinville',28218,2),('Maceió',40311,4),
    ('Manaus',20155,5),('Natal',40311,5),('Porto Alegre',103464,2),
    ('Recife',60466,4),('Ribeirão Preto',47029,2),('Rio de Janeiro',94059,3),
    ('Salvador',80622,4),('Santos',47029,2),('São Luís',20155,5),
    ('São Paulo',117573,2),('Uberlândia',23515,3),('Vitória',14109,3),
    ('Vitória da Conquista',12093,4),
]]
ESTOQUE_MP = {'MP1':78.98,'MP2':50.36,'MP3':48.14}
EM_TRANSITO = [{'dia':1,'mp':'MP1','qtd':8.7}]
PRECO_PA3 = 32.00

res = planejar_v3(rodada_n=3, ops_rodada=OPS,
    estoque_inicial_mp_ton=ESTOQUE_MP,
    estoque_inicial_pa_cd={cd:{'PA1':0,'PA2':0,'PA3':0} for cd in inst['cds']},
    mp_em_transito_chegando=EM_TRANSITO, cfg=cfg, instalacoes=inst,
    pa_proxima_rodada='PA2', buffer_pa_proxima=400000,
    compras_mp_extra_para_r_mais_1={'MP1':48,'MP3':48})
df = res['df_sol_transp']
df_op = res['df_op_fabricas']
resumo = res['resumo']

print("="*80)
print("  VALIDAÇÃO COMPLETA — TODOS OS FLUXOS DIA A DIA")
print("="*80)

# --- INPUTS ---
cap_mp = {mp: inst['fabricas']['F1']['area_mp'][mp] * 2 * cfg.densidades_mp[mp]
          for mp in ('MP1','MP2','MP3')}
cap_pa_cd = {cd: {pa: int(inst['cds'][cd]['area_pa'][pa] * 2 * cfg.densidades_pa[pa]
                          / cfg.peso_un_ton[pa])
                  for pa in ('PA1','PA2','PA3')} for cd in inst['cds']}
cap_min_dia = inst['fabricas']['F1']['maquinas'] * inst['fabricas']['F1']['turnos'] * 8 * 60
vel = {'PA1':15,'PA2':30,'PA3':60}
_DIA = re.compile(r'Dia\s*(\d+)')

# --- PARSE TRANSPORTES POR DIA ---
# transp[dia_part][tipo][item] = lista de (origem, destino, qtd, modal, lt)
transp_por_dia = defaultdict(list)
for _, row in df.iterrows():
    dia = int(_DIA.search(str(row['Dia da Coleta'])).group(1))
    modal = row['Modal']
    item = row['Tipo do Produto']
    qtd = float(row['Qtde'])
    o, d = row['Cidade'], row['Cidade_Destino']
    lt = lead_dias(cfg, o, d, modal) or 0
    transp_por_dia[dia].append({
        'origem_tipo': row['Origem'], 'origem_cid': o,
        'destino_tipo': row['Destino'], 'destino_cid': d,
        'modal': modal, 'item': item, 'qtd': qtd, 'lt': lt,
        'dia_chega': dia + lt,
    })

# --- PARSE PRODUÇÃO POR DIA ---
prod_por_dia = {}
for _, row in df_op.iterrows():
    dia = int(row['Dia'].split()[-1])
    prod_por_dia[dia] = {pa: int(row[pa]) for pa in ('PA1','PA2','PA3')}

# ============ TESTE 1: CAP TRANSPORTES ============
print("\n--- TESTE 1: Capacidade total de transportes ≤ 220 ---")
n_total = len(df)
print(f"  Total viagens R3: {n_total} (limite 220)")
print(f"  {'✅ OK' if n_total <= 220 else '❌ FALHA'}")

# ============ TESTE 2: PRODUÇÃO RESPEITA CAP MIN/DIA ============
print("\n--- TESTE 2: Produção respeita capacidade de máquinas (10080 min/dia) ---")
falhas_cap = 0
for dia in range(1, 6):
    p = prod_por_dia.get(dia, {})
    min_usado = sum(p.get(pa, 0) / vel[pa] for pa in ('PA1','PA2','PA3'))
    ok = min_usado <= cap_min_dia + 1
    print(f"  Dia {dia}: {min_usado:.0f}/{cap_min_dia} min ({min_usado/cap_min_dia*100:.1f}%) {'✅' if ok else '❌'}")
    if not ok: falhas_cap += 1
print(f"  {'✅ OK' if falhas_cap == 0 else f'❌ {falhas_cap} FALHAS'}")

# ============ TESTE 3: ESTOQUE MP DIA A DIA ============
print("\n--- TESTE 3: Estoque MP nunca negativo nem excede cap ---")
stock_mp = dict(ESTOQUE_MP)
# Pre-aggreg arrivals por dia
chegadas_mp = defaultdict(lambda: defaultdict(float))
for it in EM_TRANSITO:
    chegadas_mp[it['dia']][it['mp']] += it['qtd']
for dia, lst in transp_por_dia.items():
    for t in lst:
        if t['origem_tipo'] == 'Fornecedor' and t['destino_tipo'] == 'Fábrica':
            dia_cheg = t['dia_chega']
            if 1 <= dia_cheg <= 5:
                chegadas_mp[dia_cheg][t['item']] += t['qtd']

falhas_mp = 0
descartes_mp = 0
for dia in range(1, 6):
    p = prod_por_dia.get(dia, {})
    print(f"  Dia {dia}:")
    for mp in ('MP1','MP2','MP3'):
        pre = stock_mp[mp]
        arr = chegadas_mp[dia][mp]
        pos_arr = pre + arr
        desc = max(0, pos_arr - cap_mp[mp])
        pos_arr_real = min(pos_arr, cap_mp[mp])
        # Consumo MP por toda produção do dia
        cons = sum(p.get(pa, 0) * cfg.BoM[pa][mp] / 1e6 for pa in ('PA1','PA2','PA3'))
        end = pos_arr_real - cons
        flag = ''
        if end < -0.01:
            flag = '❌ NEG'
            falhas_mp += 1
        if desc > 0.01:
            flag += f' ⚠️ DESCART {desc:.2f}t'
            descartes_mp += 1
        if end > cap_mp[mp] + 0.01:
            flag += ' ❌ EXCEDE CAP'
            falhas_mp += 1
        print(f"    {mp}: pre={pre:.2f} +arr={arr:.2f} pos={pos_arr_real:.2f}/cap{cap_mp[mp]:.1f} -cons={cons:.2f} = end {end:.2f} {flag}")
        stock_mp[mp] = max(0, end)
print(f"  {'✅ OK' if falhas_mp == 0 and descartes_mp == 0 else f'❌ {falhas_mp} negs, {descartes_mp} descartes'}")

# ============ TESTE 4: PA SAI DA F1 NO MESMO DIA DA PRODUÇÃO ============
print("\n--- TESTE 4: PA produzido sai da F1 NO MESMO DIA (regra do jogo) ---")
# Para cada dia, soma PA produzido vs PA enviado F1→CD nesse dia
falhas_f1 = 0
for dia in range(1, 6):
    prod = prod_por_dia.get(dia, {})
    enviado_f1 = defaultdict(float)
    for t in transp_por_dia.get(dia, []):
        if t['origem_tipo'] == 'Fábrica' and t['destino_tipo'] == 'CD':
            enviado_f1[t['item']] += t['qtd']
    print(f"  Dia {dia}:")
    for pa in ('PA1','PA2','PA3'):
        prod_p = prod.get(pa, 0)
        env = enviado_f1.get(pa, 0)
        diff = prod_p - env
        # PA produzido deve igualar enviado (ou < 1 viagem por rounding)
        if prod_p > 0 and abs(diff) > max(prod_p * 0.001, 5):
            print(f"    {pa}: produzido {prod_p:>7,} enviado F1→CD {env:>7,.0f} diff {diff:+,} ❌")
            falhas_f1 += 1
        elif prod_p > 0:
            print(f"    {pa}: produzido {prod_p:>7,} enviado F1→CD {env:>7,.0f} ✅")
print(f"  {'✅ OK' if falhas_f1 == 0 else f'❌ {falhas_f1} dias com discrepância'}")

# ============ TESTE 5: PA CHEGA AO VAREJO NO DIA EXATO ============
print("\n--- TESTE 5: Toda entrega chega no varejo no DIA EXATO solicitado ---")
# Para cada OP, encontra as viagens CD→Varejo correspondentes
entregas_por_op = defaultdict(lambda: {'qtd_planejada': 0, 'qtd_entregue_no_dia': 0, 'dia_entrega': 0, 'lst': []})
for op in OPS:
    key = (op['cidade'], op['pa'])
    entregas_por_op[key]['qtd_planejada'] = op['qtd']
    entregas_por_op[key]['dia_entrega'] = op['dia_entrega']

for dia, lst in transp_por_dia.items():
    for t in lst:
        if t['origem_tipo'] == 'CD' and t['destino_tipo'] == 'Varejista':
            key = (t['destino_cid'], t['item'])
            if key in entregas_por_op:
                dia_cheg = t['dia_chega']
                if dia_cheg == entregas_por_op[key]['dia_entrega']:
                    entregas_por_op[key]['qtd_entregue_no_dia'] += t['qtd']
                entregas_por_op[key]['lst'].append((dia, dia_cheg, t['qtd'], t['modal']))

falhas_v = 0
for key, info in entregas_por_op.items():
    cidade, pa = key
    plan = info['qtd_planejada']
    ent = info['qtd_entregue_no_dia']
    if abs(plan - ent) > 1:
        print(f"  ❌ {cidade:<22} dia {info['dia_entrega']}: planejado {plan:,} entregue no dia {ent:,.0f}")
        falhas_v += 1
print(f"  ✅ 25/25 OPs entregues qty exata no dia exato" if falhas_v == 0 else f"  ❌ {falhas_v} falhas")

# ============ TESTE 6: CD CONSEGUIU TER O PA QUE ENVIOU ============
print("\n--- TESTE 6: Cada CD tem PA suficiente no momento que despacha ---")
# Simula estoque CD dia a dia
stock_cd = {cd: {'PA1':0,'PA2':0,'PA3':0} for cd in inst['cds']}
falhas_cd = 0
cidade_to_cd = {inst['cds'][cd]['cidade']: cd for cd in inst['cds']}

for dia in range(1, 6):
    chegadas_cd = defaultdict(lambda: defaultdict(float))  # [cd_cidade][pa]
    saidas_cd = defaultdict(lambda: defaultdict(float))
    # PA chegando ao CD HOJE (do F1, considerando lt)
    for d2 in range(1, 6):
        for t in transp_por_dia.get(d2, []):
            if t['destino_tipo'] == 'CD' and t['dia_chega'] == dia:
                chegadas_cd[t['destino_cid']][t['item']] += t['qtd']
    # PA saindo do CD HOJE
    for t in transp_por_dia.get(dia, []):
        if t['origem_tipo'] == 'CD':
            saidas_cd[t['origem_cid']][t['item']] += t['qtd']

    for cd, cd_info in inst['cds'].items():
        cid = cd_info['cidade']
        for pa in ('PA1','PA2','PA3'):
            pre = stock_cd[cd][pa]
            arr = chegadas_cd[cid][pa]
            sai = saidas_cd[cid][pa]
            # Stock disponível para enviar = pre + arrival (assumindo same-day)
            disponivel = pre + arr
            if sai > disponivel + 1:
                print(f"  Dia {dia} {cd} ({cid}) {pa}: ENVIA {sai:,.0f} mas só tem {disponivel:,.0f} ❌")
                falhas_cd += 1
            end = disponivel - sai
            if end > cap_pa_cd[cd][pa] + 1:
                print(f"  Dia {dia} {cd} ({cid}) {pa}: estoque {end:,.0f} excede cap {cap_pa_cd[cd][pa]:,} ❌")
                falhas_cd += 1
            stock_cd[cd][pa] = end
print(f"  {'✅ OK — CD sempre tem o PA que despacha' if falhas_cd == 0 else f'❌ {falhas_cd} falhas'}")

# ============ TESTE 7: BUFFER PA2 EM SANTOS FIM DA RODADA ============
print("\n--- TESTE 7: Buffer PA2 final no CD ≤ capacidade CD ---")
stock_final_pa = stock_cd
print(f"  CD2 Santos PA2 final: {stock_final_pa['CD2']['PA2']:,.0f} (cap {cap_pa_cd['CD2']['PA2']:,})")
print(f"  CD1 São Luís PA2 final: {stock_final_pa['CD1']['PA2']:,.0f} (cap {cap_pa_cd['CD1']['PA2']:,})")
ok_buf = all(stock_final_pa[cd]['PA2'] <= cap_pa_cd[cd]['PA2'] for cd in inst['cds'])
print(f"  {'✅ OK' if ok_buf else '❌ EXCEDE'}")

# ============ TESTE 8: COMPRAS MP — FORNECEDOR MAIS BARATO ============
print("\n--- TESTE 8: Cada MP comprada do fornecedor mais barato ---")
forn_min = {mp: min(cfg.fornecedores[mp], key=lambda x: x[1]) for mp in ('MP1','MP2','MP3')}
falhas_forn = 0
for _, row in df[df.Origem=='Fornecedor'].iterrows():
    mp = row['Tipo do Produto']
    cid = row['Cidade']
    if cid != forn_min[mp][0]:
        print(f"  ❌ {mp} de {cid} (mais caro): R$ {[c for f,c in cfg.fornecedores[mp] if f==cid][0]:,}/ton vs ótimo {forn_min[mp][0]} R$ {forn_min[mp][1]:,}")
        falhas_forn += 1
print(f"  {'✅ OK — sempre fornecedor mais barato' if falhas_forn == 0 else f'❌ {falhas_forn} pedidos de fornecedor caro'}")

# ============ RESUMO ============
print("\n" + "="*80)
print("  RESUMO DA VALIDAÇÃO COMPLETA")
print("="*80)
total_falhas = (1 if n_total > 220 else 0) + falhas_cap + falhas_mp + falhas_f1 + falhas_v + falhas_cd + (0 if ok_buf else 1) + falhas_forn
checks = [
    ("Transportes ≤ 220", n_total <= 220, f"{n_total}/220"),
    ("Produção respeita cap min/dia", falhas_cap == 0, f"max {max(sum(prod_por_dia.get(d,{}).get(pa,0)/vel[pa] for pa in vel) for d in range(1,6)):.0f} min/dia"),
    ("Estoque MP positivo + cap respeitada", falhas_mp == 0 and descartes_mp == 0, "dia a dia validado"),
    ("PA sai F1 mesmo dia produção", falhas_f1 == 0, "Σ prod = Σ envio F1→CD"),
    ("Entregas no dia EXATO", falhas_v == 0, "25/25 OPs"),
    ("CD tem PA no momento de despachar", falhas_cd == 0, "stock CD nunca neg."),
    ("Buffer PA2 ≤ cap CD", ok_buf, f"{stock_final_pa['CD2']['PA2']:,.0f}/400.000"),
    ("MP comprada do fornec mais barato", falhas_forn == 0, "Manaus/Cuiabá/PA"),
]
for desc, ok, detail in checks:
    print(f"  {'✅' if ok else '❌'} {desc:<45} {detail}")
print()
print(f"  TOTAL FALHAS: {total_falhas}")
print(f"  {'✅ TODOS OS FLUXOS VALIDADOS' if total_falhas == 0 else '❌ PLANO TEM PROBLEMAS — REFAZER'}")
