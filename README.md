# Jogo PCP 2 — FLAMENGO (solver de supply chain)

Otimizador para o **Jogo de Malha Logística (JML/PCP)** — empresa FLAMENGO. A cada rodada
o jogo pede **um produto** (PA1/PA2/PA3) com demanda por cidade/dia, e a gente decide
**compra de matéria-prima → produção → transporte → entrega** pra maximizar lucro mantendo
o Nível de Serviço (NS) alto. Este repositório tem o gerador de demanda, o solver MILP
multi-rodada, o verificador (sanity check) e os dados/saídas de cada rodada (até a R11).

## Como rodar

```bash
# 1) ambiente (Python 3.11+)
pip install -r requirements.txt          # mip (CBC), pandas, numpy, openpyxl, pyarrow

# 2) resolver uma rodada N (gera RELATORIO + FLAMENGO_ENVIO_RN.xlsm)
python solver_v3/solve_v3.py --rodada 11 --time_limit 400

# 3) validar o plano contra as 11 regras do jogo
python solver_v2/sanity_check_v2.py 11 solver_v3
```

Flags úteis do `solve_v3.py`: `--horizonte K` (rodadas futuras no horizonte), `--alpha`
(penalidade de NS), `--proteger` (modo cenário-por-dia que constrói buffer — ver ressalva
abaixo), `--no_write` (não grava o Excel).

## Estrutura

| Pasta | Conteúdo |
|---|---|
| `contexto/` | Regras oficiais do jogo (custos, modais, BoM, matriz de distância) |
| `data/` | Fórmula de demanda (curva sazonal) e lead times |
| `solver/` | MILP base + estado por rodada (`state.py`) + carteiras (`solve.py`) |
| `solver_v2/` | Solver multi-rodada (`milp_multi.py`), gerador de demanda exato (`forecast_v2.py`), sanity check (`sanity_check_v2.py`) |
| `solver_v3/` | Solver atual (estocástico no dia) + `rodadas/rodada_N/` com dados e saídas de cada rodada |
| `rodadas/` | Dados oficiais do jogo por rodada (DRE, estoques, indicadores, pedidos) |

Cada `rodadas/rodada_N/` traz os PDFs do jogo (DRE, ESTOQUES, IND, pedido do produto),
o `FLAMENGO.xlsm` do jogo, e — quando resolvida — o `FLAMENGO_ENVIO_RN.xlsm` (plano de
entrega) e o `SanityCheck_Gurobi_RN.xlsm`.

## Como funciona (resumo)

1. **Demanda (`forecast_v2.py`):** `demanda = curva_sazonal(rodada, PA) × peso_jogo(cidade)`.
   Determinística — crava o total nacional (erro de poucos frascos).
2. **Solver (`solver_v3/solve_v3.py`):** MILP da rodada atual (demanda conhecida) + rodadas
   futuras como cenários (1/3 PA1/PA2/PA3). Decide compra de MP (multimodal: caminhão barato
   / avião rápido), produção por dia, transporte e entrega no **dia exato**. Pré-pede MP
   barato pra próxima rodada (inter-rodada).
3. **Sanity (`sanity_check_v2.py`):** simula o plano dia-a-dia e checa as 11 regras
   (entrega no dia exato, estoques ≥0 e ≤cap, capacidade de fábrica, ≤220 transportes, etc).

## Calibrações importantes (validadas vs DRE real)

- **Carregamento de estoque:** MP = `qtd × maior_preço × 0,1%` **excluindo** MP recebida no
  último dia; PA = `qtd × preço_tabela × 1%`. Bate ao centavo.
- **Frete:** ≥80% ocupação = frete-viagem; <80% = frete-peso; **+ CT-e por transporte**;
  taxa de avião nominal (12). Erro ~1-2%.
- **Entrega só conta no DIA EXATO** do pedido (regra confirmada do jogo).

## Estado atual

Resolvido até a **R11** (PA1). NS realizado: R6-R8 100%, R9 98,9%, R10 88,4%, R11 100%
(previsto). Resultado acumulado ~R$145M (após R10).

## Ressalva conhecida

O modo `--proteger` (cenário-por-dia, que faz o solver construir buffer de PA acabado)
ainda tem um bug de arredondamento de transporte (estoque negativo no sanity). **Para
enviar, usar sempre o modo padrão** (sem `--proteger`), que passa no sanity 11/11.
