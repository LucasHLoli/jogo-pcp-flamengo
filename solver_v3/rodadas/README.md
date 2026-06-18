# Histórico de Rodadas — Jogo 2 FLAMENGO (arquivo do solver_v3)

Arquivo consolidado de cada rodada. Convenção de nomes dentro de `rodada_N/`:

| Arquivo | O que é |
|---|---|
| `DRE_FLAMENGO.pdf` | DRE oficial recebida no início da rodada N (resultados até R(N-1)) |
| `ESTOQUES_FLAMENGO.pdf` | Posição de estoques no fim de R(N-1) |
| `IND_FLAMENGO.pdf` | Painel de indicadores (NS, utilização, preços) |
| `RODADA_0N_PAx.pdf` | Pedido/carteira da rodada N (demanda por cidade e dia) |
| `FLAMENGO.xlsm` | Master do jogo (input/resultado validado) |
| `FLAMENGO_ENVIO_RN.xlsm` | **Nosso envio** (plano de transporte + produção submetido) |
| `SanityCheck_*_RN.xlsm` | Verificação independente do envio (11 regras + DRE recalc) |
| `RELATORIO_RN.txt` | Relatório do solver (DRE prevista, indicadores, estoque, cenários) |

## Resumo das rodadas

| Rod | Produto | Resultado semanal | Observação |
|---|---|---|---|
| R1 | — (setup) | −R$ 5.602.321 | investimento inicial |
| R2 | PA1 | −R$ 11.554.929 | montagem de estoque |
| R3 | PA3 | **+R$ 35.617.989** | primeira venda forte |
| R4 | PA3 | −R$ 1.356.169 | sem receita na rodada |
| R5 | PA1 | +R$ 1.603.752 | |
| R6 | PA2 | **+R$ 38.569.647** | buffer de PA2 pagou |
| R7 | PA2 | +R$ 28.520.764 | NS 100% (previsto cravou 0,018%) |
| **R8** | **PA3** | **+R$ 24.545.551 (previsto v3)** | NS 100%; over-build de PA3 escoou; buffer pré-posicionado p/ R9 |
| | | **Acum. até R7: +R$ 39.399.870** | |

## Modelos

- **forecast_v2 / curva × K**: demanda determinística exata (`demanda = curva_sazonal × peso_jogo`); crava o total nacional (~0,04%). Substituiu o Holt-Winters (que errava −24%..+27%).
- **frete calibrado**: viagem/peso sem doc/meia, avião 11,6 R$/km (vs 12 nominal); casa a DRE real (PA <0,1%).
- **solver_v3 (estocástico no dia)**: rodadas futuras com demanda espalhada pela distribuição de dias (d1 4,1% · d2 22,7% · d3 23,2% · d4 38,1% · d5 11,8%) + embarque direto do estoque (`ship_from_stock`), pra o solver pré-posicionar buffer e maximizar lucro esperado + NS.
