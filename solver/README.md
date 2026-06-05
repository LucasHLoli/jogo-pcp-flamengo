# Solver MILP — Jogo PCP 2 Flamengo

Resolver formal do problema de planejamento da rodada via MILP (Mixed-Integer
Linear Programming), usando `python-mip` (CBC). Mantido SEPARADO da heurística
em `src/planner_v3.py` por segurança: se o solver falhar ou der resultado
estranho, ainda temos a heurística funcionando.

## Estrutura

```
solver/
├── README.md           — este arquivo
├── state.py            — consolida estado multi-rodada (MP em-trânsito etc)
├── milp.py             — modelo formal Pyomo-style em python-mip
├── solve.py            — entry point (cli): rodada N → FLAMENGO.xlsm
├── data/
│   └── historico_state.json  — cache do estado consolidado
└── tests/
    └── test_solver_r3.py
```

## Formulação MILP

### Sets / Índices

- `T = {1,..,5}` dias da rodada
- `PA = {PA1, PA2, PA3}`
- `MP = {MP1, MP2, MP3}`
- `CD = {CD1, CD2}` centros de distribuição
- `C` cidades de varejo (subset de 25)
- `M = {Avião, Caminhão, Navio}` modais
- `F[mp]` fornecedores possíveis de cada MP
- `OPs` ordens de produção da rodada (cidade, PA, qty, dia_entrega)

### Parâmetros (dados de entrada)

- `cap_min_dia` minutos disponíveis por dia (= máq × turnos × 8 × 60)
- `vel[pa]` un/min por PA
- `BoM[pa][mp]` gramas de MP por un de PA
- `cap_mp[mp]` ton de MP suportadas em F1
- `cap_pa_cd[cd][pa]` un de PA suportadas em CD
- `cap_modal_ton[m]` ton por viagem por modal
- `cap_modal_un[m][item]` un/ton por viagem (PA ou MP)
- `lt[m][o][d]` lead time em dias úteis (lookup oficial Orig_Dest)
- `km[m][o][d]` distância
- `frete_v[m]`, `frete_p[m]`, `doc[m]` custos do modal
- `preco_mp[forn]` custo/ton MP
- `preco_pa[pa]` preço de venda (para receita)
- `estoque_ini_mp[mp]` início da rodada (em F1)
- `arrivals_mp[t][mp]` MP chegando dia t (das rodadas anteriores)
- `estoque_ini_pa_cd[cd][pa]` PA pré-estocado nos CDs

### Variáveis de decisão

- `x_op[op]` ∈ {0,1}: atende OP no dia exato (sim/não)
- `prod[t,pa]` ∈ ℤ+: produção
- `n_buy[t,mp,forn]` ∈ ℤ+: número de caminhões cheios comprados
- `qty_buy[t,mp,forn]` ∈ ℝ+: ton (≤ n_buy × cap_cam)
- `n_f1cd[t,cd,pa,m]` ∈ ℤ+: número de viagens F1→CD
- `qty_f1cd[t,cd,pa,m]` ∈ ℝ+: un PA transportadas
- `n_cdv[t,cd,c,pa,m]` ∈ ℤ+: número de viagens CD→Varejo
- `qty_cdv[t,cd,c,pa,m]` ∈ ℝ+: un PA transportadas
- `stk_mp[t,mp]` ∈ ℝ+: estoque MP F1 no fim do dia t
- `stk_pa[t,cd,pa]` ∈ ℝ+: estoque PA no CD no fim do dia t

### Restrições

#### 1. Cap fábrica

```
Σ_pa prod[t,pa] / vel[pa] ≤ cap_min_dia       ∀ t
```

#### 2. Cap modal (viagens contêm a quantidade)

```
qty_f1cd[t,cd,pa,m] ≤ n_f1cd[t,cd,pa,m] × cap_modal_un[m][pa]   ∀ t,cd,pa,m
qty_cdv[t,cd,c,pa,m] ≤ n_cdv[t,cd,c,pa,m] × cap_modal_un[m][pa]
qty_buy[t,mp,forn] ≤ n_buy[t,mp,forn] × cap_modal_ton["Caminhão"]
```

#### 3. PA sai da F1 no MESMO dia em que é produzido

```
Σ_cd,m qty_f1cd[t,cd,pa,m] = prod[t,pa]    ∀ t,pa
```

#### 4. CD balance (chegadas - saídas)

```
stk_pa[t,cd,pa] = stk_pa[t-1,cd,pa]
                  + Σ_m qty_f1cd[t-lt(m), cd, pa, m]       (chegadas)
                  − Σ_c,m qty_cdv[t,cd,c,pa,m]              (saídas)
```

#### 5. CD cap

```
stk_pa[t,cd,pa] ≤ cap_pa_cd[cd][pa]    ∀ t,cd,pa
```

#### 6. MP balance F1

```
stk_mp[t,mp] = stk_mp[t-1,mp]
              + arrivals_mp[t,mp]                              (em-trânsito de rodadas anteriores)
              + Σ_forn qty_buy[t-lt_forn, mp, forn]           (compras desta rodada que chegaram)
              − Σ_pa prod[t,pa] × BoM[pa,mp] / 10^6           (consumo)
```

#### 7. MP cap F1

```
stk_mp[t,mp] ≤ cap_mp[mp]    ∀ t,mp
```

#### 8. Entrega no dia EXATO para cada OP

Para cada OP = (cidade c, PA pa, qty Q, dia_entrega d_E):

```
Σ_t,cd,m: t + lt(cd,c,m) == d_E   qty_cdv[t,cd,c,pa,m] = Q × x_op[op]
Σ_t,cd,m: t + lt(cd,c,m) != d_E   qty_cdv[t,cd,c,pa,m] = 0   (proibido)
```

#### 9. Nível de Serviço mínimo 80%

```
Σ_op x_op[op] × Q[op] / Σ_op Q[op] ≥ 0.80
```

#### 10. Total transportes ≤ 220

```
Σ n_buy + Σ n_f1cd + Σ n_cdv ≤ 220
```

### Função objetivo

```
min Σ qty_buy × preco_mp[forn]                     (compra MP)
  + Σ n_v × custo_viagem(m, ocup, km)              (frete — linearizado com big-M)
  + Σ doc[m] × n_viagens                            (CT-e)
  + Σ stk_mp[5,mp] × maior_preço_mp × 0.01         (carregamento MP)
  + Σ stk_pa[5,cd,pa] × preco_pa[pa] × 0.01        (carregamento PA)
```

#### Tratamento do frete (ocupação ≥80% paga viagem, <80% paga peso)

Linearização: para cada viagem `v`, criamos:
- `y_viagem[v]` ∈ {0,1}: paga frete-viagem (1) ou frete-peso (0)
- `Big-M` para ativar a regra apenas quando `ocup ≥ 0.8`

(Simplificação aceita: usar **APENAS frete-peso** para todas as viagens nesta
v1 do solver. Sub-estima quando ocup ≥ 80% mas é convexa e mais simples. Refino
em v2.)

## Execução

```bash
python solver/solve.py --rodada 3
```

Lê estado consolidado de `solver/data/`, monta modelo, resolve com CBC, escreve
em `rodadas/rodada_3/FLAMENGO.xlsm` e gera relatório.

## Heurística vs Solver

Mantemos as duas implementações:
- `src/planner_v3.py` (heurística greedy) — RÁPIDA, sempre dá solução factível
- `solver/milp.py` (MILP) — ÓTIMA, mas demora alguns segundos/minutos

Use o solver para validar o ótimo. Use a heurística para iterações rápidas.
