# Design — Planner FLAMENGO (Jogo PCP 2)

**Data:** 2026-05-21
**Empresa:** FLAMENGO
**Escopo:** código rodada-a-rodada que (1) lê o estado do jogo e a OP recebida, (2) faz forecast Holt-Winters da próxima demanda, (3) preenche a planilha `FLAMENGO.xlsm` com `OP_FABRICAS` (plano de produção) e `SOL_TRANSP` (solicitação de transportes) otimizados, e (4) persiste histórico para inspeção.

> Versão 2 da spec — revisada a partir do parecer do code-reviewer. Mudanças principais: LP de modal reescrito (peso correto, capacidade por item, custo de viagem fiel ao jogo, acoplamento dia_produção↔dia_coleta); lead time multi-rodada explícito na reposição; simulador dia a dia para invariantes de capacidade; fallback HW quando 96 pontos não permitem sazonalidade estável; regras de `rod_cheg`/`dia_cheg` e "semana" explícitas.

---

## 1. Contexto e premissas do domínio

### 1.1 Infraestrutura fixa (já definida)
- **Fábrica F1 — Joinville (NE 6):** 7 máquinas, 3 turnos, 21 MO; áreas MP1=127m², MP2=36m², MP3=42m² (pé-direito 2m).
- **CD1 — São Luís (NE 7):** PA1=110m² / PA2=108m² / PA3=873m² → 733.333 / 432.000 / 9.312.000 frascos.
- **CD2 — Santos (NE 6):** PA1=100m² / PA2=100m² / PA3=800m² → 666.667 / 400.000 / 8.533.333 frascos.

> **Imutável durante o jogo.** O código *lê* essas instalações do `INSTALAÇÕES` do `FLAMENGO.xlsm` e usa como verdade; não as altera.

### 1.2 Mecânica
- 15 rodadas × 5 dias úteis cada.
- Rodada 1: sem OP recebida — apenas estimativa via forecast (já preenchida pelo usuário).
- A partir da Rodada 2: chega uma OP detalhada (cidade-varejista × PA × qtd × dia_entrega). **Entrega fora do dia → descarta.**
- MP que chega na fábrica sem espaço → **descarta**.
- PA não pode dormir na fábrica → tudo produzido no Dia X precisa ter transporte saindo no Dia X (senão **descarta**).
- **PA sempre passa pelo CD**: o briefing diz "Fábricas não armazenam PA — 100% transferido para CDs". Logo, **Fábrica→Varejo direto não é permitido** e não é modelado. Se uma OP urgente não tiver CD viável, ela é descartada (registrada em `ops_descartadas`).
- Cada transporte = 1 modal + 1 item + 1 qtd. Limite **220 transportes/semana**.
  - **"Semana" = rodada de partida.** O contador zera no fim de cada rodada. Um transporte que parte na rodada N e chega na rodada N+1 conta só na N.
- Modais: Avião 1 ton, Caminhão 24 ton, Navio 100 ton (esparso — só rotas listadas).
- Transporte pode começar em uma rodada e terminar em outra (lead time multi-semana é normal).

### 1.3 Capacidades de produção (F1)
- Disponibilidade: 7 máq × 3 turnos × 8 h × 60 min = **10.080 min-máquina/dia**.
- Velocidades: PA1=15 un/min, PA2=30 un/min, PA3=60 un/min.
- Restrição: Σ_PA (qtd[PA] / vel[PA]) ≤ 10.080 por dia.

### 1.4 BoM, peso e densidades
- Origem única: `data/parametros.json` (carregada pelo `src/config.py`).
- BoM (g/un): PA1=(60,90,150); PA2=(75,125,50); PA3=(75,30,45).
- **Peso unitário em toneladas** (derivado, novo no Config): PA1=3e-4, PA2=2.5e-4, PA3=1.5e-4 ton/frasco. Usado pelo LP para calcular peso transportado.
- Densidade MP (ton/m³): MP1=0.5, MP2=0.7, MP3=0.9.
- Densidade PA (ton/m³): PA1=1.0, PA2=0.5, PA3=0.8.

### 1.5 Fontes de dados (somente leitura)
| Arquivo | Conteúdo | Uso |
| --- | --- | --- |
| `data/parametros.json` | Custos NE, BoM, modais, densidades, preços, limites | Constantes do jogo |
| `data/demanda_long.parquet` | Demanda histórica long (ano, rodada, cidade, PA, qtd) — 2 anos | Treino HW |
| `data/distancias_caminhao.parquet` | Matriz 25×25 | LP de modal |
| `data/distancias_aviao.parquet` | Matriz 25×25 | LP de modal |
| `data/distancias_navio.parquet` | Matriz esparsa (rotas marítimas) | LP de modal |
| `data/freight_costs.parquet` | Preços por modal/rota | LP de modal |
| `data/demand_formula.json` | Curva sazonal × peso cidade | **Não usado** em runtime (apenas referência) |
| `rodadas/FLAMENGO.xlsm` | Planilha de entrega + instalações | Leitura (config) e escrita (SOL_TRANSP/OP_FABRICAS) |
| `rodadas/Rodada N.xlsm` | Snapshot da rodada (estoques no Dia 5 + OP recebida) | Leitura por rodada |

---

## 2. Arquitetura de pastas

```
Jogo PCP 2 (a vinganca)/
├── contexto/                            # já existe — docs do briefing
├── data/                                # já existe — fontes estáticas
├── rodadas/                             # já existe — Rodada N.xlsm + FLAMENGO.xlsm
├── docs/
│   └── superpowers/specs/               # este documento
├── estado/                              # NOVO — gerado em runtime
│   ├── state.json                       # estado vigente
│   ├── hw_models.json                   # parâmetros HW persistidos (JSON)
│   ├── historico_demanda_ampliado.parquet  # histórico + OPs reais agregadas
│   └── historico_rodada_<N>.json        # snapshot por rodada (para dashboard)
├── src/                                 # NOVO — módulos puros
│   ├── __init__.py
│   ├── config.py                        # carrega parametros.json + constantes
│   ├── domain.py                        # dataclasses (Estado, TransitItem, OP, etc.)
│   ├── io_xlsm.py                       # leitura/escrita das planilhas
│   ├── estado.py                        # load/save state.json + snapshots
│   ├── forecast.py                      # Holt-Winters por (cidade, PA)
│   ├── planner.py                       # heurística de planejamento
│   ├── lp_modal.py                      # LP final de alocação modal
│   ├── pipeline.py                      # orquestração: rodada N → planilha
│   └── dashboard.py                     # leitura de históricos + plots
├── jogo/                                # NOVO — interface do usuário
│   └── rodada.ipynb                     # notebook principal
├── tests/                               # NOVO — smoke tests + fixtures
│   ├── fixtures/                        # JSON/parquet sintéticos pequenos
│   ├── test_config.py
│   ├── test_io_xlsm.py
│   ├── test_estado.py
│   ├── test_forecast.py
│   ├── test_planner.py
│   ├── test_lp_modal.py
│   └── test_pipeline.py
└── requirements.txt                     # NOVO
```

**Stack:** Python 3.11+, pandas, numpy, statsmodels (HW), pulp (LP via CBC default), openpyxl, matplotlib, pyarrow (parquet), pytest.

---

## 3. Modelos de dados (`src/domain.py`)

```python
from dataclasses import dataclass, field
from typing import Dict, List, Literal, Optional

Item = Literal["MP1", "MP2", "MP3", "PA1", "PA2", "PA3"]
Modal = Literal["Avião", "Caminhão", "Navio"]
TipoOrigem = Literal["Fornecedor", "Fábrica", "CD"]
TipoDestino = Literal["Fábrica", "CD", "Varejista"]

@dataclass
class TransitItem:
    rod_part: int           # rodada de partida
    dia_part: int           # 1-5
    rod_cheg: int           # rodada de chegada (ver §6 regra)
    dia_cheg: int           # 1-5 dentro da rod_cheg
    origem_tipo: TipoOrigem
    origem_cidade: str
    destino_tipo: TipoDestino
    destino_cidade: str
    modal: Modal
    item: Item
    qtd: float              # toneladas se MP, frascos se PA

@dataclass
class OP:
    rodada: int             # rodada em que a OP foi recebida
    cidade: str             # varejista
    pa: Item                # PA1/PA2/PA3
    qtd: int                # frascos
    dia_entrega: int        # 1-5 da rodada `rodada` (entrega no mesmo período)

@dataclass
class OPDescartada:
    op: OP
    motivo: str             # "sem_estoque_CD" | "lead_time_inviavel" | "cap_modal_excedida" | "cap_cd_excedida"
    rodada_descarte: int

@dataclass
class Estado:
    rodada_atual: int                                    # última rodada processada
    estoque_mp_fabrica: Dict[str, Dict[str, float]]      # {"F1": {"MP1": ton, ...}}
    estoque_pa_cd: Dict[str, Dict[str, int]]             # {"CD1": {"PA1": frascos, ...}}
    transit: List[TransitItem]                           # pendentes
    ops_pendentes: List[OP]                              # OPs com `rodada` futura, ainda não vencidas
    ops_atendidas: List[OP]                              # histórico (% serviço)
    ops_descartadas: List[OPDescartada]                  # não atendidas → descarte

@dataclass
class PlanoTransporte:
    """O que o planner decide. Vira linha no SOL_TRANSP."""
    rodada: int
    origem_tipo: TipoOrigem
    origem_cidade: str
    dia_coleta: int
    modal: Modal
    item: Item
    qtd: float
    destino_tipo: TipoDestino
    destino_cidade: str

@dataclass
class PlanoProducao:
    """Vira célula no OP_FABRICAS."""
    rodada: int
    fabrica: str            # "F1"
    dia: int                # 1-5
    pa: Item
    qtd: int                # frascos
```

> **Política de `ops_pendentes`:** uma OP com `dia_entrega` na rodada corrente que não foi atendida ao fim da rodada vai para `ops_descartadas` (não persiste). Só fica em `ops_pendentes` OP com `rodada` futura — caso o jogo permita pedido antecipado. A spec assume que o prof entrega OPs apenas para a rodada corrente; se aparecerem OPs futuras, o pipeline trata.

---

## 4. Pipeline de uma rodada (`src/pipeline.py::run_rodada`)

Função única, chamada do notebook:

```python
def run_rodada(rodada_n: int, rodada_xlsm_path: Path) -> dict:
    """
    Lê estado anterior + rodada N (planilha do prof), processa, escreve FLAMENGO.xlsm.
    Retorna dict com resumo (custos estimados, % atendimento, transportes usados).
    """
```

**Passos internos:**

1. **Carrega config:** `Config.load()` (constantes + matrizes de distância + custos de frete).
2. **Carrega estado:** `Estado.load("estado/state.json")` ou inicializa zerado se for Rodada 1.
3. **Lê rodada do prof:**
   - `INSTALAÇÕES` (sanity check — não mudou).
   - `SOL_TRANSP` da Rodada N anterior preenchida → reconstitui `TransitItem`s reais.
   - OP da rodada N (de `rodadas/OP_Rodada_<N>.xlsx` — ver §10).
4. **Simulação dia a dia (Dia 1..5) — fechamento da rodada N-1 e abertura da rodada N:**
   - Estado de entrada: snapshot do fim do Dia 5 da rodada anterior (já salvo em `state.json`).
   - Para cada dia d ∈ {1..5} **da rodada N**:
     - Aplica chegadas de `transit` com `(rod_cheg, dia_cheg) == (N, d)` — esses são transportes agendados em rodadas anteriores que pousam neste dia.
     - **Verifica invariantes**: capacidade MP por área F1, capacidade PA por área CD (partição por PA é fixa em m² — `cap_PA_i_CD` é dura).
     - Excesso de chegada → descarte (MP) ou descarte do transporte (PA), com motivo registrado em log.
   - Esta etapa **só aplica o que já estava agendado** (transit pré-existente). As saídas/produção/compras da rodada N ainda não foram decididas (vêm dos passos 7-8). O estado final desta etapa é o "estoque de abertura" disponível para o planner usar.
5. **Mescla OP nova:** OPs recebidas viram `ops_pendentes` ou são candidatas a entrega imediata.
6. **Forecast:**
   - Agrega OPs reais da rodada N em `(cidade, PA) → qtd_total` (soma de OPs por dia).
   - Refit dos 75 modelos HW (ver §7) e gera projeção para N+1..N+4.
7. **Heurística de planejamento (4 passos, `planner.planejar`):** ver §8.
8. **LP de alocação modal (`lp_modal.otimizar`):** ver §9.
9. **Atualiza estado:**
   - Move OPs entregues no prazo para `ops_atendidas`; o que não foi possível para `ops_descartadas`.
   - Atualiza `transit` com novos transportes que saem.
   - Atualiza estoques projetados ao fim da rodada (snapshot Dia 5).
10. **Escreve FLAMENGO.xlsm:** `io_xlsm.escrever_plano(planos, op_fabricas)` preenche `SOL_TRANSP` e `OP_FABRICAS` (preservando o VBA — `keep_vba=True`).
11. **Salva snapshots:** `estado/state.json` + `estado/historico_rodada_<N>.json` com `{custos, % serviço, contagem transportes, ocupação CDs}`.
12. **Retorna dict resumo** para o notebook exibir.

---

## 5. Módulo `src/config.py`

Responsável por **uma fonte única de verdade** para constantes do jogo. Carrega tudo no `import` e expõe via `Config` dataclass imutável.

```python
class Config:
    BoM: Dict[str, Dict[str, int]]         # gramas por unidade
    velocidades: Dict[str, int]            # un/min por PA
    peso_un_ton: Dict[str, float]          # ton/frasco (PA1=3e-4, PA2=2.5e-4, PA3=1.5e-4)
    densidades_mp: Dict[str, float]
    densidades_pa: Dict[str, float]
    cap_modal_ton: Dict[str, float]                       # {"Avião":1, "Caminhão":24, "Navio":100}
    cap_modal_por_item: Dict[str, Dict[str, float]]       # cap em "unidades do item"
                                                          #   PA: frascos por viagem
                                                          #   MP: toneladas por viagem (= cap_modal_ton)
    frete_viagem: Dict[str, float]         # R$/km
    frete_peso: Dict[str, float]           # R$/km·ton
    doc_modal: Dict[str, float]            # R$/CT-e
    fornecedores: Dict[str, List[Tuple[str, float]]]  # MP → [(cidade, custo_ton)]
    ne_por_cidade: Dict[str, int]
    distancias: Dict[str, pd.DataFrame]    # {"Caminhão": 25×25, "Avião": 25×25, "Navio": esparsa}
    rotas_navio_validas: Set[Tuple[str, str]]
    capacidades: dict                      # max_transportes_semana, area_por_maquina, etc.

    @classmethod
    def load(cls, base_dir: Path) -> "Config": ...
```

**Constantes derivadas (calculadas no `load`):**
- `cap_modal_por_item["Avião"]["PA1"] = math.floor(1.0 / 3e-4) = 3333` (etc.).
- `cap_modal_por_item["Caminhão"]["MP1"] = 24` (em ton).
- `cap_min_por_dia_F1` = 10.080 min-máq.
- Para cada CD: capacidade em frascos por PA (do `INSTALAÇÕES`).
- Tabela `lead_time_dias_uteis[modal][origem][destino]` derivada das matrizes de distância e velocidade do modal, arredondada para cima (cada 8h de viagem = 1 dia útil).

---

## 6. Módulo `src/io_xlsm.py`

### 6.1 Leitura
- `ler_instalacoes(path) -> dict` — extrai F1, F2, CD1..CD4 das células fixas (linhas 8-15 da sheet `INSTALAÇÕES`).
- `ler_sol_transp(path) -> List[TransitItem]` — varre da linha 5 até primeira linha vazia.
- `ler_op_rodada(path) -> List[OP]` — formato em §10.

### 6.2 Regra de `rod_cheg` / `dia_cheg`
Dado `(rod_part, dia_part, lead_dias)`:

```python
total_dias = dia_part + lead_dias
rod_cheg = rod_part + (total_dias - 1) // 5
dia_cheg = ((total_dias - 1) % 5) + 1
```

Exemplo: `rod_part=1, dia_part=4, lead_dias=3` → `total=7 → rod_cheg=1+(6//5)=2, dia_cheg=(6%5)+1=2`. Confere com a planilha real do usuário (PA Joinville→São Luís de caminhão saindo Dia 4 chega no Dia 7 = Rodada 2 Dia 2).

### 6.3 Escrita
- `escrever_plano(path, planos_transporte, planos_producao, rodada_n)`:
  - Abre com `keep_vba=True`, `data_only=False`.
  - **`SOL_TRANSP`**: limpa colunas A-I das linhas 5+ correspondentes à `rodada_n` (mantém fórmulas das colunas J-Z). Escreve uma linha por `PlanoTransporte`.
  - **`OP_FABRICAS`**: bloco F1 (linhas 7-11, colunas B-D = PA1/PA2/PA3) para Dia 1..5. Atualiza célula F4 (= "Rodada_N") e a referência `=SOL_TRANSP!L2` permanece.
- **Cuidado VBA:** `keep_vba=True` preserva `vbaProject.bin`. Limitações conhecidas:
  - Tabelas estruturadas (`ListObjects`) podem invalidar se escrever fora do range. **Não temos tabelas estruturadas** nas sheets-alvo.
  - Formatação condicional pode ser perdida em algumas células. Aceitável — não afeta cálculo.
  - **Sanidade:** após primeira release de mudança de escrita, abrir manualmente no Excel real e confirmar que VBA e fórmulas rodam.

---

## 7. Módulo `src/forecast.py`

### 7.1 Treino inicial (chamado uma vez se `hw_models.json` não existe)
```python
def treinar_inicial(historico: pd.DataFrame) -> Dict[Tuple[str, str], dict]:
    """
    historico: long com (periodo_global=1..96, cidade, PA, qtd).
    Retorna parâmetros HW ajustados para 75 séries (25 cidades × 3 PAs).
    Tenta seasonal_periods=48 (modelo aditivo + damped_trend=True).
    Fallback automático para Holt simples (seasonal=None) se o fit falhar ou
    o RMSE in-sample piorar > 20% vs Holt sem sazonal.
    """
```

### 7.2 Agregação de OP real para refit
A OP do prof tem granularidade `(cidade, PA, qtd, dia_entrega)`. Para virar **um ponto** da série temporal por (cidade, PA, rodada):

```python
def agregar_op_para_serie(ops: List[OP], rodada_n: int) -> Dict[Tuple[str, str], float]:
    """
    Soma qtd por (cidade, PA) ignorando dia_entrega — vira um único valor por
    rodada que entra como ponto novo na série em periodo_global = 96 + N.
    Cidades sem OP na rodada N recebem 0 (ou são puladas — ver §7.3).
    """
```

### 7.3 Refit por rodada
```python
def refit(historico_path: Path, modelos_atuais: dict, ops_da_rodada: dict, rodada_n: int) -> dict:
    """
    1. Carrega historico_demanda_ampliado.parquet
    2. Para cada (cidade, PA) presente em ops_da_rodada: anexa o ponto e refita.
    3. Cidades sem OP nesta rodada: NÃO recebem ponto (não há dado).
       O modelo continua valendo, mas o periodo_global da série fica defasado.
       (Trade-off aceito: simplicidade > completude.)
    4. Salva historico ampliado e hw_models.json.
    """
```

**Refit é fit completo** (sem `start_params`). Custo ~10-20s por rodada para 75 séries; aceitável para uso humano.

### 7.4 Previsão
```python
def prever(modelos: dict, horizonte: int = 4) -> Dict[Tuple[str, str], List[float]]:
    """
    Retorna previsão das próximas 'horizonte' rodadas para cada (cidade, PA).
    Floor em 0 (não-negativo).
    """
```

### 7.5 Persistência **(JSON, não pickle)**
- **`estado/historico_demanda_ampliado.parquet`** — histórico (96 períodos) + 1 linha por (cidade, PA, rodada N) a cada rodada com OP real.
- **`estado/hw_models.json`** — para cada (cidade, PA): `{"tipo": "HW_aditivo" | "Holt_simples", "params": {...}, "rmse_in_sample": float, "ultimo_periodo_treino": int}`. Inspecionável e portável.

**Por que statsmodels e não Prophet:** statsmodels é puro Python, sem deps C, e o HW é o que o briefing pede.

---

## 8. Módulo `src/planner.py`

Heurística de **4 passos gulosos** com **simulação dia a dia** embutida.

### 8.1 Função pública
```python
def planejar(
    estado: Estado,
    ops_da_rodada: List[OP],
    forecast: Dict[Tuple[str, str], List[float]],
    config: Config,
    rodada_n: int,
) -> Tuple[List[TarefaTransporte], List[PlanoProducao]]:
    """
    Retorna TAREFAS (não PlanoTransporte ainda), para o LP final atribuir modal/dia.
    EXCETO Fábrica→CD: essas tarefas já vêm com janela_dias=[dia_producao]
    (PA não dorme na fábrica).
    """
```

### 8.2 Passo 1 — Entregas CD → Varejo
Para cada OP em `ops_da_rodada + estado.ops_pendentes` cujo `dia_entrega` ∈ rodada N:
1. Para cada CD candidato, calcula `lead_min = min_m lead_time_dias[m][CD][cidade]`.
2. Filtra: `lead_min ≤ dia_entrega - 1` (precisa caber).
3. Filtra por estoque disponível em `estado.estoque_pa_cd[CD][PA]` (descontando outras OPs já alocadas).
4. Critério de escolha (lexicográfico): menor `lead_min`, depois maior estoque disponível, depois menor custo esperado (`frete_viagem_caminhão × dist`).
5. Se nenhum CD viável → `ops_descartadas.append(OPDescartada(op, "sem_estoque_CD"))`.
6. Gera `TarefaTransporte(origem=CD, destino=cidade, item=PA, qtd, janela_dias=[1..dia_entrega - lead_min], rodada=N)`.

### 8.3 Passo 2 — Reposição Fábrica → CD (com lead time multi-rodada)
Para cada (CD, PA):

```python
lt_dias = lead_time_dias["Caminhão"]["Joinville"][cidade_CD]   # ou Navio se mais barato
lt_rodadas = math.ceil(lt_dias / 5)
# Reposição feita na rodada N atende demanda a partir de N + lt_rodadas (entrega no início)
janela_demanda = (N + lt_rodadas, N + lt_rodadas + 1)   # cobertura 2 rodadas

demanda_proxima_janela = sum(
    forecast[(cidade, PA)][lt_rodadas + offset]
    for cidade in cidades_atendidas_pelo_CD
    for offset in [0, 1]
)
saida_local = soma_ops_alocadas_neste_CD_neste_PA   # do Passo 1
estoque_pos_N = estado.estoque_pa_cd[CD][PA] - saida_local + chegadas_em_transit_ate_N+lt_rodadas

necessidade = max(0, demanda_proxima_janela - estoque_pos_N)
```

Se `necessidade > 0`, decide produção (Passo 3) e gera `TarefaTransporte(Joinville→CD, PA, qtd=necessidade, janela_dias=<dia_producao>)`.

### 8.4 Passo 3 — Produção em F1 (com vínculo dia_produção↔dia_coleta)
1. `total_a_produzir[PA] = Σ necessidades Passo 2 por PA`.
2. Aloca por dia respeitando 10.080 min-máq/dia com **heurística LPT** (PA com mais minutos primeiro).
3. **Vínculo dia_produção↔transporte:** para cada (dia, PA, qtd) produzido, cria *ao mesmo tempo*:
   - `PlanoProducao(dia, PA, qtd)`
   - `TarefaTransporte(Joinville→CD, item=PA, qtd, janela_dias=[dia])` ← janela de um dia só.
   - A divisão por CDs respeita a `necessidade` calculada no Passo 2.

Se a soma das necessidades exceder a capacidade total de 5 dias (5 × 10.080 = 50.400 min-máq), o planner recorta proporcionalmente e marca as OPs prejudicadas como risco.

### 8.5 Passo 4 — Compra de MP (simulador dia a dia)
1. `mp_necessaria_por_dia[d][MP] = Σ_PA producao[d][PA] × bom[PA][MP] / 1_000_000` (ton).
2. **Estratégia heurística just-in-time, fornecedor único por MP por rodada:**
   - Para cada MP, escolhe o fornecedor mais barato (de `config.fornecedores[MP]`).
   - Calcula `lead_min_dias = lead_time["Caminhão"][fornecedor.cidade]["Joinville"]` (caminhão é o default para MP — navio só se rota existir e fornecedor for em cidade portuária).
3. **Agendamento dia a dia:** para cada dia d ∈ {1..5}:
   - `consumo[d, MP] = mp_necessaria_por_dia[d][MP]`.
   - `estoque_inicio[d, MP] = estoque_inicio[d-1, MP] + chegadas_agendadas[d, MP] - consumo[d-1, MP]`.
   - Se `estoque_inicio[d, MP] < consumo[d, MP]`: agenda compra para chegar no Dia `d` (parte no Dia `d - lead_min_dias`; se `d - lead_min_dias < 1`, parte na rodada anterior — caso já passou, **MP é descartada da OP por inviabilidade**).
   - `qtd_a_comprar = consumo[d, MP] - estoque_inicio[d, MP]`, agregada para preencher caminhão (cap 24 ton) reduzindo nº CT-e.
4. **Restrição de capacidade:** `estoque_inicio[d, MP] + chegada[d, MP] ≤ cap_mp[MP]` para todo d. Se estourar, **adia a chegada** (compra a menos hoje, mais amanhã). Se nem isso couber (consumo > capacidade total), marca PA correspondente como "produção inviável" e descarta OP relacionada com motivo `"cap_mp_excedida"`.
5. Gera `TarefaTransporte(Fornecedor→F1, MP, qtd, janela_dias=[dia_partida])` para cada compra.

**Política proativa:** se não couber tudo, prioriza MP mais cara (MP1 > MP3 > MP2 por custo unitário) e marca o restante como `ops_descartadas` indireto (registra log: "Não foi possível repor MP, OP X pode ser descartada na rodada N+lt").

---

## 9. Módulo `src/lp_modal.py`

### 9.1 Entrada
Lista de tarefas brutas geradas pelo planner:
```python
@dataclass
class TarefaTransporte:
    origem_cidade: str
    destino_cidade: str
    item: Item              # MP ou PA
    qtd: float              # ton se MP, frascos se PA
    janela_dias: List[int]  # dias de coleta permitidos (1..5)
    rodada: int
    motivo: str             # "OP_<id>" / "reposição_CD1_PA2" / "MP_compra_MP1" / etc.
```

### 9.2 Modelagem (PuLP — MILP, não LP puro)

> **Regra de frete do jogo (briefing §6, reproduzida):**
> - Ocupação **≥ 80%** da viagem → custo da viagem = `frete_viagem[m] × km`. **Não soma frete_peso.**
> - Ocupação **< 80%** → custo da viagem = `0.5 × frete_viagem[m] × km + frete_peso[m] × km × peso_ton`.
> - Custo CT-e (`doc[m]`) é cobrado uma vez por viagem.

Para cada tarefa `t`, modal `m` (compatível com `item[t]`), dia `d ∈ janela_dias[t]`:

**Variáveis:**
- `x[t,m,d]` ∈ ℝ≥0: quantidade transportada (mesma unidade do `item`: ton para MP, frascos para PA).
- `n[t,m,d]` ∈ ℤ≥0: número total de viagens nesse (t,m,d).
- `o80[t,m,d]` ∈ {0,1}: binária — 1 se a **última** viagem tem ocupação ≥ 80%.
- `x_last[t,m,d]` ∈ ℝ≥0: quantidade na última viagem (`= x - (n-1)·cap`).
- `x_last_lo[t,m,d]` ∈ ℝ≥0: parcela de `x_last` quando `o80=0` (auxiliar para linearização).

**Quantidades derivadas (parâmetros, não variáveis):**
- `cap[m,i] = config.cap_modal_por_item[m][i]` (frascos para PA, ton para MP).
- `peso_un[i]` em toneladas (PA: peso_un_ton; MP: 1 ton/ton).
- `dist[t]` = distância (km) origem→destino no modal `m`.
- `M_x` = upper bound de `x_last` = `cap[m,i]`.

**Restrições:**
1. **Conservação:** `Σ_{m,d} x[t,m,d] = qtd[t]` para toda tarefa `t`.
2. **Capacidade por viagem — linearização de `n = ⌈x/cap⌉`:**
   - `x[t,m,d] ≤ n[t,m,d] × cap[m, item[t]]`
   - `x[t,m,d] ≥ (n[t,m,d] - 1) × cap[m, item[t]] + ε`  ← `ε = 1` para PA (frasco), `0.01` para MP.
3. **Definição de `x_last`:** `x_last[t,m,d] = x[t,m,d] - (n[t,m,d] - 1) × cap[m, item[t]]`. Por (1) e (2), `ε ≤ x_last ≤ cap`.
4. **Janela de dia:** `x[t,m,d] = 0` se `d ∉ janela_dias[t]`.
5. **Rota navio:** `x[t,"Navio",d] = 0` se `(origem,destino) ∉ rotas_navio_validas`.
6. **Limite semanal:** `Σ_{t,m,d} n[t,m,d] ≤ 220` (partidas na rodada N).
7. **Acoplamento `o80` com `x_last`:**
   - `x_last[t,m,d] ≥ 0.8 × cap[m,i] × o80[t,m,d]`  → se `o80=1`, força ocupação ≥80%.
   - `x_last[t,m,d] ≤ 0.8 × cap[m,i] - ε + (cap[m,i] - 0.8 × cap[m,i] + ε) × o80[t,m,d]`  → se `o80=0`, força ocupação <80% (implicador inverso para robustez).
8. **Auxiliar `x_last_lo = x_last × (1 - o80)` via big-M:**
   - `x_last_lo ≤ x_last`
   - `x_last_lo ≤ M_x × (1 - o80)`
   - `x_last_lo ≥ x_last - M_x × o80`
   - `x_last_lo ≥ 0`

**Função-objetivo (LINEAR após substituição):**

Para cada (t,m,d), custo = `(n-1) × custo_viagem_cheia(m,t) + custo_ultima_viagem(t,m,d) + doc[m] × n`.

Como toda viagem das `(n-1)` primeiras está cheia (cap inteira, ocupação 100% ≥ 80%), `custo_viagem_cheia(m,t) = frete_viagem[m] × dist[t]`.

Custo da última viagem:
- se `o80=1`: `frete_viagem[m] × dist[t]`
- se `o80=0`: `0.5 × frete_viagem[m] × dist[t] + frete_peso[m] × dist[t] × peso_un[item[t]] × x_last`

Combinando os dois casos via `o80` e `x_last_lo`:

```
custo_ultima = o80 × (frete_viagem × dist)
             + (1 - o80) × (0.5 × frete_viagem × dist)
             + frete_peso × dist × peso_un × x_last_lo
```

Tudo linear: `o80` é binária, `x_last_lo` é a auxiliar já linearizada.

**Objetivo final:**
```
minimize  Σ_{t,m,d} [
    frete_viagem[m] × dist[t] × (n[t,m,d] - 1)                     # n-1 viagens cheias
  + frete_viagem[m] × dist[t] × o80[t,m,d]                         # ≥80% na última
  + 0.5 × frete_viagem[m] × dist[t] × (1 - o80[t,m,d])             # <80% na última (parcela fixa)
  + frete_peso[m]   × dist[t] × peso_un[item[t]] × x_last_lo[t,m,d] # <80% na última (parcela peso)
  + doc[m] × n[t,m,d]                                              # CT-e por viagem
]
```

Tudo linear em `n`, `o80`, `x_last_lo`. O modelo é MILP. Para 15 rodadas × ~50 tarefas/rodada × 3 modais × 5 dias ≈ 750 variáveis contínuas + 750 inteiras + 750 binárias — CBC resolve em < 30s.

### 9.3 Solver
- PuLP com CBC default. `tmpDir` apontado para `./.tmp/pulp` (path simples, sem espaços) para evitar problemas com a pasta atual `Jogo PCP 2 (a vinganca)` ter acentos e parênteses no Windows.
- `solver = pulp.PULP_CBC_CMD(timeLimit=30, msg=False, tmpDir="./.tmp/pulp")`.
- Fallback: se `LpStatus != "Optimal"`, registra warning e devolve heurística pura (greedy por modal mais barato compatível).
- Alternativa via env var `JOGO_SOLVER=HIGHS` → `pulp.HiGHS_CMD()` (requer `highspy`).

### 9.4 Saída
Converte `x[t,m,d]`/`n[t,m,d]` ótimos em lista de `PlanoTransporte` (uma linha por viagem física, já quebrada pelo cap modal). Pseudo-código:

```python
for (t, m, d), n_value in n_otimos.items():
    n_int = int(round(n_value))
    if n_int == 0:
        continue
    x_total = x_otimos[(t, m, d)]
    cap = config.cap_modal_por_item[m][t.item]
    # n_int-1 viagens cheias + 1 última com x_last
    for _ in range(n_int - 1):
        planos.append(PlanoTransporte(rodada, t.origem_tipo, t.origem_cidade,
                                       dia_coleta=d, modal=m, item=t.item,
                                       qtd=cap, destino_tipo=t.destino_tipo,
                                       destino_cidade=t.destino_cidade))
    x_last = x_total - (n_int - 1) * cap
    if x_last > 0:
        planos.append(PlanoTransporte(rodada, t.origem_tipo, t.origem_cidade,
                                       dia_coleta=d, modal=m, item=t.item,
                                       qtd=x_last, destino_tipo=t.destino_tipo,
                                       destino_cidade=t.destino_cidade))
```

---

## 10. Formato de entrada da OP por rodada

A planilha `Rodada N.xlsm` enviada pelo professor traz `SOL_TRANSP` preenchida do estado anterior, mas **não traz** OP nativa.

**Decisão:** **arquivo separado `rodadas/OP_Rodada_<N>.xlsx`** (recomendado): colunas `[Rodada, Cidade, PA, Qtd, Dia_Entrega]`. O usuário converte o que o prof entrega (PDF/Excel) para esse formato.

`io_xlsm.ler_op_rodada(rodada_n)` procura o arquivo; se não existir, retorna lista vazia (caso da Rodada 1).

---

## 11. Dashboard histórico (`src/dashboard.py` + célula final do notebook)

Lê todos os `estado/historico_rodada_*.json` e produz:

1. **Tabela resumo** (uma linha por rodada): MP estocada (ton, % cap), PA estocado por CD (frascos, % cap), transit pendente (qtd transportes + ton), OPs recebidas / atendidas / descartadas, % serviço, custo total estimado da rodada.
2. **Gráficos matplotlib**:
   - Estoque MP em F1 ao longo das rodadas.
   - Estoque PA em CD1 e CD2 (linhas separadas por PA).
   - Transit pendente ao fim de cada rodada.
   - Custo total acumulado.
   - % serviço por rodada.
   - **Forecast vs. real por PA** (3 subplots, um por PA — não agregar).
3. **Tabela de OPs descartadas** com motivo.

---

## 12. Restrições e regras de descarte que o código respeita

| Regra | Onde é tratada |
| --- | --- |
| MP chega na fábrica sem espaço → descarta | `pipeline._simular_dia_a_dia` + planner Passo 4 (proativo) |
| PA chega no varejo fora da data → descarta | `planner` Passo 1 (proativo) + `pipeline._fechar_rodada` |
| PA não sai da fábrica no dia produzido → descarta | `planner` Passo 3 vincula janela=[dia_produção] |
| Capacidade modal (1/24/100 ton ou frascos equivalentes) | `lp_modal` restrição 2 |
| ≤ 220 transportes/semana (partida) | `lp_modal` restrição 5 |
| Navio só em rotas válidas | `lp_modal` restrição 4 |
| Lead time entrega ≤ dia_entrega | `planner` Passo 1 filtro + `lp_modal` janela_dias |
| Cap MP em F1 (por densidade × área × pé-direito) | `planner` Passo 4 simulador dia a dia |
| Cap PA por CD (frascos do PDF) | `planner` Passo 2 limita reposição + `pipeline._simular_dia_a_dia` |
| Custo de frete fiel à regra ≥80% vs <80% | `lp_modal` modelagem com binária `o80` |
| Fábrica→Varejo direto não modelado | Por design — PA sempre passa por CD (§1.2) |

---

## 13. Notebook `jogo/rodada.ipynb`

**Células:**

1. **Setup:** imports, `BASE = Path("..")`, `from src.pipeline import run_rodada`, `from src.dashboard import plot_historico`.
2. **Configuração da rodada:** define `RODADA = 2` e `RODADA_PATH = BASE / "rodadas" / "Rodada 2.xlsm"`. Variável para o usuário trocar a cada rodada.
3. **Executa pipeline:** `resumo = run_rodada(RODADA, RODADA_PATH)`.
4. **Mostra resumo:** `print(json.dumps(resumo, indent=2, ensure_ascii=False))`.
5. **Dashboard:** `plot_historico("../estado/")` — gera os 6+3 gráficos + tabelas.
6. **(Opcional) Inspeção manual:** célula com `pd.read_excel(BASE / "rodadas/FLAMENGO.xlsm", sheet_name="SOL_TRANSP", skiprows=3)` para conferir o que foi escrito.

---

## 14. Testes mínimos (`tests/`)

Todos usam **fixtures sintéticas pequenas** em `tests/fixtures/` (não puxam parquets reais).

- `test_config.py`: carrega `parametros.json` real (é pequeno) e valida tipos/keys esperadas.
- `test_io_xlsm.py`:
  - Escreve uma FLAMENGO.xlsm dummy e relê; round-trip preserva fórmulas (verifica algumas células).
  - Valida regra de `rod_cheg`/`dia_cheg` (4 casos: dentro da rodada, próxima rodada, +2 rodadas, dia limítrofe).
- `test_estado.py`: round-trip JSON com `OPDescartada` aninhada.
- `test_forecast.py`:
  - Treina em série sintética 96 pontos com sazonalidade conhecida; valida que prevê com erro < 10%.
  - Round-trip do `hw_models.json`.
  - Fallback Holt simples quando série não tem sazonal.
- `test_planner.py`:
  - 1 OP simples (cidade próxima a CD2) → gera 1 plano CD→varejo + 1 reposição + 1 produção + 1 compra MP.
  - 1 OP com dia_entrega impossível → vai pra `ops_descartadas`.
  - Capacidade MP estourada → fraciona ou descarta.
- `test_lp_modal.py`:
  - 2 tarefas pequenas → escolhe modal mais barato.
  - Janela de 1 dia (Fábrica→CD) → respeita.
  - Carga 90% cap → escolhe `o80=1` no objetivo.
- `test_pipeline.py` (smoke): roda `run_rodada(1, "rodadas/Rodada 1.xlsm")` ponta-a-ponta com dados reais; valida que `state.json` é criado e que `FLAMENGO.xlsm` ganha linhas em SOL_TRANSP.

Não busco cobertura — só smoke. O notebook é o "teste de integração" real.

---

## 15. requirements.txt

```
pandas>=2.1
numpy>=1.26
statsmodels>=0.14
pulp>=2.7
openpyxl>=3.1
matplotlib>=3.8
pyarrow>=14.0          # para parquet
pytest>=7.4
jupyter>=1.0
# opcionais
highspy>=1.7           # solver alternativo via JOGO_SOLVER=HIGHS
```

---

## 16. Sequência de implementação (resumo — vai virar plano detalhado)

1. `requirements.txt` + esqueleto de pastas + `__init__.py`s.
2. `src/config.py` + `src/domain.py` + `tests/test_config.py`.
3. `src/io_xlsm.py` (leitura primeiro, depois escrita) + regra `rod_cheg`/`dia_cheg` + `tests/test_io_xlsm.py`.
4. `src/estado.py` (load/save state + snapshots) + `tests/test_estado.py`.
5. `src/forecast.py` (HW + persistência JSON + fallback Holt) + `tests/test_forecast.py`.
6. `src/planner.py` (4 passos com simulador dia a dia) + `tests/test_planner.py`.
7. `src/lp_modal.py` (MILP com `o80`) + `tests/test_lp_modal.py`.
8. `src/pipeline.py` (orquestração com simulação dia a dia) + `tests/test_pipeline.py`.
9. `src/dashboard.py` (plots).
10. `jogo/rodada.ipynb` (interface).
11. Smoke test ponta-a-ponta: roda Rodada 1 e Rodada 2 mock e inspeciona output.

---

## 17. Pontos abertos (para confirmar depois)

1. **OP da Rodada 2 ainda não chegou** — quando chegar, formatar como `OP_Rodada_2.xlsx` (5 colunas). Sem isso o pipeline da Rodada 2 roda **só com forecast** (modo "antecipação").
2. **Tempo de fit completo do HW (~15s/rodada):** se virar gargalo, paralelizar com `joblib.Parallel(n_jobs=-1)`. Hoje aceito.
3. **`o80` binária aumenta tamanho do MILP:** se CBC ficar > 30s, considerar relaxação contínua (assumir só `o80=1` para tarefas com `qtd > 0.8 × cap`) ou usar HiGHS via env var.
4. **OPs antecipadas (rodada futura):** spec assume que prof entrega só OPs da rodada corrente. Se aparecerem com `rodada > N`, ficam em `ops_pendentes` e o planner Passo 1 da rodada seguinte trata. Validar quando ver a primeira OP real.
