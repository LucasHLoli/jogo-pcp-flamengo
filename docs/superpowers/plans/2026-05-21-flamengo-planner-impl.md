# Planner FLAMENGO — Plano de Implementação

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Spec:** [`docs/superpowers/specs/2026-05-21-flamengo-planner-design.md`](../specs/2026-05-21-flamengo-planner-design.md)

**Goal:** Construir um pipeline Python que, a cada rodada do Jogo PCP 2, lê o estado anterior + planilha do prof + OP recebida, faz forecast Holt-Winters por (cidade, PA), planeja produção e transportes via heurística+MILP, e preenche `rodadas/FLAMENGO.xlsm` (abas SOL_TRANSP e OP_FABRICAS) preservando o VBA.

**Architecture:** Módulos puros em `src/` (config, domain, io_xlsm, estado, forecast, planner, lp_modal, pipeline, dashboard) orquestrados por uma função `run_rodada(N, path)` chamada de um notebook em `jogo/rodada.ipynb`. Estado persistido em `estado/` como JSON + parquet — sem serialização binária insegura.

**Tech Stack:** Python 3.11+, pandas, numpy, statsmodels (Holt-Winters), PuLP+CBC (MILP), openpyxl, matplotlib, pyarrow, pytest.

---

## Mapa de arquivos

| Arquivo | Responsabilidade |
| --- | --- |
| `requirements.txt` | Dependências fixadas |
| `src/__init__.py` | Marker do pacote |
| `src/config.py` | Carrega `parametros.json` + matrizes de distância; expõe `Config` |
| `src/domain.py` | Dataclasses: `TransitItem`, `OP`, `OPDescartada`, `Estado`, `PlanoTransporte`, `PlanoProducao`, `TarefaTransporte` |
| `src/io_xlsm.py` | Ler `INSTALAÇÕES`/`SOL_TRANSP`/`OP_Rodada_<N>.xlsx`; escrever `SOL_TRANSP`/`OP_FABRICAS` preservando VBA |
| `src/estado.py` | Load/save `state.json`; snapshot `historico_rodada_<N>.json` |
| `src/forecast.py` | Treino inicial HW (75 séries, fallback Holt); agregação OP→série; refit; previsão; persistência JSON |
| `src/planner.py` | 4 passos: entregas CD→varejo, reposição F1→CD, produção F1 (LPT), compras MP (just-in-time) |
| `src/lp_modal.py` | MILP PuLP: aloca modal+dia minimizando custo (regra ≥80% / <80%) |
| `src/pipeline.py` | Orquestra `run_rodada(N, path)` |
| `src/dashboard.py` | Lê snapshots, gera plots matplotlib + tabela resumo |
| `jogo/rodada.ipynb` | Interface do usuário (1 célula por etapa) |
| `tests/fixtures/` | Fixtures sintéticas pequenas |
| `tests/test_*.py` | Smoke tests por módulo |

---

## Task 1: Setup do projeto

**Files:**
- Create: `requirements.txt`
- Create: `src/__init__.py`
- Create: `tests/__init__.py`
- Create: `tests/fixtures/__init__.py`
- Create: `jogo/.gitkeep`
- Create: `estado/.gitkeep`
- Create: `.gitignore`

- [ ] **Step 1.1: Criar `requirements.txt`**

```
pandas>=2.1
numpy>=1.26
statsmodels>=0.14
pulp>=2.7
openpyxl>=3.1
matplotlib>=3.8
pyarrow>=14.0
pytest>=7.4
jupyter>=1.0
nbformat>=5.9
# opcional
highspy>=1.7
```

- [ ] **Step 1.2: Criar `.gitignore`**

```
__pycache__/
*.py[cod]
.pytest_cache/
.ipynb_checkpoints/
estado/state.json
estado/hw_models.json
estado/historico_demanda_ampliado.parquet
estado/historico_rodada_*.json
.tmp/
*.egg-info/
```

> Mantemos só `.gitkeep` em `estado/` — o conteúdo é gerado em runtime.

- [ ] **Step 1.3: Criar esqueleto de pastas e `__init__.py`s vazios**

```bash
mkdir -p src tests/fixtures jogo estado .tmp/pulp
touch src/__init__.py tests/__init__.py tests/fixtures/__init__.py
touch jogo/.gitkeep estado/.gitkeep
```

- [ ] **Step 1.4: Instalar deps em venv local**

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

Expected: instalação sem erro. PuLP traz o `cbc.exe` embutido.

- [ ] **Step 1.5: Smoke test do solver CBC**

```python
# tests/test_setup.py
import pulp

def test_cbc_disponivel():
    prob = pulp.LpProblem("smoke", pulp.LpMinimize)
    x = pulp.LpVariable("x", lowBound=0)
    prob += x
    prob += x >= 1
    status = prob.solve(pulp.PULP_CBC_CMD(msg=False, tmpDir="./.tmp/pulp"))
    assert pulp.LpStatus[status] == "Optimal"
    assert pulp.value(x) == 1.0
```

Run: `pytest tests/test_setup.py -v`
Expected: PASS.

- [ ] **Step 1.6: Commit**

```bash
git add requirements.txt .gitignore src/ tests/ jogo/ estado/
git commit -m "chore(setup): estrutura inicial do projeto + deps + smoke CBC"
```

---

## Task 2: Domain (dataclasses)

**Files:**
- Create: `src/domain.py`
- Create: `tests/test_domain.py`

- [ ] **Step 2.1: Escrever `tests/test_domain.py` (round-trip JSON)**

```python
import json
from dataclasses import asdict
from src.domain import (
    Estado, TransitItem, OP, OPDescartada,
    PlanoTransporte, PlanoProducao, TarefaTransporte,
)


def test_estado_round_trip_json():
    estado = Estado(
        rodada_atual=2,
        estoque_mp_fabrica={"F1": {"MP1": 10.5, "MP2": 0.0, "MP3": 5.0}},
        estoque_pa_cd={
            "CD1": {"PA1": 100, "PA2": 0, "PA3": 50},
            "CD2": {"PA1": 0, "PA2": 200, "PA3": 0},
        },
        transit=[TransitItem(
            rod_part=1, dia_part=4, rod_cheg=2, dia_cheg=2,
            origem_tipo="Fábrica", origem_cidade="Joinville",
            destino_tipo="CD", destino_cidade="São Luís",
            modal="Caminhão", item="PA1", qtd=27200.0,
        )],
        ops_pendentes=[],
        ops_atendidas=[OP(rodada=2, cidade="São Paulo", pa="PA1", qtd=50000, dia_entrega=3)],
        ops_descartadas=[OPDescartada(
            op=OP(rodada=2, cidade="Manaus", pa="PA3", qtd=1000, dia_entrega=1),
            motivo="sem_estoque_CD",
            rodada_descarte=2,
        )],
    )
    blob = json.dumps(asdict(estado), ensure_ascii=False)
    data = json.loads(blob)
    assert data["rodada_atual"] == 2
    assert data["transit"][0]["destino_cidade"] == "São Luís"
    assert data["ops_descartadas"][0]["motivo"] == "sem_estoque_CD"
    assert data["estoque_pa_cd"]["CD1"]["PA1"] == 100


def test_tarefa_transporte_minimal():
    t = TarefaTransporte(
        origem_cidade="Joinville", destino_cidade="Santos",
        item="PA1", qtd=80000, janela_dias=[3],
        rodada=2, motivo="reposição_CD2_PA1",
    )
    assert t.janela_dias == [3]
```

Run: `pytest tests/test_domain.py -v`
Expected: FAIL (import error — módulo não existe).

- [ ] **Step 2.2: Escrever `src/domain.py`**

```python
"""Dataclasses do domínio do Jogo PCP 2 (FLAMENGO)."""
from dataclasses import dataclass, field
from typing import Dict, List, Literal

Item = Literal["MP1", "MP2", "MP3", "PA1", "PA2", "PA3"]
Modal = Literal["Avião", "Caminhão", "Navio"]
TipoOrigem = Literal["Fornecedor", "Fábrica", "CD"]
TipoDestino = Literal["Fábrica", "CD", "Varejista"]


@dataclass
class TransitItem:
    rod_part: int
    dia_part: int
    rod_cheg: int
    dia_cheg: int
    origem_tipo: TipoOrigem
    origem_cidade: str
    destino_tipo: TipoDestino
    destino_cidade: str
    modal: Modal
    item: Item
    qtd: float


@dataclass
class OP:
    rodada: int
    cidade: str
    pa: Item
    qtd: int
    dia_entrega: int


@dataclass
class OPDescartada:
    op: OP
    motivo: str
    rodada_descarte: int


@dataclass
class Estado:
    rodada_atual: int
    estoque_mp_fabrica: Dict[str, Dict[str, float]]
    estoque_pa_cd: Dict[str, Dict[str, int]]
    transit: List[TransitItem]
    ops_pendentes: List[OP]
    ops_atendidas: List[OP]
    ops_descartadas: List[OPDescartada]


@dataclass
class PlanoTransporte:
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
    rodada: int
    fabrica: str
    dia: int
    pa: Item
    qtd: int


@dataclass
class TarefaTransporte:
    origem_cidade: str
    destino_cidade: str
    item: Item
    qtd: float
    janela_dias: List[int]
    rodada: int
    motivo: str
    origem_tipo: TipoOrigem = "Fábrica"
    destino_tipo: TipoDestino = "CD"
```

- [ ] **Step 2.3: Rodar testes**

Run: `pytest tests/test_domain.py -v`
Expected: PASS (2 tests).

- [ ] **Step 2.4: Commit**

```bash
git add src/domain.py tests/test_domain.py
git commit -m "feat(domain): dataclasses do dominio (Estado/OP/TransitItem/...)"
```

---

## Task 3: Config (carregador de constantes)

**Files:**
- Create: `src/config.py`
- Create: `tests/test_config.py`

- [ ] **Step 3.1: Escrever `tests/test_config.py`**

```python
from pathlib import Path
import math
from src.config import Config

BASE = Path(__file__).resolve().parents[1]


def test_carrega_parametros():
    cfg = Config.load(BASE)
    assert cfg.BoM["PA1"]["MP1"] == 60
    assert cfg.BoM["PA1"]["peso_total_g"] == 300
    assert math.isclose(cfg.peso_un_ton["PA1"], 3e-4, rel_tol=1e-6)
    assert math.isclose(cfg.peso_un_ton["PA3"], 1.5e-4, rel_tol=1e-6)
    assert cfg.cap_modal_ton["Caminhão"] == 24
    assert cfg.cap_modal_por_item["Caminhão"]["PA1"] == 80000  # 24 / 3e-4
    assert cfg.cap_modal_por_item["Avião"]["PA1"] == 3333      # floor(1 / 3e-4)
    assert cfg.cap_modal_por_item["Navio"]["MP1"] == 100
    assert len(cfg.fornecedores["MP1"]) == 2
    assert cfg.ne_por_cidade["São Paulo"] == 1
    assert cfg.ne_por_cidade["Joinville"] == 6


def test_carrega_distancias():
    cfg = Config.load(BASE)
    assert "Caminhão" in cfg.distancias
    assert cfg.distancias["Caminhão"].shape[0] == 25
    assert len(cfg.rotas_navio_validas) > 0
```

Run: `pytest tests/test_config.py -v`
Expected: FAIL (import error).

- [ ] **Step 3.2: Escrever `src/config.py`**

```python
"""Carrega constantes do jogo e matrizes de distância."""
from __future__ import annotations
import json
import math
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Set, Tuple

import pandas as pd


@dataclass
class Config:
    BoM: Dict[str, Dict[str, int]]
    velocidades: Dict[str, int]
    peso_un_ton: Dict[str, float]
    densidades_mp: Dict[str, float]
    densidades_pa: Dict[str, float]
    cap_modal_ton: Dict[str, float]
    cap_modal_por_item: Dict[str, Dict[str, float]]
    frete_viagem: Dict[str, float]
    frete_peso: Dict[str, float]
    doc_modal: Dict[str, float]
    fornecedores: Dict[str, List[Tuple[str, float]]]
    ne_por_cidade: Dict[str, int]
    distancias: Dict[str, pd.DataFrame]
    rotas_navio_validas: Set[Tuple[str, str]]
    capacidades: Dict[str, Any]
    precos_referencia: Dict[str, float]

    @classmethod
    def load(cls, base_dir: Path) -> "Config":
        params = json.loads((base_dir / "data" / "parametros.json").read_text(encoding="utf-8"))

        bom = params["bom_pa"]
        BoM = {}
        for pa, d in bom.items():
            BoM[pa] = {"MP1": d["MP1"], "MP2": d["MP2"], "MP3": d["MP3"],
                       "peso_total_g": d["peso_total_g"], "prod_un_min": d["prod_un_min"]}
        velocidades = {pa: d["prod_un_min"] for pa, d in bom.items()}
        peso_un_ton = {pa: d["peso_total_g"] / 1_000_000 for pa, d in bom.items()}

        cap_modal_ton = {m: d["cap_ton"] for m, d in params["modais"].items()}
        cap_modal_por_item = {}
        for m, d in params["modais"].items():
            cap_modal_por_item[m] = {}
            for pa in ("PA1", "PA2", "PA3"):
                cap_modal_por_item[m][pa] = math.floor(d["cap_ton"] / peso_un_ton[pa])
            for mp in ("MP1", "MP2", "MP3"):
                cap_modal_por_item[m][mp] = d["cap_ton"]

        frete_viagem = {m: d["frete_viagem"] for m, d in params["modais"].items()}
        frete_peso = {m: d["frete_peso"] for m, d in params["modais"].items()}
        doc_modal = {m: d["doc"] for m, d in params["modais"].items()}

        fornecedores: Dict[str, List[Tuple[str, float]]] = {}
        for f in params["fornecedores_mp"]:
            fornecedores.setdefault(f["mp"], []).append((f["cidade"], float(f["custo_ton"])))

        distancias = {}
        modal_files = {
            "Caminhão": "distancias_caminhao.parquet",
            "Avião": "distancias_aviao.parquet",
            "Navio": "distancias_navio.parquet",
        }
        rotas_navio: Set[Tuple[str, str]] = set()
        for modal, fname in modal_files.items():
            df = pd.read_parquet(base_dir / "data" / fname)
            distancias[modal] = df
            if modal == "Navio":
                for orig in df.index:
                    for dest in df.columns:
                        v = df.at[orig, dest]
                        if pd.notna(v) and float(v) > 0:
                            rotas_navio.add((orig, dest))

        return cls(
            BoM=BoM,
            velocidades=velocidades,
            peso_un_ton=peso_un_ton,
            densidades_mp=params["densidade_mp_ton_m3"],
            densidades_pa=params["densidade_pa_ton_m3"],
            cap_modal_ton=cap_modal_ton,
            cap_modal_por_item=cap_modal_por_item,
            frete_viagem=frete_viagem,
            frete_peso=frete_peso,
            doc_modal=doc_modal,
            fornecedores=fornecedores,
            ne_por_cidade=params["ne_por_cidade"],
            distancias=distancias,
            rotas_navio_validas=rotas_navio,
            capacidades=params["custos_estruturais"],
            precos_referencia=params["preco_referencia"],
        )
```

- [ ] **Step 3.3: Rodar testes**

Run: `pytest tests/test_config.py -v`
Expected: PASS.

- [ ] **Step 3.4: Commit**

```bash
git add src/config.py tests/test_config.py
git commit -m "feat(config): carregador de parametros e matrizes de distancia"
```

---

## Task 4: io_xlsm — Leitura

**Files:**
- Create: `src/io_xlsm.py`
- Create: `tests/conftest.py`
- Create: `tests/test_io_xlsm_leitura.py`

- [ ] **Step 4.1: Criar fixture em `tests/conftest.py`**

```python
import pytest
import pandas as pd


@pytest.fixture(scope="session")
def op_rodada_dummy(tmp_path_factory):
    path = tmp_path_factory.mktemp("rodadas") / "OP_Rodada_2.xlsx"
    pd.DataFrame([
        {"Rodada": 2, "Cidade": "São Paulo", "PA": "PA1", "Qtd": 50000, "Dia_Entrega": 3},
        {"Rodada": 2, "Cidade": "Rio de Janeiro", "PA": "PA2", "Qtd": 30000, "Dia_Entrega": 5},
    ]).to_excel(path, index=False)
    return path
```

- [ ] **Step 4.2: Escrever testes em `tests/test_io_xlsm_leitura.py`**

```python
from pathlib import Path
from src.io_xlsm import ler_instalacoes, ler_sol_transp, ler_op_rodada, calcular_rod_dia_chegada

BASE = Path(__file__).resolve().parents[1]
FLAMENGO = BASE / "rodadas" / "FLAMENGO.xlsm"
RODADA1 = BASE / "rodadas" / "Rodada 1.xlsm"


def test_ler_instalacoes_real():
    inst = ler_instalacoes(FLAMENGO)
    assert inst["empresa"] == "FLAMENGO"
    f1 = inst["fabricas"]["F1"]
    assert f1["cidade"] == "Joinville"
    assert f1["maquinas"] == 7
    assert f1["turnos"] == 3
    assert f1["area_mp"]["MP1"] == 127.0
    cd1 = inst["cds"]["CD1"]
    assert cd1["cidade"] == "São Luís"
    assert cd1["area_pa"]["PA3"] == 873.0


def test_ler_sol_transp_rodada1():
    items = ler_sol_transp(RODADA1, rodada=1)
    assert len(items) >= 10
    primeiro_pa = [t for t in items if t.item.startswith("PA")][0]
    assert primeiro_pa.origem_cidade == "Joinville"
    assert primeiro_pa.destino_tipo == "CD"


def test_calcular_rod_dia_chegada_dentro_da_rodada():
    rc, dc = calcular_rod_dia_chegada(rod_part=1, dia_part=1, lead_dias=3)
    assert (rc, dc) == (1, 4)


def test_calcular_rod_dia_chegada_atravessa():
    rc, dc = calcular_rod_dia_chegada(rod_part=1, dia_part=4, lead_dias=3)
    assert (rc, dc) == (2, 2)


def test_calcular_rod_dia_chegada_duas_rodadas():
    rc, dc = calcular_rod_dia_chegada(rod_part=1, dia_part=5, lead_dias=10)
    assert (rc, dc) == (3, 5)


def test_ler_op_rodada(op_rodada_dummy):
    ops = ler_op_rodada(op_rodada_dummy)
    assert len(ops) == 2
    assert ops[0].cidade == "São Paulo"
    assert ops[0].pa == "PA1"
    assert ops[0].qtd == 50000
    assert ops[0].dia_entrega == 3


def test_ler_op_rodada_inexistente(tmp_path):
    ops = ler_op_rodada(tmp_path / "nao_existe.xlsx")
    assert ops == []
```

Run: `pytest tests/test_io_xlsm_leitura.py -v`
Expected: FAIL.

- [ ] **Step 4.3: Escrever `src/io_xlsm.py` (parte leitura)**

```python
"""Leitura e escrita de FLAMENGO.xlsm, Rodada N.xlsm e OP_Rodada_N.xlsx."""
from __future__ import annotations
import re
from pathlib import Path
from typing import Any, Dict, List, Tuple

import openpyxl
import pandas as pd

from src.domain import OP, TransitItem, PlanoProducao, PlanoTransporte


_DIA_RE = re.compile(r"Dia\s*(\d+)")
_RODADA_RE = re.compile(r"Rodada_?(\d+)")


def _parse_dia(value) -> int | None:
    if value is None:
        return None
    s = str(value).strip()
    m = _DIA_RE.search(s)
    return int(m.group(1)) if m else None


def _parse_rodada(value) -> int | None:
    if value is None:
        return None
    s = str(value).strip()
    m = _RODADA_RE.search(s)
    return int(m.group(1)) if m else None


def ler_instalacoes(path: Path) -> Dict[str, Any]:
    wb = openpyxl.load_workbook(path, keep_vba=True, data_only=True)
    ws = wb["INSTALAÇÕES"]
    empresa = ws.cell(1, 3).value
    fabricas = {}
    for row in (8, 9):
        nome = ws.cell(row, 1).value
        cidade = ws.cell(row, 2).value
        if not cidade:
            continue
        fabricas[nome] = {
            "cidade": cidade,
            "maquinas": int(ws.cell(row, 3).value or 0),
            "turnos": int(ws.cell(row, 4).value or 0),
            "mo": int(ws.cell(row, 5).value or 0),
            "area_mp": {
                "MP1": float(ws.cell(row, 6).value or 0),
                "MP2": float(ws.cell(row, 7).value or 0),
                "MP3": float(ws.cell(row, 8).value or 0),
            },
        }
    cds = {}
    for row in (12, 13, 14, 15):
        nome = ws.cell(row, 1).value
        cidade = ws.cell(row, 2).value
        if not cidade:
            continue
        cds[nome] = {
            "cidade": cidade,
            "area_pa": {
                "PA1": float(ws.cell(row, 3).value or 0),
                "PA2": float(ws.cell(row, 4).value or 0),
                "PA3": float(ws.cell(row, 5).value or 0),
            },
            "area_total": float(ws.cell(row, 6).value or 0),
        }
    return {"empresa": empresa, "fabricas": fabricas, "cds": cds}


def calcular_rod_dia_chegada(rod_part: int, dia_part: int, lead_dias: int) -> Tuple[int, int]:
    """Regra fechada (spec §6.2)."""
    total = dia_part + lead_dias
    rod_cheg = rod_part + (total - 1) // 5
    dia_cheg = ((total - 1) % 5) + 1
    return rod_cheg, dia_cheg


def ler_sol_transp(path: Path, rodada: int | None = None) -> List[TransitItem]:
    wb = openpyxl.load_workbook(path, keep_vba=True, data_only=True)
    ws = wb["SOL_TRANSP"]
    items: List[TransitItem] = []
    for r in range(5, ws.max_row + 1):
        rod = _parse_rodada(ws.cell(r, 1).value)
        if rod is None:
            break
        if rodada is not None and rod != rodada:
            continue
        origem_tipo = ws.cell(r, 2).value
        origem_cidade = ws.cell(r, 3).value
        dia_part = _parse_dia(ws.cell(r, 4).value)
        modal = ws.cell(r, 5).value
        item = ws.cell(r, 6).value
        qtd = ws.cell(r, 7).value
        destino_tipo = ws.cell(r, 8).value
        destino_cidade = ws.cell(r, 9).value
        lead = ws.cell(r, 10).value
        if dia_part is None or modal is None or item is None or qtd is None:
            continue
        try:
            lead_int = int(float(lead)) if lead is not None else 0
        except (TypeError, ValueError):
            lead_int = 0
        rod_cheg, dia_cheg = calcular_rod_dia_chegada(rod, dia_part, lead_int)
        items.append(TransitItem(
            rod_part=rod, dia_part=dia_part,
            rod_cheg=rod_cheg, dia_cheg=dia_cheg,
            origem_tipo=origem_tipo, origem_cidade=origem_cidade,
            destino_tipo=destino_tipo, destino_cidade=destino_cidade,
            modal=modal, item=item, qtd=float(qtd),
        ))
    return items


def ler_op_rodada(path: Path) -> List[OP]:
    path = Path(path)
    if not path.exists():
        return []
    df = pd.read_excel(path)
    return [
        OP(rodada=int(r["Rodada"]), cidade=str(r["Cidade"]), pa=str(r["PA"]),
           qtd=int(r["Qtd"]), dia_entrega=int(r["Dia_Entrega"]))
        for _, r in df.iterrows()
    ]
```

- [ ] **Step 4.4: Rodar testes**

Run: `pytest tests/test_io_xlsm_leitura.py -v`
Expected: PASS (todos os 7 testes).

- [ ] **Step 4.5: Commit**

```bash
git add src/io_xlsm.py tests/test_io_xlsm_leitura.py tests/conftest.py
git commit -m "feat(io_xlsm): leitura de INSTALACOES/SOL_TRANSP/OP_Rodada + regra rod_cheg"
```

---

## Task 5: io_xlsm — Escrita (preserva VBA)

**Files:**
- Modify: `src/io_xlsm.py` (adicionar `escrever_plano`)
- Create: `tests/test_io_xlsm_escrita.py`

- [ ] **Step 5.1: Escrever testes**

```python
import shutil
from pathlib import Path
import openpyxl
from src.io_xlsm import escrever_plano, ler_sol_transp
from src.domain import PlanoTransporte, PlanoProducao

BASE = Path(__file__).resolve().parents[1]
FLAMENGO_ORIG = BASE / "rodadas" / "FLAMENGO.xlsm"


def test_escrever_sol_transp_e_op_fabricas(tmp_path):
    dst = tmp_path / "FLAMENGO.xlsm"
    shutil.copy(FLAMENGO_ORIG, dst)

    planos_t = [
        PlanoTransporte(rodada=2, origem_tipo="Fornecedor", origem_cidade="Manaus",
                        dia_coleta=1, modal="Caminhão", item="MP1", qtd=24.0,
                        destino_tipo="Fábrica", destino_cidade="Joinville"),
        PlanoTransporte(rodada=2, origem_tipo="Fábrica", origem_cidade="Joinville",
                        dia_coleta=3, modal="Navio", item="PA1", qtd=80000,
                        destino_tipo="CD", destino_cidade="Santos"),
    ]
    planos_p = [
        PlanoProducao(rodada=2, fabrica="F1", dia=1, pa="PA1", qtd=10000),
        PlanoProducao(rodada=2, fabrica="F1", dia=2, pa="PA2", qtd=20000),
    ]
    escrever_plano(dst, planos_t, planos_p, rodada_n=2)

    items = ler_sol_transp(dst, rodada=2)
    assert len(items) == 2
    assert items[0].item == "MP1"
    assert items[1].destino_cidade == "Santos"

    wb = openpyxl.load_workbook(dst, keep_vba=True, data_only=False)
    ws = wb["OP_FABRICAS"]
    assert ws.cell(7, 2).value == 10000
    assert ws.cell(8, 3).value == 20000

    # VBA preservado
    assert wb.vba_archive is not None


def test_escrita_preserva_formulas_calculadas(tmp_path):
    dst = tmp_path / "FLAMENGO.xlsm"
    shutil.copy(FLAMENGO_ORIG, dst)
    escrever_plano(dst, [], [], rodada_n=2)

    wb = openpyxl.load_workbook(dst, keep_vba=True, data_only=False)
    ws = wb["SOL_TRANSP"]
    cell = ws.cell(5, 10)
    # célula J5 é fórmula de "Dias úteis viagem"
    assert cell.value is not None and str(cell.value).startswith("=")


def test_escrita_rodada2_preserva_rodada1(tmp_path):
    """Cenário real: SOL_TRANSP já tem 13 linhas de Rodada_1; escrevemos Rodada_2 sem
    sobrescrever as anteriores."""
    src = BASE / "rodadas" / "Rodada 1.xlsm"  # tem 13 linhas pré-preenchidas
    dst = tmp_path / "FLAMENGO.xlsm"
    shutil.copy(src, dst)

    planos_t = [
        PlanoTransporte(rodada=2, origem_tipo="Fábrica", origem_cidade="Joinville",
                        dia_coleta=2, modal="Caminhão", item="PA1", qtd=80000,
                        destino_tipo="CD", destino_cidade="São Luís"),
    ]
    escrever_plano(dst, planos_t, [], rodada_n=2)

    # Rodada_1 preservada
    items_r1 = ler_sol_transp(dst, rodada=1)
    assert len(items_r1) >= 10
    # Rodada_2 escrita
    items_r2 = ler_sol_transp(dst, rodada=2)
    assert len(items_r2) == 1
    assert items_r2[0].modal == "Caminhão"
```

Run: `pytest tests/test_io_xlsm_escrita.py -v`
Expected: FAIL.

- [ ] **Step 5.2: Adicionar `escrever_plano` em `src/io_xlsm.py`**

```python
def escrever_plano(
    path: Path,
    planos_transporte: List["PlanoTransporte"],
    planos_producao: List["PlanoProducao"],
    rodada_n: int,
) -> None:
    """Escreve SOL_TRANSP e OP_FABRICAS preservando VBA e fórmulas.

    SOL_TRANSP: limpa colunas A-I das linhas da rodada_n e regrava.
    OP_FABRICAS: atualiza bloco F1 (linhas 7-11, colunas B-D).
    """
    wb = openpyxl.load_workbook(path, keep_vba=True, data_only=False)
    ws = wb["SOL_TRANSP"]

    # 1) Limpar linhas A-I desta rodada (preserva J-Z fórmulas)
    for r in range(5, ws.max_row + 1):
        rod = _parse_rodada(ws.cell(r, 1).value)
        if rod == rodada_n:
            for c in range(1, 10):
                ws.cell(r, c).value = None

    # 2) Encontrar primeira linha livre para a rodada N
    linha_alvo = 5
    while True:
        val = ws.cell(linha_alvo, 1).value
        if val is None or str(val).strip() == "":
            break
        linha_alvo += 1

    # 3) Escrever planos
    for plano in planos_transporte:
        ws.cell(linha_alvo, 1).value = f"Rodada_{plano.rodada}"
        ws.cell(linha_alvo, 2).value = plano.origem_tipo
        ws.cell(linha_alvo, 3).value = plano.origem_cidade
        ws.cell(linha_alvo, 4).value = f"Dia {plano.dia_coleta}"
        ws.cell(linha_alvo, 5).value = plano.modal
        ws.cell(linha_alvo, 6).value = plano.item
        ws.cell(linha_alvo, 7).value = plano.qtd
        ws.cell(linha_alvo, 8).value = plano.destino_tipo
        ws.cell(linha_alvo, 9).value = plano.destino_cidade
        linha_alvo += 1

    # 4) OP_FABRICAS bloco F1: linhas 7..11, colunas B=PA1, C=PA2, D=PA3
    ws_op = wb["OP_FABRICAS"]
    pa_to_col = {"PA1": 2, "PA2": 3, "PA3": 4}
    for r in range(7, 12):
        for c in (2, 3, 4):
            ws_op.cell(r, c).value = 0.0
    for r in range(17, 22):
        for c in (2, 3, 4):
            ws_op.cell(r, c).value = 0.0
    dia_to_linha_f1 = {d: 6 + d for d in range(1, 6)}
    for plano in planos_producao:
        if plano.fabrica != "F1":
            continue
        r = dia_to_linha_f1[plano.dia]
        c = pa_to_col[plano.pa]
        ws_op.cell(r, c).value = int(plano.qtd)
    ws_op.cell(4, 6).value = f"Rodada_{rodada_n}"

    wb.save(path)
```

- [ ] **Step 5.3: Rodar testes**

Run: `pytest tests/test_io_xlsm_escrita.py -v`
Expected: PASS.

- [ ] **Step 5.4: Commit**

```bash
git add src/io_xlsm.py tests/test_io_xlsm_escrita.py
git commit -m "feat(io_xlsm): escrita de SOL_TRANSP/OP_FABRICAS preservando VBA"
```

---

## Task 6: Estado — load/save/snapshots

**Files:**
- Create: `src/estado.py`
- Create: `tests/test_estado.py`

- [ ] **Step 6.1: Escrever testes**

```python
from pathlib import Path
import json
from src.estado import salvar_estado, carregar_estado, snapshot_rodada, estado_inicial
from src.domain import Estado, TransitItem, OP


def test_carregar_inexistente_retorna_inicial(tmp_path):
    estado = carregar_estado(tmp_path / "state.json")
    assert estado.rodada_atual == 0
    assert estado.transit == []


def test_round_trip(tmp_path):
    e1 = estado_inicial()
    e1.transit.append(TransitItem(
        rod_part=1, dia_part=1, rod_cheg=1, dia_cheg=4,
        origem_tipo="Fornecedor", origem_cidade="Manaus",
        destino_tipo="Fábrica", destino_cidade="Joinville",
        modal="Caminhão", item="MP1", qtd=24.0,
    ))
    e1.ops_atendidas.append(OP(rodada=2, cidade="São Paulo", pa="PA1", qtd=50000, dia_entrega=3))
    path = tmp_path / "state.json"
    salvar_estado(e1, path)
    e2 = carregar_estado(path)
    assert e2.transit[0].destino_cidade == "Joinville"
    assert e2.ops_atendidas[0].cidade == "São Paulo"


def test_snapshot_rodada(tmp_path):
    e = estado_inicial()
    e.rodada_atual = 2
    snapshot_rodada(e, rodada_n=2, extras={"custo_total": 1234.5, "transportes": 10}, dir_path=tmp_path)
    f = tmp_path / "historico_rodada_2.json"
    assert f.exists()
    data = json.loads(f.read_text(encoding="utf-8"))
    assert data["rodada"] == 2
    assert data["extras"]["custo_total"] == 1234.5
    assert "estado" in data
```

Run: `pytest tests/test_estado.py -v`
Expected: FAIL.

- [ ] **Step 6.2: Escrever `src/estado.py`**

```python
"""Load/save state.json e snapshots por rodada."""
from __future__ import annotations
import json
from dataclasses import asdict
from pathlib import Path
from typing import Any, Dict

from src.domain import Estado, TransitItem, OP, OPDescartada


def estado_inicial() -> Estado:
    return Estado(
        rodada_atual=0,
        estoque_mp_fabrica={"F1": {"MP1": 0.0, "MP2": 0.0, "MP3": 0.0}},
        estoque_pa_cd={
            "CD1": {"PA1": 0, "PA2": 0, "PA3": 0},
            "CD2": {"PA1": 0, "PA2": 0, "PA3": 0},
        },
        transit=[],
        ops_pendentes=[],
        ops_atendidas=[],
        ops_descartadas=[],
    )


def carregar_estado(path: Path) -> Estado:
    path = Path(path)
    if not path.exists():
        return estado_inicial()
    data = json.loads(path.read_text(encoding="utf-8"))
    return Estado(
        rodada_atual=data["rodada_atual"],
        estoque_mp_fabrica=data["estoque_mp_fabrica"],
        estoque_pa_cd=data["estoque_pa_cd"],
        transit=[TransitItem(**t) for t in data["transit"]],
        ops_pendentes=[OP(**o) for o in data["ops_pendentes"]],
        ops_atendidas=[OP(**o) for o in data["ops_atendidas"]],
        ops_descartadas=[
            OPDescartada(op=OP(**d["op"]), motivo=d["motivo"], rodada_descarte=d["rodada_descarte"])
            for d in data["ops_descartadas"]
        ],
    )


def salvar_estado(estado: Estado, path: Path) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(asdict(estado), ensure_ascii=False, indent=2), encoding="utf-8")


def snapshot_rodada(estado: Estado, rodada_n: int, extras: Dict[str, Any], dir_path: Path) -> None:
    dir_path = Path(dir_path)
    dir_path.mkdir(parents=True, exist_ok=True)
    f = dir_path / f"historico_rodada_{rodada_n}.json"
    data = {"rodada": rodada_n, "estado": asdict(estado), "extras": extras}
    f.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
```

- [ ] **Step 6.3: Rodar testes**

Run: `pytest tests/test_estado.py -v`
Expected: PASS.

- [ ] **Step 6.4: Commit**

```bash
git add src/estado.py tests/test_estado.py
git commit -m "feat(estado): load/save state.json + snapshots por rodada"
```

---

## Task 7: Forecast — treino inicial + agregação OP + persistência JSON

**Files:**
- Create: `src/forecast.py`
- Create: `tests/test_forecast.py`

- [ ] **Step 7.1: Testes**

```python
import numpy as np
import pandas as pd
from src.forecast import (
    agregar_op_para_serie,
    treinar_inicial,
    prever,
    salvar_modelos,
    carregar_modelos,
)
from src.domain import OP


def test_agregar_op_para_serie():
    ops = [
        OP(rodada=2, cidade="São Paulo", pa="PA1", qtd=10000, dia_entrega=1),
        OP(rodada=2, cidade="São Paulo", pa="PA1", qtd=5000, dia_entrega=3),
        OP(rodada=2, cidade="Rio de Janeiro", pa="PA2", qtd=20000, dia_entrega=5),
    ]
    agg = agregar_op_para_serie(ops, rodada_n=2)
    assert agg[("São Paulo", "PA1")] == 15000
    assert agg[("Rio de Janeiro", "PA2")] == 20000


def test_treina_e_preve():
    rng = np.random.default_rng(42)
    base = np.tile(np.linspace(50, 100, 48), 2)
    ruido = rng.normal(0, 5, 96)
    serie = pd.DataFrame({
        "periodo_global": list(range(1, 97)),
        "cidade": ["TestCity"] * 96,
        "PA": ["PA1"] * 96,
        "qtd": base + ruido,
    })
    modelos = treinar_inicial(serie)
    assert ("TestCity", "PA1") in modelos
    info = modelos[("TestCity", "PA1")]
    assert info["tipo"] in ("HW_aditivo", "Holt_simples", "media_4")
    assert info["rmse_in_sample"] > 0

    forecast = prever(modelos, horizonte=4)
    assert len(forecast[("TestCity", "PA1")]) == 4
    assert all(v >= 0 for v in forecast[("TestCity", "PA1")])


def test_round_trip_json(tmp_path):
    serie = pd.DataFrame({
        "periodo_global": list(range(1, 97)),
        "cidade": ["A"] * 96,
        "PA": ["PA1"] * 96,
        "qtd": [100.0 + i for i in range(96)],
    })
    modelos = treinar_inicial(serie)
    path = tmp_path / "hw.json"
    salvar_modelos(modelos, path)
    recarregados = carregar_modelos(path)
    assert recarregados[("A", "PA1")]["tipo"] == modelos[("A", "PA1")]["tipo"]
```

Run: `pytest tests/test_forecast.py -v`
Expected: FAIL.

- [ ] **Step 7.2: Escrever `src/forecast.py`**

```python
"""Holt-Winters por (cidade, PA) com fallback Holt simples."""
from __future__ import annotations
import json
import warnings
from pathlib import Path
from typing import Dict, List, Tuple

import numpy as np
import pandas as pd
from statsmodels.tsa.holtwinters import ExponentialSmoothing

from src.domain import OP


def agregar_op_para_serie(ops: List[OP], rodada_n: int) -> Dict[Tuple[str, str], float]:
    agg: Dict[Tuple[str, str], float] = {}
    for op in ops:
        if op.rodada != rodada_n:
            continue
        k = (op.cidade, op.pa)
        agg[k] = agg.get(k, 0.0) + op.qtd
    return agg


def _fit_uma_serie(valores: np.ndarray) -> Dict:
    if len(valores) < 96:
        return _fit_holt_simples(valores)

    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        try:
            model = ExponentialSmoothing(
                valores, trend="add", seasonal="add",
                seasonal_periods=48, damped_trend=True,
                initialization_method="estimated",
            )
            fit = model.fit(optimized=True)
            rmse_hw = float(np.sqrt(np.mean((fit.fittedvalues - valores) ** 2)))
        except Exception:
            return _fit_holt_simples(valores)

    holt_info = _fit_holt_simples(valores)
    if rmse_hw > 1.2 * holt_info["rmse_in_sample"]:
        return holt_info

    return {
        "tipo": "HW_aditivo",
        "ultimo_periodo_treino": len(valores),
        "ultimo_valor": float(valores[-1]),
        "ultimo_nivel": float(fit.level[-1]) if hasattr(fit, "level") and len(fit.level) else float(np.mean(valores[-8:])),
        "ultimo_trend": float(fit.trend[-1]) if hasattr(fit, "trend") and len(fit.trend) else 0.0,
        "season_final": [float(x) for x in fit.season[-48:]] if hasattr(fit, "season") and len(fit.season) >= 48 else [],
        "rmse_in_sample": rmse_hw,
    }


def _fit_holt_simples(valores: np.ndarray) -> Dict:
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        try:
            model = ExponentialSmoothing(valores, trend="add", seasonal=None,
                                         initialization_method="estimated")
            fit = model.fit(optimized=True)
            rmse = float(np.sqrt(np.mean((fit.fittedvalues - valores) ** 2)))
            return {
                "tipo": "Holt_simples",
                "ultimo_periodo_treino": len(valores),
                "ultimo_valor": float(valores[-1]),
                "ultimo_nivel": float(fit.level[-1]) if hasattr(fit, "level") and len(fit.level) else float(valores[-1]),
                "ultimo_trend": float(fit.trend[-1]) if hasattr(fit, "trend") and len(fit.trend) else 0.0,
                "rmse_in_sample": rmse,
            }
        except Exception:
            ult = float(np.mean(valores[-4:])) if len(valores) >= 4 else float(np.mean(valores))
            return {
                "tipo": "media_4",
                "ultimo_periodo_treino": len(valores),
                "ultimo_valor": ult,
                "ultimo_nivel": ult,
                "ultimo_trend": 0.0,
                "rmse_in_sample": float(np.std(valores)),
            }


def treinar_inicial(historico: pd.DataFrame) -> Dict[Tuple[str, str], Dict]:
    modelos: Dict[Tuple[str, str], Dict] = {}
    for (cidade, pa), grupo in historico.groupby(["cidade", "PA"]):
        valores = grupo.sort_values("periodo_global")["qtd"].to_numpy(dtype=float)
        modelos[(cidade, pa)] = _fit_uma_serie(valores)
    return modelos


def prever(modelos: Dict[Tuple[str, str], Dict], horizonte: int = 4) -> Dict[Tuple[str, str], List[float]]:
    forecast: Dict[Tuple[str, str], List[float]] = {}
    for k, info in modelos.items():
        nivel = info["ultimo_nivel"]
        trend = info["ultimo_trend"]
        previsao = []
        if info["tipo"] == "HW_aditivo" and info.get("season_final"):
            season = info["season_final"]
            for h in range(1, horizonte + 1):
                s_idx = (info["ultimo_periodo_treino"] + h - 1) % 48
                v = nivel + h * trend + season[s_idx % len(season)]
                previsao.append(max(0.0, v))
        else:
            for h in range(1, horizonte + 1):
                previsao.append(max(0.0, nivel + h * trend))
        forecast[k] = previsao
    return forecast


def salvar_modelos(modelos: Dict[Tuple[str, str], Dict], path: Path) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    serializavel = {f"{c}||{p}": v for (c, p), v in modelos.items()}
    path.write_text(json.dumps(serializavel, ensure_ascii=False, indent=2), encoding="utf-8")


def carregar_modelos(path: Path) -> Dict[Tuple[str, str], Dict]:
    path = Path(path)
    if not path.exists():
        return {}
    raw = json.loads(path.read_text(encoding="utf-8"))
    return {tuple(k.split("||")): v for k, v in raw.items()}  # type: ignore
```

- [ ] **Step 7.3: Rodar testes**

Run: `pytest tests/test_forecast.py -v`
Expected: PASS. Warnings do statsmodels esperados — OK.

- [ ] **Step 7.4: Commit**

```bash
git add src/forecast.py tests/test_forecast.py
git commit -m "feat(forecast): HW aditivo + fallback Holt + agregacao OP + persistencia JSON"
```

---

## Task 8: Forecast — refit por rodada

**Files:**
- Modify: `src/forecast.py` (adicionar `refit`)
- Modify: `tests/test_forecast.py`

- [ ] **Step 8.1: Teste**

```python
def test_refit_adiciona_ponto(tmp_path):
    hist_path = tmp_path / "hist.parquet"
    df = pd.DataFrame({
        "periodo_global": list(range(1, 97)),
        "cidade": ["TestCity"] * 96,
        "PA": ["PA1"] * 96,
        "qtd": [100.0] * 96,
    })
    df.to_parquet(hist_path)

    from src.forecast import treinar_inicial, refit, agregar_op_para_serie
    modelos = treinar_inicial(df)
    ops = [OP(rodada=2, cidade="TestCity", pa="PA1", qtd=200, dia_entrega=3)]
    agg = agregar_op_para_serie(ops, rodada_n=2)
    novos_modelos = refit(hist_path, modelos, agg, rodada_n=2)

    df_novo = pd.read_parquet(hist_path)
    assert len(df_novo) == 97
    assert df_novo.iloc[-1]["periodo_global"] == 97
    assert df_novo.iloc[-1]["qtd"] == 200
    assert ("TestCity", "PA1") in novos_modelos
```

Run: `pytest tests/test_forecast.py::test_refit_adiciona_ponto -v`
Expected: FAIL.

- [ ] **Step 8.2: Adicionar `refit` em `src/forecast.py`**

```python
def refit(
    historico_path: Path,
    modelos_atuais: Dict[Tuple[str, str], Dict],
    ops_da_rodada: Dict[Tuple[str, str], float],
    rodada_n: int,
) -> Dict[Tuple[str, str], Dict]:
    historico_path = Path(historico_path)
    df = pd.read_parquet(historico_path)

    # Rodada 1 do jogo nao tem OP (so forecast), entao a primeira rodada que adiciona
    # ponto e a 2. Logo: periodo_global = 96 + (rodada_n - 1).
    periodo_global_novo = 96 + (rodada_n - 1)
    novas_linhas = []
    for (cidade, pa), qtd in ops_da_rodada.items():
        ja_existe = ((df["periodo_global"] == periodo_global_novo) &
                     (df["cidade"] == cidade) & (df["PA"] == pa)).any()
        if not ja_existe:
            novas_linhas.append({
                "periodo_global": periodo_global_novo,
                "cidade": cidade, "PA": pa, "qtd": float(qtd),
            })
    if novas_linhas:
        df = pd.concat([df, pd.DataFrame(novas_linhas)], ignore_index=True)
        df.to_parquet(historico_path, index=False)

    novos_modelos = dict(modelos_atuais)
    for (cidade, pa) in ops_da_rodada:
        valores = df[(df["cidade"] == cidade) & (df["PA"] == pa)] \
            .sort_values("periodo_global")["qtd"].to_numpy(dtype=float)
        novos_modelos[(cidade, pa)] = _fit_uma_serie(valores)
    return novos_modelos
```

- [ ] **Step 8.3: Rodar testes**

Run: `pytest tests/test_forecast.py -v`
Expected: PASS (4 tests).

- [ ] **Step 8.4: Commit**

```bash
git add src/forecast.py tests/test_forecast.py
git commit -m "feat(forecast): refit por rodada que atualiza historico ampliado"
```

---

## Task 9: Planner — Passo 1 (entregas CD→Varejo)

**Files:**
- Create: `src/planner.py`
- Create: `tests/test_planner.py`

- [ ] **Step 9.1: Testes**

```python
import pytest
from pathlib import Path
from src.config import Config
from src.domain import Estado, OP
from src.estado import estado_inicial
from src.planner import passo1_entregas_cd_varejo

BASE = Path(__file__).resolve().parents[1]


@pytest.fixture(scope="module")
def cfg():
    return Config.load(BASE)


def test_passo1_op_atendida(cfg):
    estado = estado_inicial()
    estado.estoque_pa_cd["CD2"]["PA1"] = 100000  # Santos
    ops = [OP(rodada=2, cidade="São Paulo", pa="PA1", qtd=50000, dia_entrega=5)]
    cds_info = {"CD1": "São Luís", "CD2": "Santos"}
    tarefas, descartadas = passo1_entregas_cd_varejo(estado, ops, cfg, cds_info, rodada_n=2)
    assert len(tarefas) == 1
    assert tarefas[0].origem_cidade == "Santos"  # CD2 mais perto de SP
    assert tarefas[0].qtd == 50000
    assert descartadas == []


def test_passo1_sem_estoque_descartada(cfg):
    estado = estado_inicial()  # tudo zero
    ops = [OP(rodada=2, cidade="Manaus", pa="PA3", qtd=1000, dia_entrega=1)]
    cds_info = {"CD1": "São Luís", "CD2": "Santos"}
    tarefas, descartadas = passo1_entregas_cd_varejo(estado, ops, cfg, cds_info, rodada_n=2)
    assert tarefas == []
    assert len(descartadas) == 1
    assert descartadas[0].motivo == "sem_estoque_CD"


def test_passo1_lead_time_inviavel(cfg):
    estado = estado_inicial()
    estado.estoque_pa_cd["CD1"]["PA1"] = 100000
    ops = [OP(rodada=2, cidade="Manaus", pa="PA1", qtd=10000, dia_entrega=1)]
    cds_info = {"CD1": "São Luís"}
    tarefas, descartadas = passo1_entregas_cd_varejo(estado, ops, cfg, cds_info, rodada_n=2)
    assert tarefas == []
    assert descartadas[0].motivo == "lead_time_inviavel"
```

Run: `pytest tests/test_planner.py -v`
Expected: FAIL.

- [ ] **Step 9.2: Escrever `src/planner.py`**

```python
"""Planner heurístico de 4 passos."""
from __future__ import annotations
import math
from typing import Dict, List, Tuple

from src.config import Config
from src.domain import (
    Estado, OP, OPDescartada, PlanoProducao, TarefaTransporte, TransitItem,
)


def _lead_time_dias(cfg: Config, origem: str, destino: str, modal: str) -> float:
    """Dias úteis de viagem (arredondado pra cima de 8h/dia)."""
    try:
        km = cfg.distancias[modal].at[origem, destino]
    except (KeyError, ValueError):
        return math.inf
    if km is None or (isinstance(km, float) and (km != km)):
        return math.inf
    if float(km) <= 0:
        return math.inf
    vel = {"Avião": 700, "Caminhão": 50, "Navio": 30}[modal]
    horas = float(km) / vel
    return max(1, math.ceil(horas / 8))


def passo1_entregas_cd_varejo(
    estado: Estado,
    ops: List[OP],
    cfg: Config,
    cds_info: Dict[str, str],
    rodada_n: int,
) -> Tuple[List[TarefaTransporte], List[OPDescartada]]:
    tarefas: List[TarefaTransporte] = []
    descartadas: List[OPDescartada] = []
    estoque_trab = {cd: dict(estado.estoque_pa_cd[cd]) for cd in cds_info}

    for op in ops:
        if op.rodada != rodada_n:
            continue
        candidatos = []
        for cd, cidade_cd in cds_info.items():
            lts = []
            for modal in ("Caminhão", "Navio", "Avião"):
                if modal == "Navio" and (cidade_cd, op.cidade) not in cfg.rotas_navio_validas:
                    continue
                lt = _lead_time_dias(cfg, cidade_cd, op.cidade, modal)
                if lt != math.inf:
                    lts.append(lt)
            if not lts:
                continue
            lt_min = min(lts)
            if lt_min > op.dia_entrega - 1:
                continue
            estoque_disp = estoque_trab[cd].get(op.pa, 0)
            if estoque_disp < op.qtd:
                continue
            candidatos.append((lt_min, -estoque_disp, cd, cidade_cd))

        if not candidatos:
            # classifica o motivo: se nenhum CD tem estoque suficiente do PA, motivo
            # primario eh "sem_estoque_CD". Se algum CD tem estoque mas nenhum cabe no
            # lead time, motivo eh "lead_time_inviavel".
            tem_estoque = any(estoque_trab[cd].get(op.pa, 0) >= op.qtd for cd in cds_info)
            motivo = "lead_time_inviavel" if tem_estoque else "sem_estoque_CD"
            descartadas.append(OPDescartada(op=op, motivo=motivo, rodada_descarte=rodada_n))
            continue

        candidatos.sort()
        lt_min, _, cd, cidade_cd = candidatos[0]
        estoque_trab[cd][op.pa] -= op.qtd
        janela = list(range(1, op.dia_entrega - lt_min + 1)) or [1]
        tarefas.append(TarefaTransporte(
            origem_cidade=cidade_cd, destino_cidade=op.cidade,
            item=op.pa, qtd=op.qtd, janela_dias=janela,
            rodada=rodada_n, motivo=f"OP_{op.cidade}_{op.pa}_d{op.dia_entrega}",
            origem_tipo="CD", destino_tipo="Varejista",
        ))
    return tarefas, descartadas
```

- [ ] **Step 9.3: Rodar testes**

Run: `pytest tests/test_planner.py -v`
Expected: PASS (3 tests).

- [ ] **Step 9.4: Commit**

```bash
git add src/planner.py tests/test_planner.py
git commit -m "feat(planner): Passo 1 - entregas CD->Varejo"
```

---

## Task 10: Planner — Passo 2 (reposição F1→CD multi-rodada)

**Files:**
- Modify: `src/planner.py`
- Modify: `tests/test_planner.py`

- [ ] **Step 10.1: Teste**

```python
def test_passo2_reposicao_basica(cfg):
    from src.planner import passo2_reposicao_fabrica_cd
    from src.estado import estado_inicial

    estado = estado_inicial()
    estado.estoque_pa_cd["CD2"]["PA1"] = 5000
    forecast = {
        ("São Paulo", "PA1"): [50000] * 4,
        ("Rio de Janeiro", "PA1"): [30000] * 4,
    }
    cidades_por_cd = {"CD1": ["Manaus", "Belém"], "CD2": ["São Paulo", "Rio de Janeiro", "Santos"]}
    cds_info = {"CD1": "São Luís", "CD2": "Santos"}
    saidas_cd = {"CD2": {"PA1": 10000}, "CD1": {"PA1": 0}}

    necessidades = passo2_reposicao_fabrica_cd(
        estado, forecast, cfg, cds_info, cidades_por_cd, saidas_cd, rodada_n=2,
    )
    assert necessidades["CD2"]["PA1"] > 0
    assert necessidades["CD1"]["PA1"] == 0
```

Run: `pytest tests/test_planner.py::test_passo2_reposicao_basica -v`
Expected: FAIL.

- [ ] **Step 10.2: Adicionar em `src/planner.py`**

```python
def passo2_reposicao_fabrica_cd(
    estado: Estado,
    forecast: Dict[Tuple[str, str], List[float]],
    cfg: Config,
    cds_info: Dict[str, str],
    cidades_por_cd: Dict[str, List[str]],
    saidas_cd: Dict[str, Dict[str, float]],
    rodada_n: int,
    fabrica_cidade: str = "Joinville",
) -> Dict[str, Dict[str, float]]:
    necessidades: Dict[str, Dict[str, float]] = {cd: {} for cd in cds_info}
    for cd, cidade_cd in cds_info.items():
        lt_dias = _lead_time_dias(cfg, fabrica_cidade, cidade_cd, "Caminhão")
        if lt_dias == math.inf:
            lt_dias = _lead_time_dias(cfg, fabrica_cidade, cidade_cd, "Navio")
            if lt_dias == math.inf:
                lt_dias = _lead_time_dias(cfg, fabrica_cidade, cidade_cd, "Avião")
        lt_rodadas = max(1, math.ceil(lt_dias / 5))

        # Atenção: `_aplicar_chegadas` já moveu para o estoque tudo com rod_cheg <= rodada_n.
        # Aqui só contamos o que AINDA está em trânsito (rod_cheg > rodada_n) e chegará dentro
        # da janela de lead_time. Sem o filtro inferior haveria dupla contagem.
        chegadas_pa = {pa: 0.0 for pa in ("PA1", "PA2", "PA3")}
        for t in estado.transit:
            if t.destino_tipo == "CD" and t.destino_cidade == cidade_cd and t.item.startswith("PA"):
                if rodada_n < t.rod_cheg <= rodada_n + lt_rodadas:
                    chegadas_pa[t.item] = chegadas_pa.get(t.item, 0.0) + t.qtd

        for pa in ("PA1", "PA2", "PA3"):
            demanda_janela = 0.0
            for cidade in cidades_por_cd.get(cd, []):
                fc = forecast.get((cidade, pa), [0.0, 0.0, 0.0, 0.0])
                idx_a = min(lt_rodadas, len(fc) - 1)
                idx_b = min(lt_rodadas + 1, len(fc) - 1)
                demanda_janela += fc[idx_a] + (fc[idx_b] if idx_a != idx_b else 0)

            saida = saidas_cd.get(cd, {}).get(pa, 0.0)
            estoque_pos = estado.estoque_pa_cd[cd][pa] - saida + chegadas_pa[pa]
            necessidades[cd][pa] = max(0.0, demanda_janela - estoque_pos)
    return necessidades
```

- [ ] **Step 10.3: Rodar testes**

Run: `pytest tests/test_planner.py -v`
Expected: PASS (4 tests).

- [ ] **Step 10.4: Commit**

```bash
git add src/planner.py tests/test_planner.py
git commit -m "feat(planner): Passo 2 - reposicao F1->CD com lead time multi-rodada"
```

---

## Task 11: Planner — Passo 3 (produção F1 LPT)

**Files:**
- Modify: `src/planner.py`
- Modify: `tests/test_planner.py`

- [ ] **Step 11.1: Teste**

```python
def test_passo3_aloca_por_dia(cfg):
    from src.planner import passo3_producao

    necessidades = {
        "CD1": {"PA1": 50000, "PA2": 0, "PA3": 0},
        "CD2": {"PA1": 30000, "PA2": 100000, "PA3": 0},
    }
    planos_prod, tarefas_f1_cd = passo3_producao(
        necessidades, cfg, cds_info={"CD1": "São Luís", "CD2": "Santos"},
        rodada_n=2, fabrica="F1", fabrica_cidade="Joinville", maquinas=7, turnos=3,
    )
    tot_pa1 = sum(p.qtd for p in planos_prod if p.pa == "PA1")
    assert tot_pa1 == 80000
    tot_pa2 = sum(p.qtd for p in planos_prod if p.pa == "PA2")
    assert tot_pa2 == 100000
    for t in tarefas_f1_cd:
        assert len(t.janela_dias) == 1
```

Run: `pytest tests/test_planner.py::test_passo3_aloca_por_dia -v`
Expected: FAIL.

- [ ] **Step 11.2: Implementar `passo3_producao`**

```python
def passo3_producao(
    necessidades: Dict[str, Dict[str, float]],
    cfg: Config,
    cds_info: Dict[str, str],
    rodada_n: int,
    fabrica: str = "F1",
    fabrica_cidade: str = "Joinville",
    maquinas: int = 7,
    turnos: int = 3,
) -> Tuple[List[PlanoProducao], List[TarefaTransporte]]:
    min_por_dia = maquinas * turnos * 8 * 60
    velocidades = cfg.velocidades

    total_por_pa: Dict[str, float] = {}
    for cd, d in necessidades.items():
        for pa, qtd in d.items():
            total_por_pa[pa] = total_por_pa.get(pa, 0.0) + qtd

    ordem_pa = sorted(total_por_pa.keys(),
                      key=lambda pa: -total_por_pa[pa] / velocidades[pa])
    capacidade_por_dia = [min_por_dia] * 5
    producao: Dict[int, Dict[str, int]] = {d: {} for d in range(1, 6)}

    for pa in ordem_pa:
        restante = total_por_pa[pa]
        for dia in range(1, 6):
            if restante <= 0:
                break
            cap_min = capacidade_por_dia[dia - 1]
            qtd_que_cabe = int(min(restante, cap_min * velocidades[pa]))
            if qtd_que_cabe <= 0:
                continue
            producao[dia][pa] = producao[dia].get(pa, 0) + qtd_que_cabe
            capacidade_por_dia[dia - 1] -= math.ceil(qtd_que_cabe / velocidades[pa])
            restante -= qtd_que_cabe

    planos: List[PlanoProducao] = []
    tarefas: List[TarefaTransporte] = []
    for dia in range(1, 6):
        for pa, qtd_total_dia in producao[dia].items():
            if qtd_total_dia <= 0:
                continue
            planos.append(PlanoProducao(rodada=rodada_n, fabrica=fabrica,
                                         dia=dia, pa=pa, qtd=qtd_total_dia))
            total_nec_pa = sum(necessidades[cd].get(pa, 0.0) for cd in cds_info)
            if total_nec_pa <= 0:
                continue
            for cd, cidade_cd in cds_info.items():
                fracao = necessidades[cd].get(pa, 0.0) / total_nec_pa
                qtd_cd = int(round(qtd_total_dia * fracao))
                if qtd_cd <= 0:
                    continue
                tarefas.append(TarefaTransporte(
                    origem_cidade=fabrica_cidade, destino_cidade=cidade_cd,
                    item=pa, qtd=qtd_cd, janela_dias=[dia],
                    rodada=rodada_n, motivo=f"reposição_{cd}_{pa}_d{dia}",
                    origem_tipo="Fábrica", destino_tipo="CD",
                ))
    return planos, tarefas
```

- [ ] **Step 11.3: Rodar testes**

Run: `pytest tests/test_planner.py -v`
Expected: PASS.

- [ ] **Step 11.4: Commit**

```bash
git add src/planner.py tests/test_planner.py
git commit -m "feat(planner): Passo 3 - producao F1 com LPT e acoplamento dia"
```

---

## Task 12: Planner — Passo 4 (compras MP)

**Files:**
- Modify: `src/planner.py`
- Modify: `tests/test_planner.py`

- [ ] **Step 12.1: Teste**

```python
def test_passo4_gera_compras(cfg):
    from src.planner import passo4_compras_mp
    from src.domain import PlanoProducao

    planos_prod = [
        PlanoProducao(rodada=2, fabrica="F1", dia=2, pa="PA1", qtd=10000),
        PlanoProducao(rodada=2, fabrica="F1", dia=3, pa="PA2", qtd=20000),
    ]
    estoque_inicial = {"MP1": 0.0, "MP2": 0.0, "MP3": 0.0}
    cap_mp = {"MP1": 127 * 2 * 0.5, "MP2": 36 * 2 * 0.7, "MP3": 42 * 2 * 0.9}
    tarefas, descartadas = passo4_compras_mp(
        planos_prod, estoque_inicial, cfg, cap_mp,
        rodada_n=2, fabrica_cidade="Joinville", transit_atual=[],
    )
    mps = {t.item for t in tarefas}
    assert "MP1" in mps and "MP2" in mps and "MP3" in mps
    for t in tarefas:
        assert t.origem_tipo == "Fornecedor"
```

Run: `pytest tests/test_planner.py::test_passo4_gera_compras -v`
Expected: FAIL.

- [ ] **Step 12.2: Implementar `passo4_compras_mp`**

```python
def passo4_compras_mp(
    planos_prod: List[PlanoProducao],
    estoque_inicial_mp: Dict[str, float],
    cfg: Config,
    cap_mp: Dict[str, float],
    rodada_n: int,
    fabrica_cidade: str,
    transit_atual: List[TransitItem],
) -> Tuple[List[TarefaTransporte], List[OPDescartada]]:
    consumo: Dict[int, Dict[str, float]] = {
        d: {"MP1": 0.0, "MP2": 0.0, "MP3": 0.0} for d in range(1, 6)
    }
    for p in planos_prod:
        for mp in ("MP1", "MP2", "MP3"):
            g = cfg.BoM[p.pa][mp]
            consumo[p.dia][mp] += p.qtd * g / 1_000_000

    chegadas_pre: Dict[int, Dict[str, float]] = {
        d: {"MP1": 0.0, "MP2": 0.0, "MP3": 0.0} for d in range(1, 6)
    }
    for t in transit_atual:
        if t.rod_cheg == rodada_n and t.item.startswith("MP") and t.destino_tipo == "Fábrica":
            chegadas_pre[t.dia_cheg][t.item] = chegadas_pre[t.dia_cheg].get(t.item, 0.0) + t.qtd

    tarefas: List[TarefaTransporte] = []
    descartadas: List[OPDescartada] = []

    for mp in ("MP1", "MP2", "MP3"):
        fornecedor, _custo = min(cfg.fornecedores[mp], key=lambda x: x[1])
        lt_min = _lead_time_dias(cfg, fornecedor, fabrica_cidade, "Caminhão")
        if lt_min == math.inf:
            continue

        estoque_atual = estoque_inicial_mp.get(mp, 0.0)
        for dia in range(1, 6):
            estoque_atual += chegadas_pre[dia][mp]
            falta = consumo[dia][mp] - estoque_atual
            if falta > 1e-6:
                dia_partida_raw = dia - int(lt_min)
                if dia_partida_raw < 1:
                    # Lead time maior que a janela da rodada: registra warning, mas envia
                    # ASAP (dia 1). A chegada cai em rodada N+k, alimentando producao futura.
                    descartadas.append(OPDescartada(
                        op=OP(rodada=rodada_n, cidade=fornecedor, pa=mp,
                              qtd=int(math.ceil(falta * 1000)), dia_entrega=dia),
                        motivo="lead_time_inviavel_mp",
                        rodada_descarte=rodada_n,
                    ))
                    dia_partida = 1
                else:
                    dia_partida = dia_partida_raw
                qtd_compra = min(falta, cap_mp[mp] - estoque_atual)
                if qtd_compra <= 0:
                    descartadas.append(OPDescartada(
                        op=OP(rodada=rodada_n, cidade=fornecedor, pa=mp,
                              qtd=int(math.ceil(falta * 1000)), dia_entrega=dia),
                        motivo="cap_mp_excedida",
                        rodada_descarte=rodada_n,
                    ))
                    estoque_atual -= consumo[dia][mp]
                    continue
                tarefas.append(TarefaTransporte(
                    origem_cidade=fornecedor, destino_cidade=fabrica_cidade,
                    item=mp, qtd=qtd_compra, janela_dias=[dia_partida],
                    rodada=rodada_n, motivo=f"compra_{mp}_d{dia}",
                    origem_tipo="Fornecedor", destino_tipo="Fábrica",
                ))
                estoque_atual += qtd_compra
            estoque_atual -= consumo[dia][mp]
    return tarefas, descartadas
```

- [ ] **Step 12.3: Rodar testes**

Run: `pytest tests/test_planner.py -v`
Expected: PASS.

- [ ] **Step 12.4: Commit**

```bash
git add src/planner.py tests/test_planner.py
git commit -m "feat(planner): Passo 4 - compras MP just-in-time com simulador dia"
```

---

## Task 13: LP modal — MILP completo

**Files:**
- Create: `src/lp_modal.py`
- Create: `tests/test_lp_modal.py`

> **Atenção:** o MILP precisa de uma binária auxiliar `used[i,m,d]` (1 sse `n≥1`). Sem ela, a restrição inferior `x ≥ (n-1)*cap + ε` quando `n=0` exige `x ≥ -cap+ε` (sempre verdade), mas para `n≥1` precisamos da implicação correta. Usamos: `n ≤ M·used`, `n ≥ used`, e `x ≥ (n-1)*cap + ε - cap*(1-used)`.

- [ ] **Step 13.1: Teste**

```python
import pytest
from pathlib import Path
from src.config import Config
from src.domain import TarefaTransporte
from src.lp_modal import otimizar_modal

BASE = Path(__file__).resolve().parents[1]


@pytest.fixture(scope="module")
def cfg():
    return Config.load(BASE)


def test_otimiza_2_tarefas(cfg):
    tarefas = [
        TarefaTransporte(origem_cidade="Joinville", destino_cidade="Santos",
                         item="PA1", qtd=80000, janela_dias=[2, 3, 4],
                         rodada=2, motivo="reposição_CD2_PA1",
                         origem_tipo="Fábrica", destino_tipo="CD"),
        TarefaTransporte(origem_cidade="Manaus", destino_cidade="Joinville",
                         item="MP1", qtd=24.0, janela_dias=[1, 2, 3, 4, 5],
                         rodada=2, motivo="compra_MP1",
                         origem_tipo="Fornecedor", destino_tipo="Fábrica"),
    ]
    planos = otimizar_modal(tarefas, cfg, rodada_n=2)
    assert len(planos) >= 2
    for p in planos:
        cap = cfg.cap_modal_por_item[p.modal][p.item]
        assert p.qtd <= cap + 1e-3


def test_janela_unica_respeita(cfg):
    tarefas = [
        TarefaTransporte(origem_cidade="Joinville", destino_cidade="Santos",
                         item="PA1", qtd=10000, janela_dias=[3],
                         rodada=2, motivo="reposição_CD2_PA1_d3",
                         origem_tipo="Fábrica", destino_tipo="CD"),
    ]
    planos = otimizar_modal(tarefas, cfg, rodada_n=2)
    assert all(p.dia_coleta == 3 for p in planos)
```

Run: `pytest tests/test_lp_modal.py -v`
Expected: FAIL.

- [ ] **Step 13.2: Escrever `src/lp_modal.py`**

```python
"""MILP de alocação modal (PuLP + CBC)."""
from __future__ import annotations
from pathlib import Path
from typing import List

import pulp

from src.config import Config
from src.domain import PlanoTransporte, TarefaTransporte


def otimizar_modal(
    tarefas: List[TarefaTransporte],
    cfg: Config,
    rodada_n: int,
    max_transportes: int = 220,
    time_limit_s: int = 30,
) -> List[PlanoTransporte]:
    if not tarefas:
        return []

    prob = pulp.LpProblem("modal_alloc", pulp.LpMinimize)
    modais = ("Avião", "Caminhão", "Navio")

    x = {}
    n = {}
    o80 = {}
    xl_lo = {}
    used = {}
    pares_ativos = []

    for i, t in enumerate(tarefas):
        for m in modais:
            if m == "Navio" and (t.origem_cidade, t.destino_cidade) not in cfg.rotas_navio_validas:
                continue
            try:
                km = float(cfg.distancias[m].at[t.origem_cidade, t.destino_cidade])
            except Exception:
                continue
            if not (km and km > 0):
                continue
            cap = cfg.cap_modal_por_item[m][t.item]
            if cap <= 0:
                continue
            for d in t.janela_dias:
                key = (i, m, d)
                pares_ativos.append(key)
                x[key]    = pulp.LpVariable(f"x_{i}_{m}_{d}", lowBound=0)
                n[key]    = pulp.LpVariable(f"n_{i}_{m}_{d}", lowBound=0, cat=pulp.LpInteger)
                o80[key]  = pulp.LpVariable(f"o80_{i}_{m}_{d}", cat=pulp.LpBinary)
                xl_lo[key] = pulp.LpVariable(f"xllo_{i}_{m}_{d}", lowBound=0)
                used[key] = pulp.LpVariable(f"used_{i}_{m}_{d}", cat=pulp.LpBinary)

    if not pares_ativos:
        return []

    # objetivo
    custo_terms = []
    for (i, m, d) in pares_ativos:
        t = tarefas[i]
        km = float(cfg.distancias[m].at[t.origem_cidade, t.destino_cidade])
        peso = cfg.peso_un_ton.get(t.item, 1.0) if t.item.startswith("PA") else 1.0
        custo_terms.append(cfg.frete_viagem[m] * km * (n[(i,m,d)] - used[(i,m,d)]))  # n-used cheias
        custo_terms.append(cfg.frete_viagem[m] * km * o80[(i,m,d)])                   # última ≥80%
        custo_terms.append(0.5 * cfg.frete_viagem[m] * km * (used[(i,m,d)] - o80[(i,m,d)]))  # última <80% (parcela fixa)
        custo_terms.append(cfg.frete_peso[m] * km * peso * xl_lo[(i,m,d)])           # última <80% (parcela peso)
        custo_terms.append(cfg.doc_modal[m] * n[(i,m,d)])
    prob += pulp.lpSum(custo_terms)

    # 1) Conservação por tarefa
    for i, t in enumerate(tarefas):
        soma = [x[(j, m, d)] for (j, m, d) in pares_ativos if j == i]
        if soma:
            prob += pulp.lpSum(soma) == t.qtd, f"conserv_{i}"

    # 2) Cap, used, cota inferior, acoplamento o80
    BIG_N = 50  # cota superior para n (220 transportes / 1 viagem cheia já está coberto)
    for (i, m, d) in pares_ativos:
        t = tarefas[i]
        cap = cfg.cap_modal_por_item[m][t.item]
        eps = 1.0 if t.item.startswith("PA") else 0.01
        # used = 1 sse n ≥ 1
        prob += n[(i,m,d)] <= BIG_N * used[(i,m,d)], f"used_up_{i}_{m}_{d}"
        prob += n[(i,m,d)] >= used[(i,m,d)], f"used_lo_{i}_{m}_{d}"
        # cap
        prob += x[(i,m,d)] <= n[(i,m,d)] * cap, f"upper_{i}_{m}_{d}"
        # cota inferior só quando used=1
        prob += x[(i,m,d)] >= (n[(i,m,d)] - 1) * cap + eps - cap * (1 - used[(i,m,d)]), f"lower_{i}_{m}_{d}"
        # se o80=1, x_last ≥ 0.8*cap
        prob += x[(i,m,d)] - (n[(i,m,d)] - 1) * cap >= 0.8 * cap * o80[(i,m,d)] - cap * (1 - used[(i,m,d)]), f"o80_lo_{i}_{m}_{d}"
        # se o80=0, x_last < 0.8*cap (implicador inverso)
        prob += x[(i,m,d)] - (n[(i,m,d)] - 1) * cap <= 0.8 * cap - eps + cap * o80[(i,m,d)] + cap * (1 - used[(i,m,d)]), f"o80_hi_{i}_{m}_{d}"
        # o80 só faz sentido se used=1
        prob += o80[(i,m,d)] <= used[(i,m,d)], f"o80_used_{i}_{m}_{d}"
        # xl_lo = (x - (n-1)*cap) * (1 - o80) via big-M
        prob += xl_lo[(i,m,d)] <= x[(i,m,d)] - (n[(i,m,d)] - 1) * cap + cap * (1 - used[(i,m,d)]), f"xllo1_{i}_{m}_{d}"
        prob += xl_lo[(i,m,d)] <= cap * (1 - o80[(i,m,d)]), f"xllo2_{i}_{m}_{d}"
        prob += xl_lo[(i,m,d)] >= (x[(i,m,d)] - (n[(i,m,d)] - 1) * cap) - cap * o80[(i,m,d)] - cap * (1 - used[(i,m,d)]), f"xllo3_{i}_{m}_{d}"

    # 3) Limite semanal
    prob += pulp.lpSum([n[(i,m,d)] for (i,m,d) in pares_ativos]) <= max_transportes, "max_220"

    # PuLP 3.x removeu tmpDir do PULP_CBC_CMD — usa o tempdir do sistema.
    solver = pulp.PULP_CBC_CMD(timeLimit=time_limit_s, msg=False)
    prob.solve(solver)

    planos: List[PlanoTransporte] = []
    for (i, m, d) in pares_ativos:
        n_val = int(round(pulp.value(n[(i,m,d)]) or 0))
        x_val = float(pulp.value(x[(i,m,d)]) or 0)
        if n_val == 0:
            continue
        t = tarefas[i]
        cap = cfg.cap_modal_por_item[m][t.item]
        for _ in range(n_val - 1):
            planos.append(PlanoTransporte(
                rodada=rodada_n, origem_tipo=t.origem_tipo, origem_cidade=t.origem_cidade,
                dia_coleta=d, modal=m, item=t.item, qtd=cap,
                destino_tipo=t.destino_tipo, destino_cidade=t.destino_cidade,
            ))
        x_last = x_val - (n_val - 1) * cap
        if x_last > 1e-3:
            planos.append(PlanoTransporte(
                rodada=rodada_n, origem_tipo=t.origem_tipo, origem_cidade=t.origem_cidade,
                dia_coleta=d, modal=m, item=t.item, qtd=x_last,
                destino_tipo=t.destino_tipo, destino_cidade=t.destino_cidade,
            ))
    return planos
```

- [ ] **Step 13.3: Rodar testes**

Run: `pytest tests/test_lp_modal.py -v`
Expected: PASS. CBC pode demorar 2-15s.

- [ ] **Step 13.4: Commit**

```bash
git add src/lp_modal.py tests/test_lp_modal.py
git commit -m "feat(lp_modal): MILP de alocacao modal com regra >=80%/<80%"
```

---

## Task 14: Pipeline — orquestração `run_rodada`

**Files:**
- Create: `src/pipeline.py`
- Create: `tests/test_pipeline.py`

- [ ] **Step 14.1: Teste smoke E2E**

```python
import shutil
from pathlib import Path
from src.pipeline import run_rodada

BASE = Path(__file__).resolve().parents[1]


def test_run_rodada_1_smoke(tmp_path, monkeypatch):
    rodadas_src = BASE / "rodadas"
    rodadas_dst = tmp_path / "rodadas"
    rodadas_dst.mkdir()
    shutil.copy(rodadas_src / "FLAMENGO.xlsm", rodadas_dst / "FLAMENGO.xlsm")
    shutil.copy(rodadas_src / "Rodada 1.xlsm", rodadas_dst / "Rodada 1.xlsm")
    shutil.copytree(BASE / "data", tmp_path / "data")

    monkeypatch.chdir(tmp_path)

    resumo = run_rodada(rodada_n=1, rodada_xlsm_path=rodadas_dst / "Rodada 1.xlsm")
    assert "transportes" in resumo
    assert (tmp_path / "estado" / "state.json").exists()
    assert (tmp_path / "estado" / "historico_rodada_1.json").exists()
    assert (rodadas_dst / "FLAMENGO.xlsm").exists()
```

Run: `pytest tests/test_pipeline.py -v`
Expected: FAIL.

- [ ] **Step 14.2: Escrever `src/pipeline.py`**

```python
"""Orquestração: roda uma rodada completa do jogo."""
from __future__ import annotations
import math
from pathlib import Path
from typing import Any, Dict, List

import pandas as pd

from src.config import Config
from src.domain import Estado, OP, TransitItem
from src.estado import carregar_estado, salvar_estado, snapshot_rodada
from src.forecast import (
    treinar_inicial, refit, prever,
    salvar_modelos, carregar_modelos, agregar_op_para_serie,
)
from src.io_xlsm import (
    ler_instalacoes, ler_op_rodada, ler_sol_transp,
    escrever_plano, calcular_rod_dia_chegada,
)
from src.lp_modal import otimizar_modal
from src.planner import (
    passo1_entregas_cd_varejo,
    passo2_reposicao_fabrica_cd,
    passo3_producao,
    passo4_compras_mp,
)


def _construir_cidades_por_cd(cfg: Config, cds_info: Dict[str, str]) -> Dict[str, List[str]]:
    cidades_por_cd: Dict[str, List[str]] = {cd: [] for cd in cds_info}
    for cidade in cfg.ne_por_cidade:
        melhor_cd = None
        melhor_dist = float("inf")
        for cd, cidade_cd in cds_info.items():
            try:
                d = float(cfg.distancias["Caminhão"].at[cidade_cd, cidade])
            except Exception:
                continue
            if d < melhor_dist:
                melhor_dist = d
                melhor_cd = cd
        if melhor_cd:
            cidades_por_cd[melhor_cd].append(cidade)
    return cidades_por_cd


def _capacidade_pa_frascos(area_m2: float, cfg: Config, pa: str) -> int:
    ton = area_m2 * cfg.capacidades["pe_direito_deposito_m"] * cfg.densidades_pa[pa]
    return int(ton / cfg.peso_un_ton[pa])


def _aplicar_chegadas(estado: Estado, rodada_n: int, cfg: Config, instalacoes: Dict) -> Estado:
    cap_mp_F1 = {
        mp: (instalacoes["fabricas"]["F1"]["area_mp"][mp]
             * cfg.capacidades["pe_direito_deposito_m"]
             * cfg.densidades_mp[mp])
        for mp in ("MP1", "MP2", "MP3")
    }
    cap_pa_cd = {
        cd: {pa: _capacidade_pa_frascos(instalacoes["cds"][cd]["area_pa"][pa], cfg, pa)
             for pa in ("PA1", "PA2", "PA3")}
        for cd in instalacoes["cds"]
        if instalacoes["cds"][cd].get("cidade")
    }
    novos_transit = []
    for t in estado.transit:
        if t.rod_cheg > rodada_n:
            novos_transit.append(t)
            continue
        if t.item.startswith("MP") and t.destino_tipo == "Fábrica":
            atual = estado.estoque_mp_fabrica.get("F1", {}).get(t.item, 0.0)
            cap = cap_mp_F1[t.item]
            aceita = min(t.qtd, max(0.0, cap - atual))
            estado.estoque_mp_fabrica["F1"][t.item] = atual + aceita
        elif t.item.startswith("PA") and t.destino_tipo == "CD":
            cd_dest = next((cd for cd, info in instalacoes["cds"].items()
                            if info.get("cidade") == t.destino_cidade), None)
            if cd_dest is None:
                continue
            atual = estado.estoque_pa_cd[cd_dest].get(t.item, 0)
            cap = cap_pa_cd[cd_dest][t.item]
            aceita = min(int(t.qtd), max(0, cap - atual))
            estado.estoque_pa_cd[cd_dest][t.item] = atual + aceita
    estado.transit = novos_transit
    return estado


def _agregar_saidas_cd(tarefas, cds_info):
    saidas = {cd: {"PA1": 0, "PA2": 0, "PA3": 0} for cd in cds_info}
    for t in tarefas:
        for cd, cidade in cds_info.items():
            if cidade == t.origem_cidade:
                saidas[cd][t.item] = saidas[cd].get(t.item, 0) + t.qtd
                break
    return saidas


def _atualizar_estado_pos_planejamento(estado, planos_transporte, ops, descartadas, rodada_n, cfg):
    for p in planos_transporte:
        try:
            km = float(cfg.distancias[p.modal].at[p.origem_cidade, p.destino_cidade])
        except Exception:
            km = 0
        vel = {"Avião": 700, "Caminhão": 50, "Navio": 30}[p.modal]
        horas = km / vel if vel else 0
        lead = max(1, math.ceil(horas / 8))
        rc, dc = calcular_rod_dia_chegada(rodada_n, p.dia_coleta, lead)
        estado.transit.append(TransitItem(
            rod_part=rodada_n, dia_part=p.dia_coleta, rod_cheg=rc, dia_cheg=dc,
            origem_tipo=p.origem_tipo, origem_cidade=p.origem_cidade,
            destino_tipo=p.destino_tipo, destino_cidade=p.destino_cidade,
            modal=p.modal, item=p.item, qtd=p.qtd,
        ))
    for op in ops:
        if op.rodada == rodada_n:
            estado.ops_atendidas.append(op)
    estado.ops_descartadas.extend(descartadas)
    return estado


def run_rodada(rodada_n: int, rodada_xlsm_path: Path) -> Dict[str, Any]:
    base = Path.cwd()
    cfg = Config.load(base)

    estado_path = base / "estado" / "state.json"
    estado = carregar_estado(estado_path)

    instalacoes = ler_instalacoes(rodada_xlsm_path)
    cds_info = {cd: d["cidade"] for cd, d in instalacoes["cds"].items()}
    fabricas_info = {f: d["cidade"] for f, d in instalacoes["fabricas"].items()}
    fabrica_principal = "F1"
    fabrica_cidade = fabricas_info[fabrica_principal]

    op_path = base / "rodadas" / f"OP_Rodada_{rodada_n}.xlsx"
    ops = ler_op_rodada(op_path)

    # Reconstrói transit a partir do SOL_TRANSP da rodada atual (preenchido pelo prof/usuário).
    # Crucial para Rodada 1, onde a planilha já tem decisões tomadas pelo usuário e o
    # state.json ainda não existe. Para rodadas N>1, mescla com transit já em state.json
    # (dedup por chave (rod_part, dia_part, modal, item, origem→destino)).
    transit_da_planilha = ler_sol_transp(rodada_xlsm_path, rodada=rodada_n)
    chaves_existentes = {(t.rod_part, t.dia_part, t.modal, t.item,
                          t.origem_cidade, t.destino_cidade) for t in estado.transit}
    for t in transit_da_planilha:
        k = (t.rod_part, t.dia_part, t.modal, t.item, t.origem_cidade, t.destino_cidade)
        if k not in chaves_existentes:
            estado.transit.append(t)

    estado = _aplicar_chegadas(estado, rodada_n, cfg, instalacoes)

    hw_path = base / "estado" / "hw_models.json"
    hist_path = base / "estado" / "historico_demanda_ampliado.parquet"

    if not hist_path.exists():
        # Schema do data/demanda_long.parquet: ano, rodada, pa(minúsculo), cidade, qtd,
        # unique_id, ds, y. Normalizamos para o schema esperado pelo forecast:
        # periodo_global, cidade, PA, qtd.
        hist_raw = pd.read_parquet(base / "data" / "demanda_long.parquet")
        hist = pd.DataFrame({
            "periodo_global": (hist_raw["ano"] - 1) * 48 + hist_raw["rodada"],
            "cidade": hist_raw["cidade"].astype(str),
            "PA": hist_raw["pa"].astype(str),
            "qtd": hist_raw["qtd"].astype(float),
        })
        hist_path.parent.mkdir(parents=True, exist_ok=True)
        hist.to_parquet(hist_path, index=False)
    if not hw_path.exists():
        hist = pd.read_parquet(hist_path)
        modelos = treinar_inicial(hist)
        salvar_modelos(modelos, hw_path)
    else:
        modelos = carregar_modelos(hw_path)

    if ops:
        agg = agregar_op_para_serie(ops, rodada_n)
        modelos = refit(hist_path, modelos, agg, rodada_n)
        salvar_modelos(modelos, hw_path)

    forecast = prever(modelos, horizonte=4)

    cidades_por_cd = _construir_cidades_por_cd(cfg, cds_info)
    tarefas_cd_varejo, descartadas1 = passo1_entregas_cd_varejo(
        estado, ops, cfg, cds_info, rodada_n,
    )
    saidas_cd = _agregar_saidas_cd(tarefas_cd_varejo, cds_info)
    necessidades = passo2_reposicao_fabrica_cd(
        estado, forecast, cfg, cds_info, cidades_por_cd,
        saidas_cd, rodada_n, fabrica_cidade=fabrica_cidade,
    )
    planos_prod, tarefas_fab_cd = passo3_producao(
        necessidades, cfg, cds_info, rodada_n,
        fabrica=fabrica_principal, fabrica_cidade=fabrica_cidade,
        maquinas=instalacoes["fabricas"][fabrica_principal]["maquinas"],
        turnos=instalacoes["fabricas"][fabrica_principal]["turnos"],
    )
    cap_mp = {
        mp: (instalacoes["fabricas"][fabrica_principal]["area_mp"][mp]
             * cfg.capacidades["pe_direito_deposito_m"]
             * cfg.densidades_mp[mp])
        for mp in ("MP1", "MP2", "MP3")
    }
    tarefas_mp, descartadas4 = passo4_compras_mp(
        planos_prod, estado.estoque_mp_fabrica[fabrica_principal],
        cfg, cap_mp, rodada_n, fabrica_cidade, estado.transit,
    )

    tarefas_total = tarefas_cd_varejo + tarefas_fab_cd + tarefas_mp
    planos_transporte = otimizar_modal(tarefas_total, cfg, rodada_n)

    estado = _atualizar_estado_pos_planejamento(
        estado, planos_transporte, ops,
        descartadas1 + descartadas4, rodada_n, cfg,
    )

    flamengo_path = base / "rodadas" / "FLAMENGO.xlsm"
    escrever_plano(flamengo_path, planos_transporte, planos_prod, rodada_n)

    estado.rodada_atual = rodada_n
    salvar_estado(estado, estado_path)
    extras = {
        "n_transportes": len(planos_transporte),
        "n_descartadas": len(descartadas1) + len(descartadas4),
        "n_atendidas": len(tarefas_cd_varejo),
        "ocupacao_cd": {cd: estado.estoque_pa_cd[cd] for cd in cds_info},
    }
    snapshot_rodada(estado, rodada_n, extras, base / "estado")
    return {
        "rodada": rodada_n,
        "transportes": len(planos_transporte),
        "producao_total": sum(p.qtd for p in planos_prod),
        "ops_atendidas": len(tarefas_cd_varejo),
        "ops_descartadas": len(descartadas1) + len(descartadas4),
    }
```

- [ ] **Step 14.3: Rodar testes**

Run: `pytest tests/test_pipeline.py -v`
Expected: PASS (smoke E2E). Pode demorar 30-60s (treino HW + CBC).

- [ ] **Step 14.4: Commit**

```bash
git add src/pipeline.py tests/test_pipeline.py
git commit -m "feat(pipeline): orquestracao run_rodada(N, path) E2E"
```

---

## Task 15: Dashboard

**Files:**
- Create: `src/dashboard.py`
- Create: `tests/test_dashboard.py`

- [ ] **Step 15.1: Teste**

```python
import json
from pathlib import Path
from src.dashboard import ler_snapshots, tabela_resumo


def test_ler_snapshots_vazio(tmp_path):
    rows = ler_snapshots(tmp_path)
    assert rows == []


def test_ler_snapshots_com_arquivo(tmp_path):
    (tmp_path / "historico_rodada_1.json").write_text(json.dumps({
        "rodada": 1,
        "estado": {
            "rodada_atual": 1,
            "estoque_mp_fabrica": {"F1": {"MP1": 50.0, "MP2": 0.0, "MP3": 0.0}},
            "estoque_pa_cd": {"CD1": {"PA1": 100, "PA2": 0, "PA3": 0},
                              "CD2": {"PA1": 200, "PA2": 0, "PA3": 0}},
        },
        "extras": {"n_transportes": 5, "n_atendidas": 3, "n_descartadas": 0},
    }), encoding="utf-8")
    rows = ler_snapshots(tmp_path)
    assert len(rows) == 1
    df = tabela_resumo(rows)
    assert df.loc[0, "transportes"] == 5
    assert df.loc[0, "estoque_pa1_cd1"] == 100
```

Run: `pytest tests/test_dashboard.py -v`
Expected: FAIL.

- [ ] **Step 15.2: Escrever `src/dashboard.py`**

```python
"""Lê snapshots de rodada e gera plots/tabela."""
from __future__ import annotations
import json
from pathlib import Path
from typing import Any, Dict, List

import matplotlib.pyplot as plt
import pandas as pd


def ler_snapshots(dir_path: Path) -> List[Dict[str, Any]]:
    dir_path = Path(dir_path)
    if not dir_path.exists():
        return []
    return [json.loads(f.read_text(encoding="utf-8"))
            for f in sorted(dir_path.glob("historico_rodada_*.json"))]


def tabela_resumo(snaps: List[Dict[str, Any]]) -> pd.DataFrame:
    rows = []
    for s in snaps:
        e = s["estado"]
        ex = s.get("extras", {})
        rows.append({
            "rodada": s["rodada"],
            "transportes": ex.get("n_transportes", 0),
            "ops_atendidas": ex.get("n_atendidas", 0),
            "ops_descartadas": ex.get("n_descartadas", 0),
            "estoque_mp1_F1": e.get("estoque_mp_fabrica", {}).get("F1", {}).get("MP1", 0),
            "estoque_mp2_F1": e.get("estoque_mp_fabrica", {}).get("F1", {}).get("MP2", 0),
            "estoque_mp3_F1": e.get("estoque_mp_fabrica", {}).get("F1", {}).get("MP3", 0),
            "estoque_pa1_cd1": e.get("estoque_pa_cd", {}).get("CD1", {}).get("PA1", 0),
            "estoque_pa1_cd2": e.get("estoque_pa_cd", {}).get("CD2", {}).get("PA1", 0),
            "estoque_pa2_cd1": e.get("estoque_pa_cd", {}).get("CD1", {}).get("PA2", 0),
            "estoque_pa2_cd2": e.get("estoque_pa_cd", {}).get("CD2", {}).get("PA2", 0),
            "estoque_pa3_cd1": e.get("estoque_pa_cd", {}).get("CD1", {}).get("PA3", 0),
            "estoque_pa3_cd2": e.get("estoque_pa_cd", {}).get("CD2", {}).get("PA3", 0),
        })
    return pd.DataFrame(rows)


def plot_historico(dir_path: Path) -> None:
    snaps = ler_snapshots(dir_path)
    if not snaps:
        print("Sem histórico ainda.")
        return
    df = tabela_resumo(snaps)
    fig, axes = plt.subplots(2, 3, figsize=(15, 8))
    ax = axes[0, 0]
    ax.plot(df["rodada"], df["estoque_mp1_F1"], label="MP1")
    ax.plot(df["rodada"], df["estoque_mp2_F1"], label="MP2")
    ax.plot(df["rodada"], df["estoque_mp3_F1"], label="MP3")
    ax.set_title("Estoque MP em F1 (ton)"); ax.legend(); ax.set_xlabel("Rodada")

    ax = axes[0, 1]
    ax.plot(df["rodada"], df["estoque_pa1_cd1"], label="CD1")
    ax.plot(df["rodada"], df["estoque_pa1_cd2"], label="CD2")
    ax.set_title("Estoque PA1 nos CDs"); ax.legend(); ax.set_xlabel("Rodada")

    ax = axes[0, 2]
    ax.plot(df["rodada"], df["transportes"])
    ax.set_title("Nº transportes na rodada"); ax.set_xlabel("Rodada")

    ax = axes[1, 0]
    ax.plot(df["rodada"], df["ops_atendidas"], label="atendidas")
    ax.plot(df["rodada"], df["ops_descartadas"], label="descartadas")
    ax.set_title("OPs"); ax.legend(); ax.set_xlabel("Rodada")

    ax = axes[1, 1]
    ax.plot(df["rodada"], df["estoque_pa2_cd1"], label="CD1")
    ax.plot(df["rodada"], df["estoque_pa2_cd2"], label="CD2")
    ax.set_title("Estoque PA2 nos CDs"); ax.legend(); ax.set_xlabel("Rodada")

    ax = axes[1, 2]
    ax.plot(df["rodada"], df["estoque_pa3_cd1"], label="CD1")
    ax.plot(df["rodada"], df["estoque_pa3_cd2"], label="CD2")
    ax.set_title("Estoque PA3 nos CDs"); ax.legend(); ax.set_xlabel("Rodada")

    plt.tight_layout()
    plt.show()
    print(df.to_string(index=False))
```

- [ ] **Step 15.3: Rodar testes**

Run: `pytest tests/test_dashboard.py -v`
Expected: PASS.

- [ ] **Step 15.4: Commit**

```bash
git add src/dashboard.py tests/test_dashboard.py
git commit -m "feat(dashboard): leitura snapshots + plots resumidos"
```

---

## Task 16: Notebook `jogo/rodada.ipynb`

**Files:**
- Create: `scripts/criar_notebook.py`
- Create (gerado): `jogo/rodada.ipynb`

- [ ] **Step 16.1: Script gerador `scripts/criar_notebook.py`**

```python
"""Cria jogo/rodada.ipynb. Executar uma vez no setup."""
from pathlib import Path
import nbformat as nbf

nb = nbf.v4.new_notebook()
cells = [
    nbf.v4.new_markdown_cell("# Jogo PCP 2 — FLAMENGO\nRodada a rodada, prepara `FLAMENGO.xlsm`."),
    nbf.v4.new_code_cell(
        "import sys\n"
        "from pathlib import Path\n"
        "BASE = Path('..').resolve()\n"
        "sys.path.insert(0, str(BASE))\n"
        "from src.pipeline import run_rodada\n"
        "from src.dashboard import plot_historico, tabela_resumo, ler_snapshots"
    ),
    nbf.v4.new_markdown_cell("## Configurar rodada"),
    nbf.v4.new_code_cell(
        "RODADA = 2\n"
        "RODADA_PATH = BASE / 'rodadas' / f'Rodada {RODADA}.xlsm'\n"
        "assert RODADA_PATH.exists(), f'Arquivo nao encontrado: {RODADA_PATH}'"
    ),
    nbf.v4.new_markdown_cell("## Rodar pipeline"),
    nbf.v4.new_code_cell(
        "import os, json\n"
        "os.chdir(BASE)\n"
        "resumo = run_rodada(RODADA, RODADA_PATH)\n"
        "print(json.dumps(resumo, indent=2, ensure_ascii=False))"
    ),
    nbf.v4.new_markdown_cell("## Dashboard histórico"),
    nbf.v4.new_code_cell("plot_historico(BASE / 'estado')"),
    nbf.v4.new_markdown_cell("## Inspeção manual do que foi escrito"),
    nbf.v4.new_code_cell(
        "import pandas as pd\n"
        "df = pd.read_excel(BASE / 'rodadas/FLAMENGO.xlsm', sheet_name='SOL_TRANSP', skiprows=3)\n"
        "df[df['Rodada'] == f'Rodada_{RODADA}']"
    ),
]
nb["cells"] = cells

out = Path("jogo/rodada.ipynb")
out.parent.mkdir(parents=True, exist_ok=True)
nbf.write(nb, str(out))
print(f"Notebook criado em {out}")
```

- [ ] **Step 16.2: Executar o script**

```bash
python scripts/criar_notebook.py
```

Expected: `jogo/rodada.ipynb` criado.

- [ ] **Step 16.3: Abrir no Jupyter para sanity check**

```bash
jupyter notebook jogo/rodada.ipynb
```

Conferir visualmente que as 6 células aparecem. Fechar sem rodar.

- [ ] **Step 16.4: Commit**

```bash
git add scripts/criar_notebook.py jogo/rodada.ipynb
git commit -m "feat(notebook): rodada.ipynb com 6 celulas de fluxo"
```

---

## Task 17: Smoke test E2E manual

**Files:** nenhum (verificação manual).

- [ ] **Step 17.1: Limpar estado e rodar Rodada 1**

```powershell
Remove-Item -Recurse -Force estado
New-Item -ItemType Directory -Force estado
python -c "from src.pipeline import run_rodada; from pathlib import Path; r = run_rodada(1, Path('rodadas/Rodada 1.xlsm')); print(r)"
```

Expected:
- `estado/state.json`, `estado/historico_rodada_1.json`, `estado/hw_models.json`, `estado/historico_demanda_ampliado.parquet` criados.
- `rodadas/FLAMENGO.xlsm` ganhou linhas em SOL_TRANSP da Rodada_1.
- Sem exceção.

- [ ] **Step 17.2: Criar OP_Rodada_2.xlsx fake e rodar Rodada 2**

```powershell
python -c "import pandas as pd; pd.DataFrame([{'Rodada':2,'Cidade':'São Paulo','PA':'PA1','Qtd':50000,'Dia_Entrega':5}]).to_excel('rodadas/OP_Rodada_2.xlsx', index=False)"
Copy-Item 'rodadas/Rodada 1.xlsm' 'rodadas/Rodada 2.xlsm'
python -c "from src.pipeline import run_rodada; from pathlib import Path; print(run_rodada(2, Path('rodadas/Rodada 2.xlsm')))"
```

Expected:
- Linhas com `Rodada_2` aparecem em `SOL_TRANSP`.
- `historico_rodada_2.json` gerado.
- Sem exceção.

- [ ] **Step 17.3: Abrir FLAMENGO.xlsm no Excel real**

Conferir:
- VBA continua presente (Alt+F11).
- Fórmulas das colunas J-Z calculam (sem `#REF!`).
- Aba `OP_FABRICAS` mostra valores numéricos no bloco F1.

- [ ] **Step 17.4: Rodar dashboard**

```bash
jupyter notebook jogo/rodada.ipynb
```

Executar todas as células. Conferir que os plots aparecem e a tabela resumo está populada com 2 linhas (rodada 1 e 2).

- [ ] **Step 17.5: Commit final**

```bash
git add -A
git commit -m "chore: smoke test E2E manual OK (Rodada 1 e 2)"
```

---

## Notas finais

- Cada Task é independente e termina com **testes verdes** no módulo correspondente.
- Ordem importa: Task N+1 assume Task N completa.
- Se um teste falhar, **não** mascarar com `try/except` — investigar e ajustar a implementação. Tests-first.
- Use `@superpowers:subagent-driven-development` ou `@superpowers:executing-plans` para executar.
- Após terminar todas as Tasks, criar a OP real da Rodada 2 (quando vier) e iterar.
