# 00 - Contexto Geral: Jogo de PCP / Jogo de Malha Logística (JML 126)

> Este é o **documento mestre** do projeto. Consolida todo o material original (4 arquivos)
> em um briefing único, pronto para alimentar o desenvolvimento do jogo digital.
>
> Para detalhes ler também:
> - [01_info_geral.md](01_info_geral.md) — parâmetros, custos, modais, densidades
> - [02_historico_demanda.md](02_historico_demanda.md) — demanda real 2 anos × 48 rodadas × 25 cidades × 3 PAs
> - [03_matriz_distancia.md](03_matriz_distancia.md) — matrizes aérea, marítima e terrestre
> - [04_aula_jml.md](04_aula_jml.md) — slides com a mecânica do jogo original
>
> **Relatórios técnicos:**
> - 📈 [forecast/FORECAST.md](forecast/FORECAST.md) — modelagem de demanda completa
>   (EDA → escolha do modelo → tunagem Holt-Winters → descoberta da fórmula geradora)
> - 🧮 [solver/SOLVER.md](solver/SOLVER.md) — Network Design (MILP Pyomo + HiGHS)
>   (formulação matemática, 10 cenários, sanity check, plano de jogo)
> - 📋 [solver/ENTREGA_1A_DECISAO.md](solver/ENTREGA_1A_DECISAO.md) — ficha pronta
>   para entregar ao professor (1ª Decisão: localização, máquinas, MO)

---

## 1. O que é o projeto

**Origem:** dissertação de mestrado de **Edgard Liberali Filho**, orientado por **Prof. Dr. Daniel de Oliveira Mota**, no programa **CISLog – Centro de Inovação em Sistemas Logísticos (POLI-USP)**.

**Tese:** _"Jogo de Malha Logística: resgatando o jogo de empresa como metodologia ativa de ensino no curso de Engenharia de Produção"_.

**Objetivo pedagógico:** sedimentar conhecimentos em **Network Design** e **Estratégias de Estoques** com ênfase no cenário brasileiro.

**O que o usuário (Lucas) quer construir:** um **jogo digital de supply chain** baseado nesse material — provavelmente um simulador/SaaS onde times tomam decisões de rede logística e PCP ao longo de várias rodadas e competem.

---

## 2. Cadeia simulada — visão geral

```
┌─────────────────┐    ┌──────────┐    ┌─────────┐    ┌─────────────┐
│ Fornecedores MP │ -> │ Fábricas │ -> │   CDs   │ -> │  Varejistas │
│   (6 fixos)     │    │  (≤ 2)   │    │  (≤ 4)  │    │ (25 cidades)│
└─────────────────┘    └──────────┘    └─────────┘    └─────────────┘
        \____________________________________________________/
                       3 modais: Avião | Caminhão | Navio
```

- **Fluxos:** bens, financeiro, informação.
- **Cada jogo:** 3 empresas competindo, 4 alunos por empresa.
- **Horizonte:** 48 rodadas/ano × 2 anos (Ano1 + Ano2 = 96 períodos no histórico).
- **Restrições estruturais:**
  - Máximo 2 fábricas + 4 CDs por empresa.
  - Máximo 8 máquinas no total (distribuídas entre fábricas).
  - **Não pode haver 2 instalações da mesma empresa na mesma cidade** (exceto se a cidade for de fornecedor de MP).
  - Localizações **uma vez definidas, não mudam mais**.
  - Fábricas **não armazenam PA** — 100% transferido para CDs.

---

## 3. Produtos, matérias-primas e BoM

### Matérias-primas (3 tipos, 2 fornecedores cada)

| MP  | Fornecedor 1 (cidade, R$/ton) | Fornecedor 2 (cidade, R$/ton) | Densidade (ton/m³) |
| --- | --- | --- | --- |
| MP1 | Manaus — R$ 48.000 | Belém — R$ 56.000 | 0,5 |
| MP2 | Cuiabá — R$ 16.000 | Vitória da Conquista — R$ 22.000 | 0,7 |
| MP3 | Joinville — R$ 41.000 | Porto Alegre — R$ 32.000 | 0,9 |

### Produtos acabados (BoM, peso e velocidade de produção)

| Item | MP1 (g) | MP2 (g) | MP3 (g) | Peso total (g) | Produção (un/min) | Densidade (ton/m³) | Preço referência (R$) |
| --- | --- | --- | --- | --- | --- | --- | --- |
| PA1 |  60 |  90 | 150 | 300 | 15 | 1,0 | 80 |
| PA2 |  75 | 125 |  50 | 250 | 30 | 0,5 | 50 |
| PA3 |  75 |  30 |  45 | 150 | 60 | 0,8 | 25 |

> **PA1** é o mais pesado e mais caro por unidade, mas o mais lento de produzir.
> **PA3** é o mais leve, mais barato e o mais rápido de produzir.

---

## 4. As 25 cidades varejistas (mercado consumidor)

Belém, Belo Horizonte, Brasília, Campinas, Campo Grande, Cuiabá, Curitiba, Fortaleza,
Goiânia, João Pessoa, Joinville, Maceió, Manaus, Natal, Porto Alegre, Recife,
Ribeirão Preto, Rio de Janeiro, Salvador, Santos, São Luís, São Paulo, Uberlândia,
Vitória, Vitória da Conquista.

**Distâncias:** disponíveis para os 3 modais entre todos os pares — ver `03_matriz_distancia.md`.
- **Terrestre (Caminhão):** matriz completa 25×25.
- **Aérea (Avião):** matriz completa 25×25.
- **Marítima/Fluvial (Navio):** matriz **esparsa** — só cidades com porto têm rota; demais marcadas com `#ND` (≈ 14 cidades atendidas).

---

## 5. Tabela de custos regionais por nível de NE (Necessidade Econômica)

7 níveis, do mais caro (NE 1 = São Paulo) ao mais barato (NE 7 = Norte/interior).

| NE | Cidades | Terreno (R$/m²) | Água (R$/m³·h) | EE (R$/KWA·h) | Contratação MO | Salário MO | Manut. Máquina | Manut. CD (m²) |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 1 | São Paulo | 5.000 | 14 | 22 | 1.800 | 200 | 150 | 10,0 |
| 2 | Rio de Janeiro | 4.750 | 20 | 26 | 1.710 | 190 | 157,50 | 10,5 |
| 3 | Belo Horizonte, Brasília, Fortaleza, Salvador | 4.500 | 26 | 30 | 1.620 | 180 | 165 | 11,0 |
| 4 | Campinas, Curitiba, Porto Alegre, Recife | 4.250 | 32 | 34 | 1.530 | 170 | 172,50 | 11,5 |
| 5 | Goiânia, João Pessoa, Maceió, Natal, Ribeirão Preto | 4.000 | 38 | 38 | 1.440 | 160 | 180 | 12,0 |
| 6 | Cuiabá, Joinville, Santos, Uberlândia, Vitória | 3.750 | 44 | 42 | 1.350 | 150 | 187,50 | 12,5 |
| 7 | Belém, Campo Grande, Manaus, São Luís, Vitória da Conquista | 3.500 | 50 | 46 | 1.260 | 140 | 195 | 13,0 |

> **Trade-off central:** cidades baratas (NE 7) ficam longe do consumo (Sul/Sudeste), aumentando frete.

---

## 6. Modais de transporte

| Modal | Velocidade | Capacidade | Frete Viagem (R$/km) | Frete Peso (R$/km·ton) | Custo CT-e |
| --- | --- | --- | --- | --- | --- |
| Avião | 700 km/h | 1 ton | 12,00 | 18,00 | 200,00 |
| Caminhão | 50 km/h | 24 ton | 8,00 | 0,50 | 100,00 |
| Navio | 30 km/h | 100 ton | 5,00 | 0,075 | 50,00 |

**Regras de cálculo do frete:**
- **Ocupação ≥ 80%** → cobra **Frete Viagem** (R$ × km rodado).
- **Ocupação < 80%** → cobra **Frete Peso** = 50% do Frete Viagem + (R$ × km × peso).

**Capacidade máxima por carga (já convertida):**

| Item | Avião | Caminhão | Navio |
| --- | --- | --- | --- |
| PA1 (un) | 3.333 | 80.000 | 333.333 |
| PA2 (un) | 4.000 | 96.000 | 400.000 |
| PA3 (un) | 6.666 | 160.000 | 666.666 |
| MP1/2/3 (ton) | 1 | 24 | 100 |

**Restrições do transporte:**
- Máximo **220 transportes/semana** por empresa.
- Um transporte = 1 modal + 1 item + 1 quantidade (não dá pra mesclar cargas).
- Excesso de carga sobre o limite é **perdido** (a não ser que se contrate outro).
- Navio: só rotas listadas na matriz marítima (esparsa).

---

## 7. Regras da produção

- Máquina: **R$ 1.500.000** de aquisição, financiada a **3% a.m. por 48 períodos**.
- Terreno: financiado a **1,5% a.m. por 48 períodos**.
- 1 máquina ocupa **200 m²**; estruturas adicionais da fábrica = **1.000 m²**.
- 1 turno = **8 horas**; 1 operador por máquina por turno.
- Consumo por máquina: **1,5 m³/h** de água + **2,5 KWA/h**.
- Depósito de MP nas fábricas e CDs: **pé-direito 2 m**.

### Armazenagem
- Fábricas só estocam MP (PA vai 100% para CDs).
- Cálculo da área de estoque: usar densidade × volume × pé-direito 2 m.
- **Custo de manutenção do estoque:**
  - MP: `Qtd × maior preço de mercado × 1%`
  - PA: `Qtd × preço tabela × 1%`

---

## 8. Demanda histórica disponível (input para forecasting)

**Arquivo:** `Histórico_Demanda_126.xlsm` — 2 abas.

- **Ano 1:** 48 rodadas × 25 cidades × 3 PAs. Total Ano1 = aprox **83 milhões de unidades** (PA1).
- **Ano 2:** mesma estrutura. Total Ano2 = aprox **81 milhões de unidades** (PA1).

### Padrões observados (a inspecionar profundamente quando construir o forecast)
- Cidades dominantes em volume: **Salvador, São Paulo, Brasília, Curitiba, Fortaleza, Porto Alegre, Belo Horizonte** (todas com 3M+ no Ano 1 para PA1).
- Há **sazonalidade** clara: picos nas rodadas 21, 22, 29, 30, 44–48 — sugere crescimento de fim de ano + festas.
- Cidades menores: Vitória, Campo Grande, São Luís, Belém, Cuiabá (≤ 1,7M no Ano 1).

> Esta demanda **histórica** é o que os alunos enxergam para basear decisões. A demanda real do jogo pode ter variabilidade extra.

---

## 9. Mecânica de jogo — fluxo por rodada

Adaptado dos slides 7–8 da apresentação JML.

### Setup inicial (antes da rodada 1)

1. Professor apresenta o jogo, regras e premissas.
2. Disponibiliza: histórico de demanda, matriz de distância, custos, modais, dados de produção.
3. **1ª Decisão dos alunos** (irreversível): localização e tamanho das fábricas + CDs, quantidade de máquinas, MO.

### Rodada típica

1. Empresas informam **preços de venda** dos 3 PAs.
2. Plataforma compara preços — **menor preço ganha o 1º pedido de compra** daquele PA.
3. Cada empresa recebe seus pedidos (qtd + data de entrega).
4. Empresas tomam decisões semanais:
   - Quando comprar MP e de qual fornecedor?
   - Quando iniciar produção?
   - Como agendar transportes (até 220/semana)?
5. Plataforma roda a contabilidade da rodada e mostra:
   - Estoques atualizados (MP e PA por local).
   - Custos da rodada.
   - Pesquisa de preço dos concorrentes.
   - Relatórios gerenciais.
6. Próxima rodada — até a última.

### Decisões recorrentes a otimizar
- **Onde produzir x onde estocar x quando enviar** — equilibrar custo regional, frete e estoque.
- **Mix de produtos** — PA1 paga mais por unidade mas consome mais MP e tempo de máquina.
- **Mix de modais** — caminhão é o "default"; navio só onde há porto; avião só para emergência.

---

## 10. Fórmulas-chave (para implementar)

```text
Custo_terreno_periodo  = preco_m2 * m2 * juros_terreno (1.5%/mês por 48 períodos, sistema price)
Custo_maquina_periodo  = 1_500_000 * juros_maquina (3%/mês por 48 períodos)
Custo_MO_periodo       = (qtd_maquinas * turnos_dia * dias_uteis) * salario_MO + contratacao_inicial
Custo_agua_periodo     = horas_trabalhadas * 1.5 * preco_agua_regiao
Custo_EE_periodo       = horas_trabalhadas * 2.5 * preco_EE_regiao
Custo_manut_maquina    = qtd_maquinas * manut_unitaria
Custo_manut_CD         = area_CD * manut_m2

Frete (por viagem):
  if ocupacao >= 0.8:
    custo = R$_viagem_modal * km
  else:
    custo = 0.5 * R$_viagem_modal * km + R$_peso_modal * km * peso_ton
  custo_total = custo_frete + R$_documento

Custo_estoque_periodo:
  MP: qtd * maior_preco_mercado_MP * 0.01
  PA: qtd * preco_tabela_PA       * 0.01

Área de armazenagem:
  area_MP = (peso_estoque_MP / densidade_MP) / pe_direito_2m
  area_PA = (peso_estoque_PA / densidade_PA) / pe_direito_2m

Tempo de produção:
  PA1: 1 un / (15 un/min) = 4 s/un
  PA2: 1 un / (30 un/min) = 2 s/un
  PA3: 1 un / (60 un/min) = 1 s/un
```

---

## 11. Inventário de dados de entrada (o que o jogo digital consome)

| Dado | Fonte | Forma |
| --- | --- | --- |
| Lista de 25 cidades + classificação NE | `Infor_Geral_126.xlsx` | tabela estática |
| Tabela de custos regionais | `Infor_Geral_126.xlsx` | tabela por NE |
| Tabela de fornecedores de MP | `Infor_Geral_126.xlsx` | 6 linhas (MP × cidade × custo) |
| BoM dos PAs + velocidade produção | `Infor_Geral_126.xlsx` | matriz PA×MP + un/min |
| Densidades MP e PA | `Infor_Geral_126.xlsx` | 2 tabelas |
| Custo aquisição máquina + juros | `Infor_Geral_126.xlsx` | constantes |
| Modais (velocidade, carga, frete) | `Infor_Geral_126.xlsx` | tabela modal × custos |
| Preço referência dos PAs | `Infor_Geral_126.xlsx` | 3 valores |
| Demanda histórica 2 anos | `Histórico_Demanda_126.xlsm` | 6 grids 48×25 (2 anos × 3 PAs) |
| Distância Avião | `Matriz de Distancia.xlsx` | 25×25 completa |
| Distância Caminhão | `Matriz de Distancia.xlsx` | 25×25 completa |
| Distância Navio | `Matriz de Distancia.xlsx` | 25×25 esparsa (#ND para sem rota) |

---

## 12. Diretrizes para o produto digital (sugestão inicial)

### Estado mínimo viável a modelar

- **Empresa** (id, nome, capital, fábricas, CDs)
- **Fábrica** (id, cidade, m² terreno, qtd máquinas, estoques MP)
- **CD** (id, cidade, m² terreno, estoque PA)
- **Máquina** (id, fábrica, turnos, operadores)
- **EstoqueMP / EstoquePA** (local, item, quantidade, preço médio)
- **PedidoVenda** (rodada, varejista, PA, qtd, preço, data_entrega)
- **OrdemProducao** (rodada, fábrica, PA, qtd, MP consumidas)
- **Transporte** (rodada, origem, destino, modal, item, qtd, peso, custo)
- **RelatorioFinanceiro** (rodada, empresa, receitas, custos por categoria, lucro)

### Decisões por rodada (UI)

1. Tela de **setup inicial** (one-time): mapa Brasil clicável → escolher fábricas, CDs, dimensões, máquinas, MO.
2. Tela de **pricing**: definir preços dos 3 PAs por rodada.
3. Tela de **compras de MP**: escolher fornecedor + qtd + modal + destino.
4. Tela de **plano de produção**: alocar máquinas para PAs em cada fábrica.
5. Tela de **transferências fábrica → CD** e **CD → varejista** (até 220 transportes/sem).
6. Tela de **relatórios**: DRE, posições de estoque, mapa de fluxo, comparativo concorrentes.

### Risco principal de implementação

A **simulação determinística** das rodadas (otimização vs. ações dos times) precisa ser **explicável** — os alunos têm que entender por que ganharam ou perderam dinheiro. Investir em:
- Logs detalhados por transação.
- Visualização do fluxo (Sankey ou mapa animado).
- Replay de rodadas.

---

## 13. Pontos abertos para refinar com o usuário

Antes de começar a codar, vale alinhar com o Lucas:

1. **Plataforma alvo:** web SaaS multi-tenant (Next.js + Postgres) ou desktop/mobile?
2. **Modo de jogo:** turn-based assíncrono (como no original com professor) ou tempo-real?
3. **Quem é o usuário final:** estudantes da POLI/USP, cursos próprios, B2B treinamento?
4. **Mecânica do "menor preço ganha":** mantém a regra original ou abre para market share por preço?
5. **Variabilidade:** demanda do jogo digital usa o histórico literal ou adiciona estocasticidade?
6. **Multi-jogo simultâneo:** as 3 empresas competindo são sempre humanos ou pode ter IA?
7. **Licenciamento:** o Edgard Liberali Filho e Prof. Daniel autorizaram o uso digital do material?

---

## 14. Estrutura de pastas do projeto

```
Jodo de PCP/
├── docs/                            <- documentação gerada
│   ├── 00_CONTEXTO_GERAL.md         <- este arquivo (briefing mestre)
│   ├── 01_info_geral.md             <- dump da planilha de parâmetros
│   ├── 02_historico_demanda.md      <- dump da planilha de demanda 2 anos
│   ├── 03_matriz_distancia.md       <- dump das 3 matrizes de distância
│   └── 04_aula_jml.md               <- transcrição dos slides
├── raw_data/                        <- arquivos originais intocados
│   ├── Infor_Geral_126.xlsx
│   ├── Histórico_Demanda_126.xlsm
│   ├── Matriz de Distancia.xlsx
│   └── JML_Aula_126.pptx
└── scripts/
    └── extract_all.py               <- script Python que regenera os .md
```

> **Próximo passo sugerido:** definir o stack e abrir um repositório com pasta `apps/` (ou `packages/`) para começar a modelar o domínio em código a partir do que está aqui.
