# Como o Solver Funciona — Jogo PCP 2 (Flamengo)

> Documentação técnica completa do solver MILP que planeja a rodada do jogo.
> Cobre desde **a entrada de dados** até **a tomada de decisão matemática** e **a saída final** (`FLAMENGO_SOLVER.xlsm`).

---

## Índice

1. [Visão geral em 30 segundos](#1-visão-geral-em-30-segundos)
2. [Arquitetura — o caminho dos dados](#2-arquitetura--o-caminho-dos-dados)
3. [Entradas: de onde vem cada dado](#3-entradas-de-onde-vem-cada-dado)
4. [Estado da rodada — `state.py`](#4-estado-da-rodada--statepy)
5. [Forecast de demanda — `forecast_r4.py`](#5-forecast-de-demanda--forecast_r4py)
6. [O modelo MILP — peça por peça](#6-o-modelo-milp--peça-por-peça)
7. [Função objetivo](#7-função-objetivo)
8. [Restrições — todas as regras do jogo, em equações](#8-restrições--todas-as-regras-do-jogo-em-equações)
9. [Pipeline de execução (R3 e R4+)](#9-pipeline-de-execução-r3-e-r4)
10. [Saídas: arquivos gerados e o que eles contêm](#10-saídas-arquivos-gerados-e-o-que-eles-contêm)
11. [Validação automática](#11-validação-automática)
12. [Glossário rápido](#12-glossário-rápido)

---

## 1. Visão geral em 30 segundos

O solver é um **MILP (Mixed-Integer Linear Programming)** escrito em [`python-mip`](https://www.python-mip.com/) usando o resolvedor **CBC**. Ele recebe:

- O **estado inicial** da rodada (estoques, MP em-trânsito, OPs oficiais)
- O **forecast** da rodada seguinte (Holt-Winters)
- As **regras físicas do jogo** (BoM, lead times, capacidades)

E entrega:

- O **plano ótimo** de produção, transporte e compras
- Maximizando **lucro horizonte (R3 + R4)** com NS ≥ 80%
- Respeitando **TODAS** as restrições do jogo

A saída final é o `FLAMENGO_SOLVER.xlsm`, pronto pra subir no jogo.

---

## 2. Arquitetura — o caminho dos dados

```
┌─────────────────────────┐
│ 1. ENTRADAS             │
│  • rodadas/rodada_N/    │
│    FLAMENGO.xlsm        │  (template do jogo)
│  • PDF Estoques         │  (estoque inicial)
│  • data/lead_times.json │  (tabela Orig_Dest)
│  • data/freight_*.parquet│
│  • OPs oficiais R_N     │  (do PDF RODADA_0X)
│  • Histórico 2 anos     │  (data/demanda_long.parquet)
└────────────┬────────────┘
             │
             ▼
┌─────────────────────────┐
│ 2. PREPARAÇÃO           │
│  state.py               │  ← consolida estado
│  forecast_r4.py         │  ← prevê demanda R4 (HW)
└────────────┬────────────┘
             │
             ▼
┌─────────────────────────┐
│ 3. MODELO MILP          │
│  milp_global.py         │  ← R3 dia-a-dia + R4 buffer
│  milp_horizon.py        │  ← R3+R4 ambos dia-a-dia
│  milp.py                │  ← rodada única
└────────────┬────────────┘
             │ resolve com CBC
             ▼
┌─────────────────────────┐
│ 4. PÓS-PROCESSAMENTO    │
│  converter_para_buffer  │  ← remove entregas R4 prematuras
│  mesclar_historico      │  ← agrega R1..R_N
└────────────┬────────────┘
             │
             ▼
┌─────────────────────────┐
│ 5. SAÍDAS               │
│  FLAMENGO_SOLVER.xlsm   │  ← arquivo do jogo (R1..R_N)
│  SanityCheck_Solver.xlsm│  ← 9 abas de auditoria
│  Comparativo.xlsx       │  ← solver vs heurística
└─────────────────────────┘
```

---

## 3. Entradas: de onde vem cada dado

| Dado | Tipo | Fonte | Quem usa |
|---|---|---|---|
| **Estoques iniciais MP/PA** | dict | PDF `ESTOQUES_FLAMENGO.pdf` (digitado manual em `state.py:estado_r3_flamengo()`) | `state.py` |
| **MP em-trânsito** | lista | Lido do `SOL_TRANSP` histórico (linhas Fornecedor→F1 de rodadas anteriores cuja chegada cai em R_N) | `state.py:consolidar_estado()` |
| **OPs oficiais R3** | lista | PDF `RODADA_03_PA3.pdf` — digitadas em `solver/solve.py:ops_r3()` | `milp.py`, `milp_global.py` |
| **Tabela Lead Times** | JSON | Extraída da aba `Orig_Dest` do FLAMENGO original (oficial do jogo) | Todo solver |
| **Distâncias km** | parquet | `data/distancias_{modal}.parquet` (aba `Orig_Dest`) | Cálculo de frete |
| **Custos de frete** | parquet | `data/freight_costs.parquet` (frete-viagem + frete-peso por modal) | Função objetivo |
| **Densidades/BoM/Vel** | hardcoded | Constantes em `milp.py` | Restrições físicas |
| **Capacidades F1/CDs** | xlsm | Aba `INFRAESTRUTURA` do FLAMENGO via `src/io_xlsm.ler_instalacoes()` | `state.py` |
| **Histórico 2 anos** | parquet | `data/demanda_long.parquet` | `forecast_r4.py` (HW) |
| **Preços PA** | hardcoded | R$ 80/PA1, 50/PA2, 32/PA3 (R3 PA3); 25/PA3 R4 | Receita |
| **Custos MP por fornecedor** | dict | `cfg.fornecedores[mp]` (`src/config.py`) | Compra MP |

### Como o PDF Estoques vira código

```python
# state.py, linha 203
estoque_mp = {"MP1": 78.98, "MP2": 50.36, "MP3": 48.14}  # ton, fim R2
estoque_pa = {"CD1": {...}, "CD2": {...}}                 # un por PA
```

Esses números são digitados **uma vez por rodada** a partir do PDF que o jogo entrega. (Poderia ser automatizado com OCR — mas como são 6 números, vale mais o tempo do que automatizar.)

---

## 4. Estado da rodada — `state.py`

A primeira tarefa antes de chamar o solver é **consolidar o estado**. Tudo que o modelo precisa saber sobre o "mundo" no Dia 1 da rodada N entra num dataclass:

```python
@dataclass
class EstadoRodada:
    rodada: int                                      # ex: 3
    estoque_mp_ton: Dict[str, float]                 # {"MP1": 78.98, ...}
    estoque_pa_cd: Dict[str, Dict[str, int]]         # {"CD1": {"PA2": 0, ...}, ...}
    mp_em_transito: List[Dict]                       # [{"dia_rel":1, "mp":"MP1", "qtd":8.7, ...}]
    historico_dre: List[float]                       # [R1_lucro, R2_lucro]
    cap_mp_ton: Dict[str, float]                     # capacidade F1
    cap_pa_cd_un: Dict[str, Dict[str, int]]          # capacidade CDs
    cap_min_dia: int                                 # 10080
    fab_cidade: str                                  # "Joinville"
    cds_info: Dict[str, str]                         # {"CD1": "Belo Horizonte", ...}
```

### O truque do MP em-trânsito

Quando você compra MP em R2 com Navio Manaus→Joinville (lead 9 dias), o material pode chegar **dentro de R3**. O `state.py` percorre o histórico do `SOL_TRANSP`, calcula `dia_chegada = dia_part + lead_time`, e se cair em `[Dia 11..15]` (R3 absoluto), adiciona em `mp_em_transito` com `dia_rel ∈ {1..5}`.

```python
# state.py, linhas 138-178 (resumido)
for cada linha "Fornecedor" no SOL_TRANSP de rodadas <N:
    lt_v = lead_time[modal][origem][Joinville]
    dia_abs_cheg = dia_part_abs + lt_v
    if dia_inicio_N <= dia_abs_cheg <= dia_fim_N:
        mp_em_transito.append({...})
```

Isso é essencial: sem isso o solver acharia que MP1=78.98t é tudo que tem em R3, quando na verdade tem +8.7t chegando no Dia 1 (de uma compra feita em R2).

---

## 5. Forecast de demanda — `forecast_r4.py`

R4 só tem **PA2**. O solver precisa saber **quanto PA2 cada cidade vai pedir** para decidir o tamanho do buffer.

### Holt-Winters tunado

`src/planner_manual.py:forecast_proxima_rodada_via_hw()`:

1. Lê 2 anos de histórico (`data/demanda_long.parquet`)
2. Para cada (cidade, PA), ajusta um modelo **Holt-Winters aditivo** com sazonalidade semanal
3. Prevê o próximo ponto (rodada N+1)
4. Aplica `share_flamengo = 0.40` (market share assumido)

```python
# forecast_r4.py
def forecast_ops_r4(rodada_n_atual=3, share_flamengo=0.40, dia_entrega=3):
    fc = forecast_proxima_rodada_via_hw(...)
    return [{"cidade": c, "pa": "PA2", "qtd": int(q * share_flamengo),
             "dia_entrega": 3}
            for (c, pa), q in fc.items() if pa == "PA2" and q > 0]
```

`dia_entrega=3` (meio da rodada) dá ao solver flexibilidade para produzir nos dias 1-3 e entregar com lead time razoável.

---

## 6. O modelo MILP — peça por peça

Aqui é onde a mágica acontece. Vou explicar **a anatomia do `milp_global.py`** (o mais completo).

### 6.1 Conjuntos (sets)

| Símbolo | Significado | Valor |
|---|---|---|
| `T` | Dias da rodada R3 | {1,2,3,4,5} |
| `PA` | Produtos acabados | {PA1, PA2, PA3} |
| `MP` | Matérias-primas | {MP1, MP2, MP3} |
| `CD` | Centros de distribuição | {CD1=BH, CD2=Santos} |
| `C` | Cidades de varejo | 25 cidades |
| `M` | Modais | {Avião, Caminhão, Navio} |
| `F_mp` | Fornecedores de MP | varia por MP |
| `OPs` | Ordens de produção R3 | 25 OPs PA3 |
| `C4` | Cidades com demanda R4 | subset com forecast > 0 |

### 6.2 Parâmetros (dados — não decidem nada)

```
vel[pa]                  un/min      {PA1:15, PA2:30, PA3:60}
BoM[pa][mp]              g/un        {PA2:{MP1:75, MP2:125, MP3:50}, ...}
peso_un_ton[pa]          t/un        {PA1:0.0003, PA2:0.00025, PA3:0.00015}
cap_min_dia              min/dia     7×3×8×60 = 10.080
cap_mp[mp]               ton         área × 2m × densidade
cap_pa_cd[cd][pa]        un          área × 2m × densidade / peso
cap_modal_ton[m]         t/viagem    {Avião:1, Caminhão:24, Navio:100}
cap_modal_un[m][pa]      un/viagem   floor(cap_ton / peso_un)
lt[m][o][d]              dias        tabela lead_times.json
km[m][o][d]              km          parquet distâncias
frete_viagem[m]          R$/km       {Caminhão:8, Navio:5, Avião:12}
frete_peso[m]            R$/(km·t)   {Caminhão:0.5, Navio:0.075, Avião:18}
doc_modal[m]             R$/viagem   {Caminhão:100, Navio:50, Avião:200}
preco_mp[forn]           R$/t        cfg.fornecedores
preco_pa[pa]             R$/un       {PA1:80, PA2:50, PA3:32}
estoque_ini_mp[mp]       ton         de state.estoque_mp_ton
arrivals_mp[t][mp]       ton         de state.mp_em_transito
forecast_r4[c]           un PA2      forecast_ops_r4
```

### 6.3 Variáveis de decisão

| Variável | Domínio | Significado |
|---|---|---|
| `x_op[op]` | ∈ {0,1} | atende a OP no dia exato? |
| `prod[t,pa]` | ℤ⁺ | un produzidas no dia t |
| `n_buy[t,mp,f]` | ℤ⁺ | nº de viagens de compra MP |
| `qty_buy[t,mp,f]` | ℝ⁺ | toneladas compradas |
| `n_f1cd[t,cd,pa,m]` | ℤ⁺ | nº viagens F1→CD |
| `qty_f1cd[t,cd,pa,m]` | ℝ⁺ | un transportadas F1→CD |
| `n_cdv[t,cd,c,pa,m]` | ℤ⁺ | nº viagens CD→Varejo |
| `qty_cdv[t,cd,c,pa,m]` | ℝ⁺ | un transportadas CD→Varejo |
| `stk_mp[t,mp]` | ℝ⁺ | estoque MP em F1 no fim do dia t |
| `stk_pa[t,cd,pa]` | ℝ⁺ | estoque PA no CD no fim do dia t |
| `x_r4[c]` | ∈ {0,1} | atende cidade c em R4 via buffer? |

**Por que `n_*` é inteiro e `qty_*` é contínuo?** Porque você só pode despachar **viagens inteiras** (não dá pra mandar "0,7 caminhão"), mas a quantidade dentro de cada viagem pode ser fracionada — o solver decide quantos caminhões cheios + parciais.

Para R3 sozinho: ~580 variáveis + 380 restrições.
Para horizonte R3+R4: ~1.140 variáveis + 760 restrições.

---

## 7. Função objetivo

```
max  receita_R3 + α × receita_R4_esperada
   − custo_compra_MP
   − custo_frete
   − custo_doc                            (CT-e)
   − custo_carregamento_MP                (estoque MP fim R3 × maior_preço × 1%)
   − custo_carregamento_PA                (estoque PA fim R3 × preço × 1%)
```

Onde `α = 1.0` no modelo horizonte completo. Em `milp.py` (rodada única) o objetivo é só R3.

### 7.1 Receita

```
receita_R3 = Σ_op x_op[op] × Q[op] × preco_pa[op.pa]
receita_R4 = Σ_c   x_r4[c] × Q4[c] × preco_pa["PA2"]
```

A receita só conta se a OP foi **realmente atendida no dia exato** (`x_op = 1`). Senão é descarte = R$ 0.

### 7.2 Custo de compra MP

```
custo_compra_MP = Σ_{t,mp,f} qty_buy[t,mp,f] × preco_mp[f]
```

O solver prefere o fornecedor mais barato, **mas pode escolher mais caros** se o lead time obrigar (ex: comprar MP1 de Belém com lead 1 dia ao invés de Manaus com lead 3 dias).

### 7.3 Custo de frete (a parte complicada)

Regra do jogo:
- Se ocupação ≥ 80% da capacidade → paga **frete-viagem** (R$/km × km × n_viagens)
- Se ocupação < 80% → paga **frete-peso** (R$/(km·t) × km × peso)

Linearizar isso em MILP é difícil (envolve produto de variáveis binárias × contínuas). **Simplificação adotada na v1**: pagamos sempre frete-peso. Isso **subestima** o custo quando o solver usa viagens cheias, mas é convexo e mais simples. Refino possível: introduzir `y_viagem ∈ {0,1}` com big-M.

```
custo_frete ≈ Σ qty × peso_un × km × frete_peso[m]   (simplificação)
            + Σ n_viagens × doc_modal[m]              (CT-e exato)
```

### 7.4 Custo de carregamento

Estoque parado no fim da rodada paga **1%** do valor por dia (não detalhado dia a dia no modelo — fim de rodada apenas, como o jogo cobra):

```
carreg_MP = Σ_mp stk_mp[5,mp] × maior_preço_mp[mp] × 0.01
carreg_PA = Σ_{cd,pa} stk_pa[5,cd,pa] × preco_pa[pa] × 0.01
```

`maior_preço_mp` = preço do fornecedor mais caro de cada MP (regra oficial).

---

## 8. Restrições — todas as regras do jogo, em equações

### R1 — PA chega no dia EXATO da OP (regra ouro)

Para cada OP `(c, pa, Q, d_E)`:

```
Σ_{t,cd,m : t + lt[m][cd_cid][c] == d_E}  qty_cdv[t,cd,c,pa,m]  =  Q × x_op[op]
Σ_{t,cd,m : t + lt[m][cd_cid][c] != d_E}  qty_cdv[t,cd,c,pa,m]  =  0
```

**Tradução**: a soma de tudo que sai dos CDs com chegada no dia certo precisa bater com a OP (se atendida). Tudo que chega em outros dias é proibido = descarte.

### R2 — PA sai da F1 no mesmo dia da produção

```
∀ t, pa:    Σ_{cd,m} qty_f1cd[t,cd,pa,m]  =  prod[t,pa]
```

### R3 — Capacidade modal por viagem

```
qty_f1cd[t,cd,pa,m]  ≤  n_f1cd[t,cd,pa,m] × cap_modal_un[m][pa]
qty_cdv[t,cd,c,pa,m] ≤  n_cdv[t,cd,c,pa,m] × cap_modal_un[m][pa]
qty_buy[t,mp,f]      ≤  n_buy[t,mp,f] × cap_modal_ton["Caminhão"]
```

(MP só viaja em caminhão; PA viaja nos 3 modais.)

### R4 — Capacidade da fábrica

```
∀ t:    Σ_pa prod[t,pa] / vel[pa]  ≤  cap_min_dia
```

10.080 min/dia = 7 máquinas × 3 turnos × 8h × 60min.

### R5 — Balanço MP em F1 (dia a dia)

```
∀ t, mp:
  stk_mp[t,mp] = stk_mp[t-1,mp]
               + arrivals_mp[t,mp]                              (em-trânsito de rodadas anteriores)
               + Σ_{f : t-lt[Cam][f][Joinville] ≥ 1} qty_buy[t-lt, mp, f]
               − Σ_pa prod[t,pa] × BoM[pa,mp] / 10⁶
```

Onde `stk_mp[0,mp] = estoque_ini_mp[mp]`.

### R6 — Capacidade MP em F1

```
∀ t, mp:    stk_mp[t,mp]  ≤  cap_mp[mp]
```

Excesso = descarte → o solver evita comprar mais do que cabe.

### R7 — Balanço PA nos CDs (dia a dia)

```
∀ t, cd, pa:
  stk_pa[t,cd,pa] = stk_pa[t-1,cd,pa]
                  + Σ_m qty_f1cd[t-lt[m][Joinville][cd_cid], cd, pa, m]
                  − Σ_{c,m} qty_cdv[t,cd,c,pa,m]
```

### R8 — Capacidade dos CDs

```
∀ t, cd, pa:    stk_pa[t,cd,pa]  ≤  cap_pa_cd[cd][pa]
```

### R9 — Buffer PA2 para R4 (modelo global)

Cada cidade R4 atendida via buffer é mapeada para um CD (o mais barato):

```
∀ cd:   stk_pa[5, cd, "PA2"]  ≥  Σ_{c : cidade_to_cd_r4[c] == cd}  x_r4[c] × Q4[c]
```

### R10 — Nível de Serviço mínimo

```
Σ_op x_op[op] × Q[op]  ≥  ns_min × Σ_op Q[op]      (≥ 80%)
Σ_c  x_r4[c] × Q4[c]   ≥  ns_min × Σ_c Q4[c]       (≥ 80%)
```

### R11 — Total de transportes ≤ 220

```
Σ n_buy + Σ n_f1cd + Σ n_cdv  ≤  220   (por rodada)
```

### R12 — Não-negatividade e integralidade

Todas as variáveis `qty_*`, `stk_*` ≥ 0; `x_op`, `x_r4` ∈ {0,1}; `n_*`, `prod` ∈ ℤ⁺.

---

## 9. Pipeline de execução (R3 e R4+)

### Para R3 (já rodado)

```bash
# 1) Roda o solver global (R3 + forecast R4 como buffer)
python solver/solve_global.py --rodada 3 --time_limit 300

# 2) (Opcional) converte pra plano "buffer puro" — remove entregas R4 prematuras
python solver/converter_para_buffer.py

# 3) Valida 12 regras
python solver/validar_solver.py

# 4) Gera SanityCheck Excel auditável
python solver/sanity_check.py --rodada 3

# 5) Mescla histórico R1+R2+R3 (auto no fim do solver)
# Saída final: solver/rodadas/rodada_3/FLAMENGO_SOLVER.xlsm
```

### Para R4 (futuro — automático)

```bash
# 1) Atualizar estado: o jogo entrega rodada_4/FLAMENGO.xlsm com R1+R2+R3 reais
#    e PDF ESTOQUES com saldos do fim de R3.

# 2) Editar state.py:estado_r4_flamengo() com os novos saldos do PDF.

# 3) Rodar
python solver/solve_global.py --rodada 4 --time_limit 300

# O hook automático em solve_global.py chama:
#   mesclar_historico(rodada_alvo=4)
# que produz FLAMENGO_SOLVER.xlsm com R1..R4 já mesclados.
```

---

## 10. Saídas: arquivos gerados e o que eles contêm

| Arquivo | Localização | Conteúdo |
|---|---|---|
| `FLAMENGO_SOLVER.xlsm` | `solver/rodadas/rodada_N/` | **Arquivo final pra submeter**: SOL_TRANSP com R1..R_N + OP_FABRICAS do plano R_N |
| `FLAMENGO_BUFFER.xlsm` | idem | Plano puro do solver (só R_N) — backup |
| `FLAMENGO.xlsm` | idem | Cópia espelho do SOLVER (compatibilidade) |
| `SanityCheck_Solver.xlsm` | idem | 9 abas: Resumo, OPs detalhe, Transportes, Produção, Estoque MP, Estoque PA, Estoque Final, DRE, Checks |
| `Comparativo.xlsx` | idem | Solver vs Heurística (3 vias) |

### Estrutura do SOL_TRANSP (saída)

| Col A | Col B | Col C | Col D | Col E | Col F | Col G | Col H | Col I |
|---|---|---|---|---|---|---|---|---|
| Rodada | Origem | Cidade origem | Dia coleta | Modal | Tipo produto | Qtde | Destino | Cidade destino |
| Rodada_3 | Fornecedor | Belém | Dia 11 | Caminhão | MP1 | 23.97 | Fábrica | Joinville |
| Rodada_3 | Fábrica | Joinville | Dia 11 | Avião | PA3 | 6.666 | CD | Belo Horizonte |
| Rodada_3 | CD | Belo Horizonte | Dia 12 | Avião | PA3 | 117.573 | Varejista | Brasília |

---

## 11. Validação automática

Toda saída passa por **12 checagens** em `solver/validar_solver.py`:

| # | Regra | Como é validada |
|---:|---|---|
| 1 | PA chega no dia EXATO | Simula `dia_part + lt` para cada CD→Varejo |
| 2 | PA sai F1 no mesmo dia da produção | Compara prod[t,pa] vs Σ envio F1→CD no dia t |
| 3 | MP sem espaço → descarte = 0 | Simula MP dia a dia com cap |
| 4 | Transportes ≤ 220 | Conta linhas R3 |
| 5 | Cap fábrica ≤ 10.080 min/dia | Σ prod/vel por dia |
| 6 | Cap modal por viagem | Cada linha vs cap modal |
| 7 | PA CD nunca negativo | Simulação CD dia a dia |
| 8 | PA CD ≤ cap CD | idem |
| 9 | MP F1 nunca negativo | Simulação MP F1 |
| 10 | MP do fornecedor mais barato | Compara com `min(cfg.fornecedores[mp])` |
| 11 | Σ produção = Σ envio F1→CD | Por dia e por PA |
| 12 | Estado MP coerente com em-trânsito R2 | Cruza com `state.mp_em_transito` |

Se algum falhar, aparece `❌` e a linha problemática é impressa.

---

## 12. Glossário rápido

| Termo | Significado |
|---|---|
| **MILP** | Mixed-Integer Linear Programming — otimização linear com variáveis inteiras |
| **CBC** | Coin-or Branch and Cut — solver open-source usado pelo python-mip |
| **BoM** | Bill of Materials — quanto de cada MP entra em cada PA |
| **OP** | Ordem de Produção — pedido oficial do jogo (cidade, PA, qty, dia) |
| **NS** | Nível de Serviço — % de frascos entregues no dia exato |
| **Lead time (lt)** | Dias entre coleta e chegada (tabela `Orig_Dest`) |
| **Buffer R4** | PA2 estocado nos CDs em R3 antecipando a demanda de R4 |
| **Em-trânsito** | Carga já comprada/despachada mas ainda não chegou |
| **Holt-Winters (HW)** | Modelo de previsão com tendência + sazonalidade |
| **Share Flamengo** | Market share assumido (40%) ao distribuir forecast nacional |

---

## Apêndice A — Heurística vs Solver

`src/planner_v3.py` é a **heurística gulosa** (rápida, sempre factível, míope a R4). O solver é **MILP ótimo** (mais lento, vê horizonte). Para R3:

| | Heurística | Solver |
|---|---:|---:|
| Tempo de execução | ~1s | ~30-300s |
| NS R3 | 100% | 100% |
| Lucro R3 isolado | R$ 36,8M | R$ 35,4M |
| Buffer PA2 R4 | 79k frascos | 464k frascos |
| Util. fábrica média | 49,7% | 75,1% |
| Lucro horizonte (R3+R4) estim. | R$ 40M | **R$ 58M** |

A heurística é mantida como **fallback**: se o solver não convergir, ainda temos plano.

---

## Apêndice B — Por que escolhemos MILP em vez de heurística pura

1. **Garantia matemática**: MILP encontra o ótimo (ou prova que não existe melhor).
2. **Trade-off explícito**: a função objetivo deixa visível quanto vale cada R$ de margem vs cap modal.
3. **Restrições rígidas**: o jogo tem 12 regras "duras" — qualquer violação descarta material. MILP modela isso direto.
4. **Multi-rodada**: o horizonte R3+R4 é difícil de raciocinar manualmente; o solver tira essa decisão do braço.

A heurística é uma sanity-check útil mas não consegue antecipar R4 com o mesmo rigor.
