# 📦 Rodada 2 — Arquivos do Professor

**Data dos arquivos:** 21/05/2026 (entregues pelo prof após fechamento da Rodada 1)
**Local:** `rodadas/rodada_2/`

---

## 📑 Inventário (7 arquivos)

| Arquivo | Tipo | O que é |
| --- | --- | --- |
| `ESTOQUES_FLAMENGO.pdf` | PDF | Fechamento de estoques R1 (Dia 5) |
| `DRE_FLAMENGO.pdf` | PDF | Demonstrativo de resultados acumulado |
| `IND_FLAMENGO.pdf` | PDF | Painel de indicadores |
| `INFRA_FLAMENGO.xlsx` | Excel | Configuração de instalações (espelho) |
| `J2_FLAMENGO_ROD_2_PREÇO.docx` | Word | Preço de venda da Rodada 2 |
| `RODADA_02_PA1.pdf` | PDF | **OPs do varejo — só PA1** |
| `FLAMENGO.xlsm` | Excel macro | Planilha atualizada (template para você devolver) |

---

## 1. `ESTOQUES_FLAMENGO.pdf` — Posição de estoques no fim da R1

### F1 Joinville
| MP | Cap. Máx (ton) | Estoque (ton) | Ocupação | Custo Carregamento | Capital Imobilizado |
| --- | --- | --- | --- | --- | --- |
| MP1 | 127,00 | 47,00 | 37,0% | R$ 2.632 | R$ 2.444.000 |
| MP2 | 50,40 | **48,00** | **95,2% ⚠** | R$ 1.056 | R$ 912.000 |
| MP3 | 75,60 | 42,00 | 55,6% | R$ 1.722 | R$ 1.533.000 |

**Total capital imobilizado em MP: R$ 4.889.000.**

### CDs
- **CD1 (São Luís): TODOS PA zerados** (PA1=0, PA2=0, PA3=0)
- **CD2 (Santos): TODOS PA zerados**

🚨 **Conclusão**: nada chegou aos CDs até o fechamento do Dia 5 da R1. Faz sentido pelo lead time:
- Joinville → Santos = 1 dia caminhão / 1 dia navio
- Joinville → São Luís = ~9 dias caminhão / vários dias navio

Os transportes saindo no Dia 2, 3, 4, 5 só chegariam após o Dia 5. Logo, os CDs entram na R2 **vazios**, e o que você produziu na R1 está **em trânsito**.

---

## 2. `DRE_FLAMENGO.pdf` — Demonstrativo de Resultados

### 🚨 Achado crítico: nosso placeholder estrutural está ERRADO

| Item | Valor real (DRE) | Nosso placeholder | Diferença |
| --- | --- | --- | --- |
| Estruturais por rodada | **R$ 1.123.150** | R$ 850.000 | -R$ 273k subestimado |

**Custo real por rodada (sem MP/frete):**
| Item | R$ |
| --- | --- |
| Parcela terrenos | 506.968 |
| Parcela máquinas | 415.567 |
| Parcela contratação | 84 |
| Manutenção fábricas | 1.313 |
| Salário operários | 450 |
| Custo de produção (água + EE + etc) | 172.086 |
| Manutenção CDs | 26.683 |
| Carregamento de estoque MP | 5.410 |
| **TOTAL (sem MP/frete)** | **1.128.561** |

### Investimentos iniciais (Set-up)
- Terrenos: R$ 17.258.500
- Máquinas: R$ 10.500.000
- Contratação: R$ 4.050
- **Total set-up: R$ 27.762.550**

### Rodada 1 (incluindo MP/frete)
- Sub-total estruturais: R$ 922.619
- Operação fábrica (com MP R$ 4.368.000): R$ 4.541.848
- Operação CDs: R$ 26.683
- Frete (MP R$ 105.666 + PA R$ 95): R$ 105.761
- Carregamento: R$ 5.410
- **TOTAL R1: -R$ 5.602.321**

### Acumulado até 21/05/2026
- **Resultado: -R$ 57.764.027** (R$ 27,7M setup + R$ 5,6M R1 + 4 rodadas projetadas)

> Receita ainda R$ 0 (R1 não teve venda). R2 começa a vender PA1 a R$ 64.

---

## 3. `IND_FLAMENGO.pdf` — Indicadores

### Performance F1
| Item | Valor |
| --- | --- |
| Cap. máq. HH semanal | 840 horas |
| Utilização real | 100% (todas as 840h utilizadas) |
| Custo médio instalação | R$ 2,85/frasco |

### Performance Transporte (R1)
| Modal | Cap. Máx. (ton) | Ocupação | Taxa |
| --- | --- | --- | --- |
| Caminhão | 240 | 137 | **57,1%** |
| Navio | 300 | 0 | 0,0% |
| Avião | — | — | — |

**Custo médio R$ 771,21/ton.**

Distribuição de movimentação: 99,9% caminhão, 0,1% navio, 0% avião.

🤔 **Observação**: o IND diz "Navio: 0 ton, 0% utilização" mas você usou navio na R1 (3 viagens). Pode ser que o IND mostre só transportes **finalizados** até o Dia 5 — e os navios que saíram nos dias 2-4 ainda não tinham fechado.

### Vendas (R1)
Tudo `#N/D` — Rodada 1 não teve OP recebida do prof.

---

## 4. `INFRA_FLAMENGO.xlsx` — Confirmação de instalações

Mesmo conteúdo do `INSTALAÇÕES` do `FLAMENGO.xlsm`. Confirma:
- **F1 Joinville**: 7 máq, 3 turnos, 21 MO, MP1=127m², MP2=36m², MP3=42m²
- **CD1 São Luís**: PA1=110, PA2=108, PA3=873m² (tot 1.091)
- **CD2 Santos**: PA1=100, PA2=100, PA3=800m² (tot 1.000)

(Útil pra confirmar que nada mudou entre rodadas — infra é fixa.)

---

## 5. `J2_FLAMENGO_ROD_2_PREÇO.docx` — Preço de venda

> **PEDIDO DE PA 1: PREÇO DE VENDA R$ 64,00**

📌 **Pontos importantes:**
- Preço da Rodada 2 é **R$ 64,00 por frasco de PA1**.
- **Só tem preço de PA1** nesse documento. Ainda **não recebemos pedidos de PA2 nem PA3** na R2.
- Comparando com o preço de referência (R$ 80/PA1): **20% abaixo** do preço de referência. Indica concorrência forte ou mercado em baixa.

---

## 6. `RODADA_02_PA1.pdf` — OPs do varejo (PA1)

**TOTAL DE PEDIDOS PA1 NA R2: 445.135 frascos** (em 25 cidades)

### Distribuição por dia de entrega

| Dia (briefing) | Dia (rodada) | Qtd | % do total |
| --- | --- | --- | --- |
| Dia 6 | Dia 1 | 0 | 0% |
| Dia 7 | Dia 2 | 178.055 | 40% |
| Dia 8 | Dia 3 | 146.893 | 33% |
| Dia 9 | Dia 4 | 69.709 | 16% |
| Dia 10 | Dia 5 | 50.478 | 11% |

🚨 **Concentração no Dia 7 (= Dia 2 da Rodada 2)**: 40% dos pedidos vencem **logo no Dia 2**. Lead time apertado.

### Pedidos por cidade (PA1)

| Cidade | Qtd | Dia entrega (rodada) | Tem estoque? |
| --- | --- | --- | --- |
| São Paulo | 55.642 | Dia 2 | ❌ CDs vazios |
| Rio de Janeiro | 44.513 | Dia 3 | ❌ |
| Belo Horizonte | 33.385 | Dia 3 | ❌ |
| Campinas | 26.708 | Dia 2 | ❌ |
| Brasília | 25.595 | Dia 3 | ❌ |
| Salvador | 24.037 | Dia 4 | ❌ |
| Curitiba | 22.524 | Dia 2 | ❌ |
| Porto Alegre | 22.524 | Dia 2 | ❌ |
| Ribeirão Preto | 22.257 | Dia 2 | ❌ |
| Santos | 22.257 | Dia 2 | ❌ |
| Fortaleza | 20.432 | Dia 5 | ❌ |
| Recife | 18.028 | Dia 4 | ❌ |
| Goiânia | 14.333 | Dia 3 | ❌ |
| João Pessoa | 12.019 | Dia 4 | ❌ |
| Maceió | 12.019 | Dia 4 | ❌ |
| Natal | 12.019 | Dia 5 | ❌ |
| Uberlândia | 11.128 | Dia 3 | ❌ |
| Vitória | 6.677 | Dia 3 | ❌ |
| Cuiabá | 6.143 | Dia 3 | ❌ |
| Joinville | 6.143 | Dia 2 | ❌ |
| Belém | 6.009 | Dia 5 | ❌ |
| Manaus | 6.009 | Dia 5 | ❌ |
| São Luís | 6.009 | Dia 5 | ❌ |
| Campo Grande | 5.119 | Dia 3 | ❌ |
| Vitória da Conquista | 3.606 | Dia 4 | ❌ |

### 🎯 Share da FLAMENGO

A demanda histórica média Brasil de PA1 era ~**1.081.165 frascos/rodada**.

**FLAMENGO recebeu 445.135 frascos = 41% de share** — bem acima da média esperada (33% se equilibrado entre 3 empresas). Provavelmente nosso preço de R$ 64 saiu **mais barato que o concorrente**.

---

## 7. `FLAMENGO.xlsm` — Template para devolver

Mesmas 5 sheets de sempre: SOL_TRANSP, OP_FABRICAS, INSTALAÇÕES, Orig_Dest, Base_Dados.

**SOL_TRANSP já vem com 13 linhas da Rodada 1** (os transportes que você decidiu no setup):

| Rod | Origem | Cidade | Dia | Modal | Item | **Qtd (ton)** | Destino |
| --- | --- | --- | --- | --- | --- | --- | --- |
| R1 | Fornecedor | Manaus | 1 | Caminhão | MP1 | 24,0 | F1 Joinville |
| R1 | Fornecedor | Manaus | 1 | Caminhão | MP1 | 23,0 | F1 Joinville |
| R1 | Fornecedor | Cuiabá | 1 | Caminhão | MP2 | 24,0 | F1 Joinville |
| R1 | Fornecedor | Cuiabá | 1 | Caminhão | MP2 | 24,0 | F1 Joinville |
| R1 | Fornecedor | Cuiabá | 1 | Caminhão | MP2 | 0,0 | F1 Joinville |
| R1 | Fornecedor | Porto Alegre | 1 | Caminhão | MP3 | 24,0 | F1 Joinville |
| R1 | Fornecedor | Porto Alegre | 1 | Caminhão | MP3 | 18,0 | F1 Joinville |
| R1 | Fábrica | Joinville | 4 | Caminhão | PA1 | **27,2** | CD São Luís |
| R1 | Fábrica | Joinville | 4 | Navio | PA1 | **81,6** | CD Santos |
| R1 | Fábrica | Joinville | 3 | Caminhão | PA2 | **96,0** | CD São Luís |
| R1 | Fábrica | Joinville | 3 | Navio | PA2 | **137,3** | CD Santos |
| R1 | Fábrica | Joinville | 2 | Caminhão | PA3 | **115,5** | CD São Luís |
| R1 | Fábrica | Joinville | 2 | Navio | PA3 | **192,3** | CD Santos |

🚨 **DESCOBERTA IMPORTANTE — UNIDADE DE PA**

O cabeçalho da coluna 7 do SOL_TRANSP é "Qtde MP em (ton) PA". A unidade do PA não está clara, mas analisando:

- PA1 96,0 em Caminhão (cap 24 ton). Se for **frascos diretos**: 96 frascos ≈ 0,03 ton — irrelevante. Se for **ton**: 96 ton > 24 ton de cap — impossível.
- **Se for "mil frascos"**: 96 × 1.000 = 96.000 frascos = 96.000 × 0,25 g/un = 24 ton ✅ **bate EXATAMENTE com a cap do caminhão!**

✅ **CONCLUSÃO**: a coluna 7 do prof usa **toneladas para MP** e **MIL FRASCOS para PA**. O que eu corrigi antes (PA1 27,2 → 27.200) na verdade ESTAVA SOBRESCREVENDO a unidade do prof. Os números originais (27,2 / 81,6 / 96,0 / 137,3 / 115,5 / 192,3) **já estão corretos em "mil frascos"**.

🔧 **Ação necessária no código:**
- `src/io_xlsm.py::ler_sol_transp` precisa multiplicar PA por 1.000 quando ler do .xlsm.
- `src/io_xlsm.py::escrever_plano` precisa dividir PA por 1.000 quando escrever.
- OU usar coluna 7 em "mil frascos" internamente também.

⚠ **Eu havia corrigido o Rodada 1.xlsm pra 27.200 frascos antes — preciso reverter para 27,2 (mil frascos) para bater com o padrão do prof.**

---

## 🎯 Checklist do que fazer agora

1. ⚠ **Reverter** correção do Rodada 1.xlsm (voltar PA1=27.2, PA2=96.0, etc — em "mil frascos")
2. 🔧 **Ajustar `io_xlsm.py`** para fazer conversão automática mil-frascos ↔ frascos
3. 🔧 **Ajustar custo estrutural** no `factibilidade.py` de R$ 850k → R$ 1.128.561 (valor real do DRE)
4. 📥 **Importar OP da Rodada 2** (`RODADA_02_PA1.pdf` → criar `OP_Rodada_2.xlsx` no formato que o pipeline lê):
   ```
   Rodada=2, Cidade, PA=PA1, Qtd, Dia_Entrega (1-5 — converter Dia 6→1, Dia 7→2, etc.)
   ```
5. 📌 **Preço único PA1 = R$ 64**. Sem preço para PA2/PA3 ainda — produzir esses só pra estoque.
6. ▶ **Rodar pipeline da Rodada 2** com OP real + preço real e ver o cockpit.

---

## 📊 Diagnóstico estratégico inicial da R2

**Situação:**
- Brasil inteiro pede 445k frascos PA1, vencendo principalmente nos Dias 2-3 (74% do volume).
- Seus CDs estão **vazios** — não tem estoque pra atender. Tem que **produzir e enviar tudo dentro da R2**.
- Joinville → Santos = 1 dia → entrega no Sudeste/Sul é viável (produzir Dia 1, enviar Dia 1, chega Dia 2).
- Joinville → São Luís = 9 dias → entregas no Norte/Nordeste **provavelmente vão descartar** (não chega em 5 dias).

**Cidades de risco** (vencem cedo, longe de qualquer CD):
- Manaus (Dia 5) — caminhão Joinville→Manaus = 15 dias 🔴 **vai descartar**
- Belém (Dia 5) — 14 dias 🔴 **vai descartar**
- Fortaleza (Dia 5) — 9 dias 🔴 **vai descartar**
- Natal (Dia 5) — 9 dias 🔴 **vai descartar**
- São Luís (Dia 5) — 9 dias 🔴 **vai descartar**

A não ser que use **avião** (1 dia). Mas avião tem cap 1 ton (= 3.333 frascos PA1). Belém quer 6.009 → 2 viagens de avião. Manaus idem. **Avião pode salvar o Nordeste/Norte**.

**Receita máxima possível** (se atender 100%):
- 445.135 frascos × R$ 64 = **R$ 28.488.640**

Vamos calcular tudo direitinho quando rodar o pipeline.
