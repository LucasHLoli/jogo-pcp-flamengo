"""Gera jogo/rodada.ipynb com fluxo manual + planner com forecast HW pra próxima rodada."""
from pathlib import Path
import nbformat as nbf

nb = nbf.v4.new_notebook()

cells = [
    # === HEADER ===
    nbf.v4.new_markdown_cell(
        "# 🎮 Jogo PCP 2 — FLAMENGO — Cockpit\n\n"
        "Fluxo a cada rodada (edite só as células marcadas com 📝):\n\n"
        "1. **Setup** — roda sempre\n"
        "2. 📝 **Estado inicial** — estoques no início da rodada (de `ESTOQUES_FLAMENGO.pdf`)\n"
        "3. 📝 **OPs do prof** — cidade/PA/qtd/dia_entrega (de `RODADA_0X_PAY.pdf`)\n"
        "4. 📝 **Preços de mercado** — do `J2_FLAMENGO_ROD_X_PREÇO.docx`\n"
        "5. **Forecast HW próxima rodada** — automático\n"
        "6. **Planejamento** — atende R atual + estoca buffer R+1\n"
        "7. **📋 Tabela SOL_TRANSP** — copie para a aba SOL_TRANSP do FLAMENGO.xlsm\n"
        "8. **📋 Tabela OP_FABRICAS** — copie para a aba OP_FABRICAS do FLAMENGO.xlsm\n"
        "9. **Resumo** — métricas e alertas\n"
        "10. **Histórico** — dashboard"
    ),

    # === 1. SETUP ===
    nbf.v4.new_markdown_cell("## 1. Setup (rodar sempre)"),
    nbf.v4.new_code_cell(
        "import sys, os, json\n"
        "from pathlib import Path\n"
        "import pandas as pd\n"
        "BASE = Path('..').resolve()\n"
        "sys.path.insert(0, str(BASE))\n"
        "os.chdir(BASE)\n"
        "if hasattr(sys.stdout, 'reconfigure'):\n"
        "    sys.stdout.reconfigure(encoding='utf-8', errors='replace')\n"
        "from src.config import Config\n"
        "from src.io_xlsm import ler_instalacoes\n"
        "from src.planner_manual import planejar_rodada, forecast_proxima_rodada_via_hw\n"
        "from src.dashboard import plot_historico, tabela_resumo, ler_snapshots\n"
        "cfg = Config.load(BASE)\n"
        "instalacoes = ler_instalacoes(BASE / 'rodadas' / 'FLAMENGO.xlsm')\n"
        "print('OK — base:', BASE)\n"
        "print('Fábrica F1:', instalacoes['fabricas']['F1']['cidade'],\n"
        "      '— máq:', instalacoes['fabricas']['F1']['maquinas'],\n"
        "      '— turnos:', instalacoes['fabricas']['F1']['turnos'])\n"
        "for cd, d in instalacoes['cds'].items():\n"
        "    if d.get('cidade'):\n"
        "        print(f'{cd}: {d[\"cidade\"]} — areas PA1={d[\"area_pa\"][\"PA1\"]} PA2={d[\"area_pa\"][\"PA2\"]} PA3={d[\"area_pa\"][\"PA3\"]}')"
    ),

    # === 2. ESTADO INICIAL ===
    nbf.v4.new_markdown_cell(
        "## 2. 📝 Estado inicial da rodada\n\n"
        "Cole aqui os dados do `ESTOQUES_FLAMENGO.pdf` (estoques no Dia 5 da rodada anterior)."
    ),
    nbf.v4.new_code_cell(
        "RODADA = 2  # ← troque a cada rodada\n"
        "\n"
        "# Estoque MP em F1 (toneladas — do PDF de estoques, F1 Joinville)\n"
        "ESTOQUE_MP = {\n"
        "    'MP1': 47.0,\n"
        "    'MP2': 48.0,\n"
        "    'MP3': 42.0,\n"
        "}\n"
        "\n"
        "# Estoque PA em CDs (unidades — frascos)\n"
        "ESTOQUE_PA_CD = {\n"
        "    'CD1': {'PA1': 0, 'PA2': 0, 'PA3': 0},  # São Luís\n"
        "    'CD2': {'PA1': 0, 'PA2': 0, 'PA3': 0},  # Santos\n"
        "}\n"
        "\n"
        "print(f'Rodada {RODADA} - estoque inicial:')\n"
        "print('  MP F1:', ESTOQUE_MP)\n"
        "print('  PA CDs:', ESTOQUE_PA_CD)"
    ),

    # === 3. OPs ===
    nbf.v4.new_markdown_cell(
        "## 3. 📝 Pedidos do varejo (OPs do prof)\n\n"
        "Cole as OPs do PDF da rodada. Cada dict: `cidade, pa, qtd, dia_entrega` (1-5).\n\n"
        "⚠ **Conversão de dias**: se o PDF mostrar Dia 6-10, converta para Dia 1-5 da rodada (Dia 6→1, Dia 7→2, etc.)."
    ),
    nbf.v4.new_code_cell(
        "OPS = [\n"
        "    # PA1 — Rodada 2 (do PDF RODADA_02_PA1.pdf, dias do jogo 6-10 → dias R2 1-5)\n"
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
        "total_demanda = sum(o['qtd'] for o in OPS)\n"
        "print(f'{len(OPS)} OPs recebidas, total {total_demanda:,} frascos')"
    ),

    # === 4. PREÇOS ===
    nbf.v4.new_markdown_cell(
        "## 4. 📝 Preços de mercado\n\n"
        "Do `J2_FLAMENGO_ROD_X_PREÇO.docx`. Se algum PA não tem preço informado, use o preço de referência (cfg.precos_referencia)."
    ),
    nbf.v4.new_code_cell(
        "PRECOS = {\n"
        "    'PA1': 64.00,   # Rodada 2 (do docx do prof)\n"
        "    'PA2': cfg.precos_referencia['PA2'],   # sem preço → usa referência\n"
        "    'PA3': cfg.precos_referencia['PA3'],   # sem preço → usa referência\n"
        "}\n"
        "print('Preços R2:', PRECOS)"
    ),

    # === 5. FORECAST HW ===
    nbf.v4.new_markdown_cell(
        "## 5. Forecast Holt-Winters da próxima rodada (automático)\n\n"
        "O algoritmo usa o forecast pra dimensionar o **buffer de PA a estocar nos CDs**, antecipando R+1."
    ),
    nbf.v4.new_code_cell(
        "forecast_next = forecast_proxima_rodada_via_hw(rodada_n_atual=RODADA, base_dir=BASE)\n"
        "total_pa1_next = sum(v for (c, pa), v in forecast_next.items() if pa == 'PA1')\n"
        "total_pa2_next = sum(v for (c, pa), v in forecast_next.items() if pa == 'PA2')\n"
        "total_pa3_next = sum(v for (c, pa), v in forecast_next.items() if pa == 'PA3')\n"
        "print(f'Forecast Brasil rodada {RODADA+1}: PA1={total_pa1_next:,.0f} | PA2={total_pa2_next:,.0f} | PA3={total_pa3_next:,.0f}')\n"
        "print(f'Esperado FLAMENGO (~40% share): PA1={total_pa1_next*0.4:,.0f} | PA2={total_pa2_next*0.4:,.0f} | PA3={total_pa3_next*0.4:,.0f}')"
    ),

    # === 6. PLANEJAMENTO ===
    nbf.v4.new_markdown_cell(
        "## 6. Planejamento\n\n"
        "**Parâmetros editáveis:**\n"
        "- `BUFFER_PCT` = fração da previsão R+1 a estocar nos CDs (0 = nada, 1 = previsão inteira)"
    ),
    nbf.v4.new_code_cell(
        "BUFFER_PCT = 0.30  # 30% da previsão R+1 vira buffer estocado nos CDs\n"
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
        ")\n"
        "df_sol_transp = resultado['df_sol_transp']\n"
        "df_op_fabricas = resultado['df_op_fabricas']\n"
        "resumo = resultado['resumo']\n"
        "print(f'Plano gerado: {len(df_sol_transp)} transportes, produção total {sum(resumo[\"producao_total_por_pa\"].values()):,} frascos')"
    ),

    # === 7. TABELA SOL_TRANSP ===
    nbf.v4.new_markdown_cell(
        "## 7. 📋 SOL_TRANSP — copie pra aba `SOL_TRANSP` do `FLAMENGO.xlsm`\n\n"
        "Cole esta tabela a partir da linha 5 do `SOL_TRANSP` (colunas A-I)."
    ),
    nbf.v4.new_code_cell(
        "df_show_st = df_sol_transp.rename(columns={'Cidade': 'Cidade_Origem', 'Cidade_Destino': 'Cidade'})\n"
        "df_show_st = df_show_st[['Rodada', 'Origem', 'Cidade_Origem', 'Dia da Coleta', 'Modal',\n"
        "                         'Tipo do Produto', 'Qtde', 'Destino', 'Cidade']]\n"
        "df_show_st.columns = ['Rodada', 'Origem', 'Cidade', 'Dia da Coleta', 'Modal',\n"
        "                     'Tipo do Produto', 'Qtde', 'Destino', 'Cidade']  # ambas chamadas Cidade (origem e destino)\n"
        "df_show_st"
    ),

    # === 8. TABELA OP_FABRICAS ===
    nbf.v4.new_markdown_cell(
        "## 8. 📋 OP_FABRICAS — copie pra aba `OP_FABRICAS` do `FLAMENGO.xlsm`\n\n"
        "Cole nas células B7:D11 (PA1, PA2, PA3 × Dia 1..5)."
    ),
    nbf.v4.new_code_cell(
        "df_op_fabricas"
    ),

    # === 9. RESUMO ===
    nbf.v4.new_markdown_cell("## 9. Resumo da rodada"),
    nbf.v4.new_code_cell(
        "print('━' * 60)\n"
        "print(f'  RODADA {RODADA} — RESUMO')\n"
        "print('━' * 60)\n"
        "print(f'OPs atendidas:    {resumo[\"ops_atendidas\"]}/{resumo[\"ops_total\"]}')\n"
        "print(f'Qtd atendida:     {resumo[\"qtd_atendida\"]:,} frascos ({resumo[\"taxa_atendimento_pct\"]:.1f}% da qtd)')\n"
        "print(f'Qtd descartada:   {resumo[\"qtd_descartada\"]:,} frascos')\n"
        "print()\n"
        "print('Produção total por PA:')\n"
        "for pa, qtd in resumo['producao_total_por_pa'].items():\n"
        "    if qtd > 0:\n"
        "        print(f'  {pa}: {qtd:,}')\n"
        "print()\n"
        "print('Buffer estocado para próxima rodada:')\n"
        "for pa, qtd in resumo['buffer_acumulado_pa'].items():\n"
        "    if qtd > 0:\n"
        "        print(f'  {pa}: {qtd:,}')\n"
        "print()\n"
        "print('MP a comprar (toneladas):')\n"
        "tem_compra = False\n"
        "for mp, ton in resumo['mp_a_comprar_ton'].items():\n"
        "    if ton > 0:\n"
        "        print(f'  {mp}: {ton:.1f} ton')\n"
        "        tem_compra = True\n"
        "if not tem_compra:\n"
        "    print('  (nenhuma — estoque atual suficiente)')\n"
        "print()\n"
        "print('Minutos-máq utilizados por dia (cap = 10.080):')\n"
        "for d, m in enumerate(resumo['minutos_usados_por_dia'], 1):\n"
        "    pct = m / resumo['minutos_max_por_dia'] * 100\n"
        "    barra = '█' * int(pct / 5)\n"
        "    print(f'  Dia {d}: {m:>5,} min ({pct:>5.1f}%) {barra}')\n"
        "print()\n"
        "if resumo['descartadas']:\n"
        "    print('OPs descartadas:')\n"
        "    for d in resumo['descartadas']:\n"
        "        print(f'  ❌ {d.get(\"cidade\", \"?\"):<22} {d.get(\"pa\", \"?\")} qtd={d.get(\"qtd\", 0):>6,} dia_entrega={d.get(\"dia_entrega\", \"?\")} motivo={d.get(\"motivo\")}')"
    ),

    # === 10. ESCREVER NO FLAMENGO.xlsm ===
    nbf.v4.new_markdown_cell(
        "## 10. 📤 Gravar no `FLAMENGO.xlsm` (pronto pra entregar pro prof)\n\n"
        "Escreve ambas as abas `SOL_TRANSP` e `OP_FABRICAS` no arquivo,\n"
        "**preservando o VBA, as fórmulas das colunas J-Z e as demais abas**.\n\n"
        "⚠ Faça backup do FLAMENGO.xlsm antes da primeira execução, por garantia."
    ),
    nbf.v4.new_code_cell(
        "from src.io_xlsm import escrever_planos_de_df\n"
        "\n"
        "flamengo_path = BASE / 'rodadas' / 'FLAMENGO.xlsm'\n"
        "n = escrever_planos_de_df(flamengo_path, df_sol_transp, df_op_fabricas, rodada_n=RODADA)\n"
        "print(f'✅ FLAMENGO.xlsm atualizado: {n} linhas em SOL_TRANSP da Rodada_{RODADA}')\n"
        "print(f'   {flamengo_path}')\n"
        "print('   VBA e fórmulas preservadas. Pronto pra entregar pro prof.')"
    ),

    # === 11. HISTÓRICO ===
    nbf.v4.new_markdown_cell("## 11. Dashboard histórico (rodadas anteriores)"),
    nbf.v4.new_code_cell("plot_historico(BASE / 'estado')"),
]

nb["cells"] = cells

out = Path("jogo/rodada.ipynb")
out.parent.mkdir(parents=True, exist_ok=True)
nbf.write(nb, str(out))
print(f"Notebook criado em {out}")
