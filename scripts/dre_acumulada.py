"""DRE acumulada Rodada 1 + Rodada 2 + projeção R3-R15."""
import sys
import math
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')

# =================== R1 (do DRE oficial do prof) ===================
R1 = {
    'rodada': 'R1 (Set-up + Operação)',
    'receita': 0,
    'parcela_terrenos': 506_968,
    'parcela_maquinas': 415_567,
    'parcela_contratacao': 84,
    'manut_fabricas': 1_313,
    'salario_operarios': 450,
    'custo_producao': 172_086,
    'mp_comprada': 4_368_000,
    'manut_cds': 26_683,
    'frete_mp': 105_666,
    'frete_pa': 95,
    'carreg_mp': 5_410,
    'carreg_pa': 0,
    'setup_terrenos': 17_258_500,
    'setup_maquinas': 10_500_000,
    'setup_contratacao': 4_050,
}
R1['custo_total_set_up'] = R1['setup_terrenos'] + R1['setup_maquinas'] + R1['setup_contratacao']
R1['custo_total_operacional'] = (
    R1['parcela_terrenos'] + R1['parcela_maquinas'] + R1['parcela_contratacao']
    + R1['manut_fabricas'] + R1['salario_operarios'] + R1['custo_producao']
    + R1['mp_comprada'] + R1['manut_cds']
    + R1['frete_mp'] + R1['frete_pa']
    + R1['carreg_mp'] + R1['carreg_pa']
)
R1['resultado'] = R1['receita'] - R1['custo_total_operacional']
R1['acumulado_com_setup'] = -(R1['custo_total_set_up'] + R1['custo_total_operacional'])

# =================== R2 (do nosso planejamento) ===================
R2 = {
    'rodada': 'R2 (PA1 atendido 60%)',
    'receita_pa1': 17_093_120,
    'receita_pa2': 0,
    'receita_pa3': 0,
    'parcela_terrenos': 506_968,
    'parcela_maquinas': 415_567,
    'parcela_contratacao': 84,
    'manut_fabricas': 1_313,
    'salario_operarios': 450,
    'custo_producao': 172_086,
    'manut_cds': 26_683,
    'mp_comprada': 4_622_400,  # incluindo buffer R3
    'frete_mp': 136_524,
    'frete_pa': 6_427_822,
    'carreg_mp': 79_923,
    'carreg_pa': 0,
}
R2['receita'] = R2['receita_pa1'] + R2['receita_pa2'] + R2['receita_pa3']
R2['custo_total'] = (
    R2['parcela_terrenos'] + R2['parcela_maquinas'] + R2['parcela_contratacao']
    + R2['manut_fabricas'] + R2['salario_operarios'] + R2['custo_producao']
    + R2['manut_cds']
    + R2['mp_comprada'] + R2['frete_mp'] + R2['frete_pa']
    + R2['carreg_mp'] + R2['carreg_pa']
)
R2['resultado'] = R2['receita'] - R2['custo_total']

# =================== Imprime tabela DRE ===================
print('=' * 90)
print('  DRE — FLAMENGO — Acumulado R1 + R2')
print('=' * 90)

linhas = [
    ('RECEITA', None, None, None),
    ('  Vendas PA1', 0, R2['receita_pa1'], R2['receita_pa1']),
    ('  Vendas PA2', 0, 0, 0),
    ('  Vendas PA3', 0, 0, 0),
    ('  TOTAL RECEITA', 0, R2['receita'], R2['receita']),
    ('', None, None, None),
    ('INVESTIMENTO INICIAL (Set-up)', None, None, None),
    ('  Aquisição terrenos', R1['setup_terrenos'], 0, R1['setup_terrenos']),
    ('  Aquisição máquinas', R1['setup_maquinas'], 0, R1['setup_maquinas']),
    ('  Contratação inicial', R1['setup_contratacao'], 0, R1['setup_contratacao']),
    ('  SUB-TOTAL SET-UP', R1['custo_total_set_up'], 0, R1['custo_total_set_up']),
    ('', None, None, None),
    ('PARCELAS DE FINANCIAMENTO (por rodada)', None, None, None),
    ('  Parcela terrenos', R1['parcela_terrenos'], R2['parcela_terrenos'], R1['parcela_terrenos']+R2['parcela_terrenos']),
    ('  Parcela máquinas', R1['parcela_maquinas'], R2['parcela_maquinas'], R1['parcela_maquinas']+R2['parcela_maquinas']),
    ('  Parcela contratação', R1['parcela_contratacao'], R2['parcela_contratacao'], R1['parcela_contratacao']+R2['parcela_contratacao']),
    ('', None, None, None),
    ('OPERAÇÃO FÁBRICA', None, None, None),
    ('  Manut fábricas', R1['manut_fabricas'], R2['manut_fabricas'], R1['manut_fabricas']+R2['manut_fabricas']),
    ('  Salário operários', R1['salario_operarios'], R2['salario_operarios'], R1['salario_operarios']+R2['salario_operarios']),
    ('  Custo produção (água+EE)', R1['custo_producao'], R2['custo_producao'], R1['custo_producao']+R2['custo_producao']),
    ('  MP comprada', R1['mp_comprada'], R2['mp_comprada'], R1['mp_comprada']+R2['mp_comprada']),
    ('', None, None, None),
    ('OPERAÇÃO CDs', None, None, None),
    ('  Manut CDs', R1['manut_cds'], R2['manut_cds'], R1['manut_cds']+R2['manut_cds']),
    ('', None, None, None),
    ('TRANSPORTE', None, None, None),
    ('  Frete MP (For→F1)', R1['frete_mp'], R2['frete_mp'], R1['frete_mp']+R2['frete_mp']),
    ('  Frete PA (F1→CD e CD→Var)', R1['frete_pa'], R2['frete_pa'], R1['frete_pa']+R2['frete_pa']),
    ('', None, None, None),
    ('CARREGAMENTO ESTOQUE', None, None, None),
    ('  MP', R1['carreg_mp'], R2['carreg_mp'], R1['carreg_mp']+R2['carreg_mp']),
    ('  PA', R1['carreg_pa'], R2['carreg_pa'], R1['carreg_pa']+R2['carreg_pa']),
    ('', None, None, None),
    ('  TOTAL CUSTOS OPERACIONAIS', R1['custo_total_operacional'], R2['custo_total'], R1['custo_total_operacional']+R2['custo_total']),
    ('', None, None, None),
    ('RESULTADO DA RODADA', R1['resultado'], R2['resultado'], R1['resultado']+R2['resultado']),
    ('RESULTADO COM SET-UP', R1['acumulado_com_setup'], R2['resultado'], R1['acumulado_com_setup']+R2['resultado']),
]

print(f'{"":<42} {"R1":>14} {"R2":>14} {"Acumulado":>14}')
print('-' * 90)
for label, v_r1, v_r2, v_acum in linhas:
    if v_r1 is None:
        print(f'{label:<42}')
        continue
    sinal_r1 = '-' if v_r1 > 0 and 'RECEITA' not in label.upper() and 'RESULTADO' not in label.upper() and 'TOTAL' not in label.upper() else ''
    sinal_r2 = '-' if v_r2 > 0 and 'RECEITA' not in label.upper() and 'RESULTADO' not in label.upper() and 'TOTAL' not in label.upper() else ''
    # Pra "TOTAL CUSTOS" e linhas neutras
    if 'RECEITA' in label.upper() and 'TOTAL' not in label.upper() and 'AS' not in label:
        sinal_r1 = '+'; sinal_r2 = '+'
    if 'RESULTADO' in label.upper():
        sinal_r1 = '+' if v_r1 >= 0 else '-'; sinal_r2 = '+' if v_r2 >= 0 else '-'
        v_r1, v_r2, v_acum = abs(v_r1), abs(v_r2), abs(v_acum)
    print(f'{label:<42} {sinal_r1}R$ {v_r1:>10,.0f}  {sinal_r2}R$ {v_r2:>10,.0f}  R$ {v_acum:>12,.0f}')

print()
print('=' * 90)
print('  PROJEÇÃO R3-R15 (cenário PA3, atendimento 50%, com buffer já comprado)')
print('=' * 90)

# Cenário R3 (PA3 mais provável dado proporção HW)
qtd_pa3_r3 = 1_026_558  # capacidade com buffer MP atual
preco_pa3 = 25  # referência (será sobrescrito quando vier preço real)
receita_r3 = qtd_pa3_r3 * preco_pa3

# Custos R3 (estimativa)
# MP já está em estoque (buffer R2), só repõe consumo
mp_consumo_pa3 = {
    'MP1': qtd_pa3_r3 * 75 / 1_000_000,
    'MP2': qtd_pa3_r3 * 30 / 1_000_000,
    'MP3': qtd_pa3_r3 * 45 / 1_000_000,
}
# Frete: caminhão majoritário (estoque já tá nos CDs?? NÃO — só MP)
# Vai ter avião pra PA3 também porque CDs estão vazios em PA3
frete_pa_r3 = 5_000_000  # estimativa conservadora (maioria avião pra OPs urgentes)
mp_comprada_r3 = 0  # estoque atual cobre boa parte
estruturais_r3 = 1_123_151  # = parcelas + operação fábrica/CDs
carreg_r3 = 200_000

custo_r3 = estruturais_r3 + mp_comprada_r3 + frete_pa_r3 + 30_000 + carreg_r3
resultado_r3 = receita_r3 - custo_r3

print(f'\nCenário R3 = PA3 (mais provável)')
print(f'  Receita: {qtd_pa3_r3:,} frascos × R$ {preco_pa3} = R$ {receita_r3:,.0f}')
print(f'  Custo estimado: R$ {custo_r3:,.0f}')
print(f'  Resultado R3 estimado: R$ {resultado_r3:,.0f}')

acum_pos_r3 = R1['acumulado_com_setup'] + R2['resultado'] + resultado_r3
print(f'  Acumulado R1+R2+R3: R$ {acum_pos_r3:,.0f}')
print()
print('Projeção até R15 (assumindo média R3 de receita constante):')
print(f'  Receita média R3-R15: ~R$ {receita_r3:,.0f}/rodada (varia conforme preço)')
print(f'  Custo médio R3-R15: ~R$ {custo_r3:,.0f}/rodada')
print(f'  Lucro médio R3-R15: ~R$ {resultado_r3:,.0f}/rodada')
print(f'  Rodadas restantes: 13 (R3 a R15)')
acum_final = acum_pos_r3 + resultado_r3 * 12  # +12 outras rodadas similares
print(f'\nPROJEÇÃO FINAL (R15):')
print(f'  Acumulado nominal: R$ {acum_final:,.0f}')
# VPL
taxa = 0.0075
vpl = R1['acumulado_com_setup'] + R2['resultado']/1.0075 + sum(resultado_r3/(1.0075**(2+i)) for i in range(1, 14))
print(f'  VPL descontado (0.75%/rodada): R$ {vpl:,.0f}')
