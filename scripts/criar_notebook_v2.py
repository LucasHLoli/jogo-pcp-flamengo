"""Gera jogo/rodada_V2.ipynb com estrategia + indicadores + VPL."""
from pathlib import Path
import nbformat as nbf

nb = nbf.v4.new_notebook()

cells = [
    # === HEADER ===
    nbf.v4.new_markdown_cell(
        "# 🎮 Jogo PCP 2 — FLAMENGO — Cockpit V2\n\n"
        "Versão estratégica focada em VPL no longo prazo (15 rodadas).\n\n"
        "**O que mudou vs V1:**\n"
        "- Parâmetro `ESTRATEGIA` (conservador / balanceado / agressivo)\n"
        "- Célula nova com **DRE + indicadores operacionais (espelhando o `IND_FLAMENGO.pdf`) + VPL**\n"
        "- Histórico de resultados (calcula VPL acumulado)\n\n"
        "**Fluxo:**\n"
        "1. Setup\n"
        "2. 📝 Estado inicial\n"
        "3. 📝 OPs do prof\n"
        "4. 📝 Preços\n"
        "5. 📝 Histórico de resultados (rodadas anteriores)\n"
        "6. Forecast HW próxima rodada\n"
        "7. 📝 Estratégia + planejar\n"
        "8. Tabela SOL_TRANSP\n"
        "9. Tabela OP_FABRICAS\n"
        "10. Resumo\n"
        "11. 📊 **DRE + IND + VPL** (novo)\n"
        "12. 📤 Gravar FLAMENGO.xlsm\n"
        "13. Dashboard histórico"
    ),

    # 1. Setup
    nbf.v4.new_markdown_cell("## 1. Setup"),
    nbf.v4.new_code_cell(
        "import sys, os, json\n"
        "from pathlib import Path\n"
        "import pandas as pd\n"
        "\n"
        "# Acha a raiz do projeto procurando o marker 'data/parametros.json'\n"
        "# (robusto contra mudanças no CWD do kernel Jupyter)\n"
        "def _find_base():\n"
        "    candidatos = [Path.cwd()] + list(Path.cwd().parents)\n"
        "    # também tenta a partir do diretório do próprio notebook\n"
        "    try:\n"
        "        candidatos.insert(0, Path(__file__).resolve().parent.parent)\n"
        "    except NameError:\n"
        "        pass\n"
        "    for c in candidatos:\n"
        "        if (c / 'data' / 'parametros.json').exists():\n"
        "            return c\n"
        "    # fallback hardcoded\n"
        "    fallback = Path(r'C:/Users/lolil/Downloads/Jogo PCP 2 (a vinganca)')\n"
        "    if (fallback / 'data' / 'parametros.json').exists():\n"
        "        return fallback\n"
        "    raise FileNotFoundError(\n"
        "        f'Não achei a raiz do projeto. CWD={Path.cwd()}. '\n"
        "        f'Verifique que existe data/parametros.json acima do notebook.'\n"
        "    )\n"
        "\n"
        "BASE = _find_base()\n"
        "sys.path.insert(0, str(BASE))\n"
        "os.chdir(BASE)\n"
        "if hasattr(sys.stdout, 'reconfigure'):\n"
        "    sys.stdout.reconfigure(encoding='utf-8', errors='replace')\n"
        "from src.config import Config\n"
        "from src.io_xlsm import ler_instalacoes, escrever_planos_de_df\n"
        "from src.planner_manual import planejar_rodada, forecast_proxima_rodada_via_hw\n"
        "from src.indicadores import calcular_dre_e_ind, imprimir_painel\n"
        "from src.dashboard import plot_historico\n"
        "cfg = Config.load(BASE)\n"
        "instalacoes = ler_instalacoes(BASE / 'rodadas' / 'FLAMENGO.xlsm')\n"
        "print('OK — base:', BASE)\n"
        "print('Fábrica F1:', instalacoes['fabricas']['F1']['cidade'],\n"
        "      '— máq:', instalacoes['fabricas']['F1']['maquinas'],\n"
        "      '— turnos:', instalacoes['fabricas']['F1']['turnos'])"
    ),

    # 2. Estado inicial
    nbf.v4.new_markdown_cell(
        "## 2. 📝 Estado inicial (do `ESTOQUES_FLAMENGO.pdf`)"
    ),
    nbf.v4.new_code_cell(
        "RODADA = 2\n"
        "\n"
        "ESTOQUE_MP = {\n"
        "    'MP1': 47.0,\n"
        "    'MP2': 48.0,\n"
        "    'MP3': 42.0,\n"
        "}\n"
        "ESTOQUE_PA_CD = {\n"
        "    'CD1': {'PA1': 0, 'PA2': 0, 'PA3': 0},  # São Luís\n"
        "    'CD2': {'PA1': 0, 'PA2': 0, 'PA3': 0},  # Santos\n"
        "}\n"
        "print(f'Rodada {RODADA} — estoque inicial OK')"
    ),

    # 3. OPs
    nbf.v4.new_markdown_cell(
        "## 3. 📝 OPs do prof (do PDF da rodada)\n\n"
        "⚠ Converta dias do jogo (Dia 6-10, etc.) para dias da rodada (1-5)."
    ),
    nbf.v4.new_code_cell(
        "OPS = [\n"
        "    # PA1 R2 — dias jogo 6-10 → dias rodada 1-5\n"
        "    {'cidade': 'Belém',                 'pa': 'PA1', 'qtd': 6009,  'dia_entrega': 5},\n"
        "    {'cidade': 'Belo Horizonte',        'pa': 'PA1', 'qtd': 33385, 'dia_entrega': 3},\n"
        "    {'cidade': 'Brasília',              'pa': 'PA1', 'qtd': 25595, 'dia_entrega': 3},\n"
        "    {'cidade': 'Campinas',              'pa': 'PA1', 'qtd': 26708, 'dia_entrega': 2},\n"
        "    {'cidade': 'Campo Grande',          'pa': 'PA1', 'qtd': 5119,  'dia_entrega': 3},\n"
        "    {'cidade': 'Cuiabá',                'pa': 'PA1', 'qtd': 6143,  'dia_entrega': 3},\n"
        "    {'cidade': 'Curitiba',              'pa': 'PA1', 'qtd': 22524, 'dia_entrega': 2},\n"
        "    {'cidade': 'Fortaleza',             'pa': 'PA1', 'qtd': 20432, 'dia_entrega': 5},\n"
        "    {'cidade': 'Goiânia',               'pa': 'PA1', 'qtd': 14333, 'dia_entrega': 3},\n"
        "    {'cidade': 'João Pessoa',           'pa': 'PA1', 'qtd': 12019, 'dia_entrega': 4},\n"
        "    {'cidade': 'Joinville',             'pa': 'PA1', 'qtd': 6143,  'dia_entrega': 2},\n"
        "    {'cidade': 'Maceió',                'pa': 'PA1', 'qtd': 12019, 'dia_entrega': 4},\n"
        "    {'cidade': 'Manaus',                'pa': 'PA1', 'qtd': 6009,  'dia_entrega': 5},\n"
        "    {'cidade': 'Natal',                 'pa': 'PA1', 'qtd': 12019, 'dia_entrega': 5},\n"
        "    {'cidade': 'Porto Alegre',          'pa': 'PA1', 'qtd': 22524, 'dia_entrega': 2},\n"
        "    {'cidade': 'Recife',                'pa': 'PA1', 'qtd': 18028, 'dia_entrega': 4},\n"
        "    {'cidade': 'Ribeirão Preto',        'pa': 'PA1', 'qtd': 22257, 'dia_entrega': 2},\n"
        "    {'cidade': 'Rio de Janeiro',        'pa': 'PA1', 'qtd': 44513, 'dia_entrega': 3},\n"
        "    {'cidade': 'Salvador',              'pa': 'PA1', 'qtd': 24037, 'dia_entrega': 4},\n"
        "    {'cidade': 'Santos',                'pa': 'PA1', 'qtd': 22257, 'dia_entrega': 2},\n"
        "    {'cidade': 'São Luís',              'pa': 'PA1', 'qtd': 6009,  'dia_entrega': 5},\n"
        "    {'cidade': 'São Paulo',             'pa': 'PA1', 'qtd': 55642, 'dia_entrega': 2},\n"
        "    {'cidade': 'Uberlândia',            'pa': 'PA1', 'qtd': 11128, 'dia_entrega': 3},\n"
        "    {'cidade': 'Vitória',               'pa': 'PA1', 'qtd': 6677,  'dia_entrega': 3},\n"
        "    {'cidade': 'Vitória da Conquista',  'pa': 'PA1', 'qtd': 3606,  'dia_entrega': 4},\n"
        "]\n"
        "print(f'{len(OPS)} OPs — total {sum(o[\"qtd\"] for o in OPS):,} frascos')"
    ),

    # 4. Preços
    nbf.v4.new_markdown_cell("## 4. 📝 Preços de mercado"),
    nbf.v4.new_code_cell(
        "PRECOS = {\n"
        "    'PA1': 64.00,\n"
        "    'PA2': cfg.precos_referencia['PA2'],\n"
        "    'PA3': cfg.precos_referencia['PA3'],\n"
        "}\n"
        "print('Preços:', PRECOS)"
    ),

    # 5. Histórico de resultados (para VPL)
    nbf.v4.new_markdown_cell(
        "## 5. 📝 Histórico de resultados das rodadas anteriores\n\n"
        "Cole os **resultados** (lucro/prejuízo) das rodadas anteriores em ordem.\n"
        "Rodada 1 do DRE: -R$ 5.602.321 (incluindo set-up). Sem set-up, custo operacional ~R$ 1.128k."
    ),
    nbf.v4.new_code_cell(
        "# Histórico — lucro (positivo) ou prejuízo (negativo) por rodada\n"
        "# Inclui Rodada 1: -R$ 5.602.321 (set-up + operação sem receita)\n"
        "HISTORICO_RESULTADOS = [\n"
        "    -5_602_321.0,  # Rodada 1\n"
        "]\n"
        "print(f'Histórico até R{RODADA-1}: {len(HISTORICO_RESULTADOS)} rodada(s)')\n"
        "print(f'Acumulado nominal: R$ {sum(HISTORICO_RESULTADOS):,.2f}')"
    ),

    # 6. Forecast HW → proporções entre PAs
    nbf.v4.new_markdown_cell(
        "## 6. Forecast HW → estimativa demanda próxima rodada\n\n"
        "⚠ Como só vem **1 PA por rodada** (ciclo desconhecido), o HW absoluto não vale\n"
        "como demanda direta. Mas a **proporção entre PAs** é estável historicamente:\n\n"
        "- Aplicamos `(forecast_PA2 / forecast_PA1)` no realizado da R2 pra estimar PA2 na R3\n"
        "- Idem pra PA3"
    ),
    nbf.v4.new_code_cell(
        "forecast_next = forecast_proxima_rodada_via_hw(rodada_n_atual=RODADA, base_dir=BASE)\n"
        "total_fc = {pa: sum(v for (c, p), v in forecast_next.items() if p == pa) for pa in ('PA1','PA2','PA3')}\n"
        "\n"
        "prop_pa2_pa1 = total_fc['PA2'] / total_fc['PA1']\n"
        "prop_pa3_pa1 = total_fc['PA3'] / total_fc['PA1']\n"
        "\n"
        "qtd_pa_realizada = sum(o['qtd'] for o in OPS)\n"
        "pa_r2 = OPS[0]['pa']\n"
        "\n"
        "# Estima qtd FLAMENGO em R+1 pra cada PA possível\n"
        "if pa_r2 == 'PA1':\n"
        "    est = {'PA1': qtd_pa_realizada,\n"
        "           'PA2': int(qtd_pa_realizada * prop_pa2_pa1),\n"
        "           'PA3': int(qtd_pa_realizada * prop_pa3_pa1)}\n"
        "elif pa_r2 == 'PA2':\n"
        "    est = {'PA1': int(qtd_pa_realizada / prop_pa2_pa1),\n"
        "           'PA2': qtd_pa_realizada,\n"
        "           'PA3': int(qtd_pa_realizada * prop_pa3_pa1 / prop_pa2_pa1)}\n"
        "else:  # PA3\n"
        "    est = {'PA1': int(qtd_pa_realizada / prop_pa3_pa1),\n"
        "           'PA2': int(qtd_pa_realizada * prop_pa2_pa1 / prop_pa3_pa1),\n"
        "           'PA3': qtd_pa_realizada}\n"
        "\n"
        "DEMANDA_R3_ESTIMADA = est\n"
        "\n"
        "print(f'Proporções HW (PA1 referência):')\n"
        "print(f'  PA2/PA1 = {prop_pa2_pa1:.2f}x | PA3/PA1 = {prop_pa3_pa1:.2f}x')\n"
        "print()\n"
        "print(f'R{RODADA} atendeu: {qtd_pa_realizada:,} frascos de {pa_r2}')\n"
        "print()\n"
        "print(f'Estimativa demanda R{RODADA+1} (se vier cada PA):')\n"
        "for pa, qtd in DEMANDA_R3_ESTIMADA.items():\n"
        "    print(f'  Se R{RODADA+1} vier {pa}: ~{qtd:,} frascos')"
    ),

    # 6.5 — Buffer MP flexível com heurística automática (NOVO)
    nbf.v4.new_markdown_cell(
        "## 6.5. 📝 Buffer MP flexível — heurística automática\n\n"
        "**Regra do jogo**: cada rodada vem APENAS 1 PA, e ele NÃO se repete na próxima.\n"
        "Logo, se R2 = PA1, então **R3 será PA2 OU PA3** (nunca PA1).\n\n"
        "Como o PA específico é desconhecido, a melhor estratégia é **comprar MP extra**\n"
        "(não PA acabado, porque pode ir pro PA errado).\n\n"
        "**Heurística automática** (rodando abaixo):\n"
        "1. Identifica PAs **POSSÍVEIS** na R+1 (exclui o PA atual)\n"
        "2. Calcula MP necessária pra produzir cada cenário (pior caso por MP)\n"
        "3. **Enche cap de cada MP até o limite útil** (sem desperdício)\n"
        "4. Respeita cap do depósito F1\n\n"
        "**Override manual**: se quiser ignorar a heurística, edite `COMPRAS_MP_EXTRA` direto."
    ),
    nbf.v4.new_code_cell(
        "# === HEURÍSTICA AUTOMÁTICA ===\n"
        "# IMPORTANTE: cada rodada vem APENAS 1 PA, e ele NÃO se repete na próxima\n"
        "# (R2 = PA1 → R3 será PA2 OU PA3, nunca PA1 de novo).\n"
        "# Calcula MP necessária pra atender X% da demanda estimada dos PAs restantes,\n"
        "# pega o pior caso por MP, limita por cap do depósito.\n"
        "\n"
        "BUFFER_PCT_R3 = 0.50  # % da demanda estimada R+1 a cobrir\n"
        "\n"
        "# PAs possíveis na próxima rodada — EXCLUI o PA da rodada atual\n"
        "PAS_POSSIVEIS_PROXIMA = tuple(pa for pa in ('PA1','PA2','PA3') if pa != pa_r2)\n"
        "print(f'PA atual R{RODADA}: {pa_r2}')\n"
        "print(f'PAs possíveis R{RODADA+1}: {PAS_POSSIVEIS_PROXIMA}')\n"
        "print()\n"
        "\n"
        "# Estoque MP pós-consumo R2 (estimado)\n"
        "consumo_mp_r2 = {mp: qtd_pa_realizada * cfg.BoM[pa_r2][mp] / 1_000_000\n"
        "                  for mp in ('MP1','MP2','MP3')}\n"
        "mp_pos_r2 = {mp: max(0, ESTOQUE_MP[mp] - consumo_mp_r2[mp]) for mp in ('MP1','MP2','MP3')}\n"
        "\n"
        "# Cap MP da fábrica\n"
        "f1 = instalacoes['fabricas']['F1']\n"
        "cap_mp = {mp: f1['area_mp'][mp] * cfg.capacidades['pe_direito_deposito_m']\n"
        "                * cfg.densidades_mp[mp] for mp in ('MP1','MP2','MP3')}\n"
        "\n"
        "# MP necessária pra cada cenário (pior caso entre os PAs POSSÍVEIS)\n"
        "mp_necessaria_pior_caso = {'MP1':0.0,'MP2':0.0,'MP3':0.0}\n"
        "for pa in PAS_POSSIVEIS_PROXIMA:\n"
        "    qtd_alvo = DEMANDA_R3_ESTIMADA[pa] * BUFFER_PCT_R3\n"
        "    for mp in ('MP1','MP2','MP3'):\n"
        "        mp_req = qtd_alvo * cfg.BoM[pa][mp] / 1_000_000\n"
        "        if mp_req > mp_necessaria_pior_caso[mp]:\n"
        "            mp_necessaria_pior_caso[mp] = mp_req\n"
        "\n"
        "# MP a comprar (limita por cap)\n"
        "COMPRAS_MP_EXTRA = {}\n"
        "for mp in ('MP1','MP2','MP3'):\n"
        "    falta = max(0, mp_necessaria_pior_caso[mp] - mp_pos_r2[mp])\n"
        "    cap_livre = cap_mp[mp] - mp_pos_r2[mp]\n"
        "    comprar = min(falta, cap_livre)\n"
        "    if comprar > 0.1:\n"
        "        COMPRAS_MP_EXTRA[mp] = round(comprar, 1)\n"
        "\n"
        "# Mostra análise\n"
        "print(f'Buffer alvo: {BUFFER_PCT_R3*100:.0f}% da demanda estimada R{RODADA+1}')\n"
        "print(f'(considerando APENAS os PAs possíveis: {PAS_POSSIVEIS_PROXIMA})')\n"
        "print()\n"
        "print(f'{\"MP\":<5} {\"Atual\":>8} {\"Necessário\":>12} {\"Comprar\":>10} {\"Cap livre\":>11}')\n"
        "for mp in ('MP1','MP2','MP3'):\n"
        "    print(f'{mp:<5} {mp_pos_r2[mp]:>6.1f}t  {mp_necessaria_pior_caso[mp]:>10.1f}t  '\n"
        "          f'{COMPRAS_MP_EXTRA.get(mp, 0):>8.1f}t  {cap_mp[mp]-mp_pos_r2[mp]:>9.1f}t')\n"
        "print()\n"
        "custo_extra = sum({\n"
        "    'MP1': 48_000, 'MP2': 16_000, 'MP3': 32_000\n"
        "}[mp] * t for mp, t in COMPRAS_MP_EXTRA.items())\n"
        "print(f'Custo MP extra: R$ {custo_extra:,.0f}')\n"
        "print()\n"
        "print(f'💡 Capacidade de produção R{RODADA+1} com esse buffer:')\n"
        "mp_inicio_prox = {mp: mp_pos_r2[mp] + COMPRAS_MP_EXTRA.get(mp, 0) for mp in ('MP1','MP2','MP3')}\n"
        "for pa in PAS_POSSIVEIS_PROXIMA:\n"
        "    cap_por_mp = {mp: mp_inicio_prox[mp] * 1_000_000 / cfg.BoM[pa][mp] for mp in ('MP1','MP2','MP3') if cfg.BoM[pa][mp] > 0}\n"
        "    gargalo_mp = min(cap_por_mp, key=cap_por_mp.get)\n"
        "    cap_pa = int(cap_por_mp[gargalo_mp])\n"
        "    atende = min(cap_pa, DEMANDA_R3_ESTIMADA[pa])\n"
        "    pct = atende / DEMANDA_R3_ESTIMADA[pa] * 100 if DEMANDA_R3_ESTIMADA[pa] > 0 else 0\n"
        "    print(f'  Se R{RODADA+1} vier {pa}: até {cap_pa:>8,} frascos → atende {atende:>8,}/{DEMANDA_R3_ESTIMADA[pa]:>8,} ({pct:.0f}%)')"
    ),

    # 7. Estratégia + planejar
    nbf.v4.new_markdown_cell(
        "## 7. 📝 Estratégia + Planejamento\n\n"
        "**Comparativo da R2 (CDs zerados, R1=-R$5.6M acumulado):**\n\n"
        "| Estratégia | Buffer | Atendimento | Lucro R2 | VPL acum |\n"
        "|---|---|---|---|---|\n"
        "| conservador | qualquer | **0%** | -R$ 1,18M | -R$ 6,78M ❌ |\n"
        "| balanceado | 0% | 27% | R$ 5,43M | -R$ 0,21M |\n"
        "| **agressivo** | **0%** | **60%** | **+R$ 9,51M** | **+R$ 3,84M ✅** |\n"
        "| agressivo | 40% | 60% | R$ 7,04M | +R$ 1,39M |\n\n"
        "**🎯 RECOMENDAÇÃO R2: `agressivo` + `BUFFER_PCT=0.0`** — único cenário com VPL positivo.\n\n"
        "**⚠ Sobre BUFFER_PCT (estocar PA pra próxima rodada):**\n"
        "Como cada rodada só tem **1 PA** (ciclo desconhecido), produzir buffer do PA atual\n"
        "pode ser desperdício se a R+1 vier com outro PA. **Default: 0%** (sem buffer).\n\n"
        "**Definições das estratégias:**\n"
        "- `'conservador'`: só caminhão/navio em todas as pernas. Sem avião.\n"
        "- `'balanceado'`: F1→CD só via caminhão/navio; CD→Varejo pode usar avião.\n"
        "- `'agressivo'`: avião livre em qualquer perna."
    ),
    nbf.v4.new_code_cell(
        "ESTRATEGIA = 'agressivo'  # 'conservador' | 'balanceado' | 'agressivo'\n"
        "BUFFER_PCT = 0.0          # 0.0 default — só vem 1 PA por rodada, sem buffer PA\n"
        "\n"
        "resultado = planejar_rodada(\n"
        "    rodada_n=RODADA,\n"
        "    ops_rodada=OPS,\n"
        "    forecast_proxima=forecast_next,\n"
        "    estado_inicial_mp_ton=ESTOQUE_MP,\n"
        "    estado_inicial_pa_cd=ESTOQUE_PA_CD,\n"
        "    cfg=cfg,\n"
        "    instalacoes=instalacoes,\n"
        "    buffer_pct=BUFFER_PCT,\n"
        "    estrategia=ESTRATEGIA,\n"
        "    compras_mp_extra=COMPRAS_MP_EXTRA,\n"
        ")\n"
        "df_sol_transp = resultado['df_sol_transp']\n"
        "df_op_fabricas = resultado['df_op_fabricas']\n"
        "resumo = resultado['resumo']\n"
        "print(f'Plano: {len(df_sol_transp)} transportes')\n"
        "print(f'Atendimento: {resumo[\"qtd_atendida\"]:,}/{resumo[\"qtd_atendida\"]+resumo[\"qtd_descartada\"]:,} frascos')"
    ),

    # 8. SOL_TRANSP
    nbf.v4.new_markdown_cell("## 8. 📋 SOL_TRANSP (DataFrame final)"),
    nbf.v4.new_code_cell(
        "df_show = df_sol_transp.rename(columns={'Cidade_Destino': 'Cidade Destino'})\n"
        "df_show"
    ),

    # 9. OP_FABRICAS
    nbf.v4.new_markdown_cell("## 9. 📋 OP_FABRICAS"),
    nbf.v4.new_code_cell("df_op_fabricas"),

    # 10. Resumo
    nbf.v4.new_markdown_cell("## 10. Resumo operacional"),
    nbf.v4.new_code_cell(
        "print('━' * 60)\n"
        "print(f'  RODADA {RODADA} — Estratégia: {ESTRATEGIA}')\n"
        "print('━' * 60)\n"
        "print(f'OPs atendidas: {resumo[\"ops_atendidas\"]}/{resumo[\"ops_total\"]}')\n"
        "print(f'Qtd atendida:  {resumo[\"qtd_atendida\"]:,} frascos ({resumo[\"taxa_atendimento_pct\"]:.1f}%)')\n"
        "print(f'Qtd descartada: {resumo[\"qtd_descartada\"]:,}')\n"
        "print()\n"
        "print('Produção por PA:', resumo['producao_total_por_pa'])\n"
        "print('Buffer R+1:    ', resumo['buffer_acumulado_pa'])\n"
        "print()\n"
        "print('MP a comprar:')\n"
        "for mp, ton in resumo['mp_a_comprar_ton'].items():\n"
        "    if ton > 0.1:\n"
        "        print(f'  {mp}: {ton:.1f} ton')\n"
        "print()\n"
        "print('Min-máq usados/dia (cap=10080):')\n"
        "for d, m in enumerate(resumo['minutos_usados_por_dia'], 1):\n"
        "    print(f'  Dia {d}: {m:,} ({m/10080*100:.1f}%)')\n"
        "if resumo['descartadas']:\n"
        "    print()\n"
        "    print('OPs descartadas:')\n"
        "    for d in resumo['descartadas']:\n"
        "        print(f'  ❌ {d.get(\"cidade\",\"?\"):<22} qtd={d.get(\"qtd\",0):>6,} dia={d.get(\"dia_entrega\",\"?\")}')"
    ),

    # 11. DRE + IND + VPL
    nbf.v4.new_markdown_cell(
        "## 11. 📊 DRE + IND_FLAMENGO + VPL\n\n"
        "Painel financeiro e operacional **espelhando os relatórios do prof**:\n"
        "- **DRE**: receita - todos os custos detalhados (parcelas, MP, frete, carregamento, etc.)\n"
        "- **IND**: utilização da fábrica, distribuição modal, custo/ton\n"
        "- **VPL**: valor presente líquido descontado (foco no longo prazo)"
    ),
    nbf.v4.new_code_cell(
        "# Calcula qtd atendida por PA a partir das tarefas finalizadas\n"
        "qtd_atendida_por_pa = {'PA1': 0, 'PA2': 0, 'PA3': 0}\n"
        "# Soma das OPs que foram efetivamente alocadas (não descartadas)\n"
        "ops_descartadas_set = {(d.get('cidade'), d.get('pa'), d.get('dia_entrega'))\n"
        "                        for d in resumo['descartadas']}\n"
        "for o in OPS:\n"
        "    k = (o['cidade'], o['pa'], o['dia_entrega'])\n"
        "    if k not in ops_descartadas_set:\n"
        "        qtd_atendida_por_pa[o['pa']] += o['qtd']\n"
        "\n"
        "# Estimativa de estoque final nos CDs = estoque inicial + buffer produzido\n"
        "estoque_pa_final = {\n"
        "    cd: {pa: ESTOQUE_PA_CD[cd][pa] + resumo['buffer_acumulado_pa'][pa] // 2\n"
        "         for pa in ('PA1','PA2','PA3')}\n"
        "    for cd in ESTOQUE_PA_CD\n"
        "}\n"
        "# Estimativa de estoque MP final = inicial + comprado - consumido\n"
        "estoque_mp_final = {\n"
        "    mp: max(0, ESTOQUE_MP[mp]\n"
        "             + resumo['mp_a_comprar_ton'][mp]\n"
        "             - sum(resumo['producao_total_por_pa'][pa] * cfg.BoM[pa][mp] / 1_000_000\n"
        "                   for pa in ('PA1','PA2','PA3')))\n"
        "    for mp in ('MP1','MP2','MP3')\n"
        "}\n"
        "\n"
        "indicadores = calcular_dre_e_ind(\n"
        "    rodada_n=RODADA,\n"
        "    df_sol_transp=df_sol_transp,\n"
        "    df_op_fabricas=df_op_fabricas,\n"
        "    qtd_atendida_por_pa=qtd_atendida_por_pa,\n"
        "    precos=PRECOS,\n"
        "    estoque_pa_final=estoque_pa_final,\n"
        "    estoque_mp_final=estoque_mp_final,\n"
        "    cfg=cfg,\n"
        "    instalacoes=instalacoes,\n"
        "    historico_resultados=HISTORICO_RESULTADOS,\n"
        ")\n"
        "imprimir_painel(indicadores)"
    ),

    # 12. Gravar no FLAMENGO
    nbf.v4.new_markdown_cell(
        "## 12. 📤 Gravar `FLAMENGO.xlsm` (pronto para entregar)\n\n"
        "Escreve as duas abas preservando VBA, fórmulas e demais abas."
    ),
    nbf.v4.new_code_cell(
        "flamengo_path = BASE / 'rodadas' / 'FLAMENGO.xlsm'\n"
        "n = escrever_planos_de_df(flamengo_path, df_sol_transp, df_op_fabricas, rodada_n=RODADA)\n"
        "print(f'✅ FLAMENGO.xlsm atualizado: {n} linhas em SOL_TRANSP da Rodada_{RODADA}')\n"
        "print(f'   {flamengo_path}')\n"
        "print('   VBA, fórmulas e demais abas preservadas. Pronto pra entregar.')"
    ),

    # 13. Histórico
    nbf.v4.new_markdown_cell("## 13. Dashboard histórico (rodadas anteriores)"),
    nbf.v4.new_code_cell("plot_historico(BASE / 'estado')"),
]

nb["cells"] = cells

out = Path("jogo/rodada_V2.ipynb")
out.parent.mkdir(parents=True, exist_ok=True)
nbf.write(nb, str(out))
print(f"Notebook criado em {out}")
