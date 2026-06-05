"""Gerador de OPs mock realistas usando previsão Holt-Winters.

Útil para testar o pipeline antes do professor entregar a OP real.
Usa o forecast HW (treinado no histórico real de 96 períodos) para
gerar quantidades plausíveis por (cidade, PA), e sorteia o dia de entrega.
"""
from __future__ import annotations
import math
import random
from pathlib import Path
from typing import Dict, List

import pandas as pd

from src.forecast import (
    treinar_inicial, prever, salvar_modelos, carregar_modelos,
)


def gerar_ops_mock(
    rodada_n: int,
    base_dir: Path | None = None,
    cidades: List[str] | None = None,
    pas: tuple = ("PA1", "PA2", "PA3"),
    seed: int = 42,
    ruido_pct: float = 0.10,
) -> List[Dict]:
    """Gera lista de OPs mock baseada na previsão HW para a rodada N.

    Args:
        rodada_n: rodada-alvo da previsão (N=2,3,...).
        base_dir: raiz do projeto (default: cwd).
        cidades: lista de cidades a gerar OP. Default: todas 25.
        pas: tuple de PAs.
        seed: semente do random pra reprodutibilidade.
        ruido_pct: ruído aplicado em cima do forecast (±%).

    Returns:
        Lista de dicts no formato `OPS = [{'cidade', 'pa', 'qtd', 'dia_entrega'}, ...]`.
    """
    base_dir = Path(base_dir) if base_dir else Path.cwd()
    hw_path = base_dir / "estado" / "hw_models.json"
    hist_path = base_dir / "estado" / "historico_demanda_ampliado.parquet"

    # Garante que há histórico ampliado e modelos
    if not hist_path.exists():
        hist_raw = pd.read_parquet(base_dir / "data" / "demanda_long.parquet")
        hist = pd.DataFrame({
            "periodo_global": (hist_raw["ano"] - 1) * 48 + hist_raw["rodada"],
            "cidade": hist_raw["cidade"].astype(str),
            "PA": hist_raw["pa"].astype(str),
            "qtd": hist_raw["qtd"].astype(float),
        })
        hist_path.parent.mkdir(parents=True, exist_ok=True)
        hist.to_parquet(hist_path, index=False)

    if not hw_path.exists():
        print("Treinando HW inicial (primeira vez, ~30s)...")
        hist = pd.read_parquet(hist_path)
        modelos = treinar_inicial(hist)
        salvar_modelos(modelos, hw_path)
    else:
        modelos = carregar_modelos(hw_path)

    # Previsão: horizonte rodada_n - 1 (porque a rodada 1 não conta como ponto histórico).
    # idx 0 = previsão pra próximo período após o histórico.
    horizonte = max(1, rodada_n - 1)
    forecast = prever(modelos, horizonte=horizonte)

    if cidades is None:
        # pega todas as cidades únicas dos modelos
        cidades = sorted({c for c, _ in modelos.keys()})

    rng = random.Random(seed)
    ops: List[Dict] = []
    for cidade in cidades:
        for pa in pas:
            chave = (cidade, pa)
            if chave not in forecast:
                continue
            previsao_total = forecast[chave][-1]  # último período do horizonte
            if previsao_total <= 0:
                continue
            # ruído aleatório ±ruido_pct
            ruido = rng.uniform(1 - ruido_pct, 1 + ruido_pct)
            qtd = int(previsao_total * ruido)
            if qtd < 100:
                continue
            # dia de entrega: distribui realisticamente entre dias 2-5
            # (dia 1 é raro; cidades mais distantes pedem com mais antecedência)
            dia_entrega = rng.choices([2, 3, 4, 5], weights=[10, 25, 30, 35])[0]
            ops.append({
                "cidade": cidade,
                "pa": pa,
                "qtd": qtd,
                "dia_entrega": dia_entrega,
            })
    return ops


def gerar_precos_mock(
    base_dir: Path | None = None,
    variacao_pct: float = 0.05,
    seed: int = 42,
) -> Dict[str, float]:
    """Gera preços de mercado mock — variação aleatória em torno do preço de referência.

    Args:
        variacao_pct: variação ±% em torno do preço de referência.
        seed: semente.

    Returns:
        Dict {'PA1': preco, 'PA2': preco, 'PA3': preco}.
    """
    base_dir = Path(base_dir) if base_dir else Path.cwd()
    import json
    params = json.loads((base_dir / "data" / "parametros.json").read_text(encoding="utf-8"))
    ref = params["preco_referencia"]

    rng = random.Random(seed)
    return {
        pa: round(ref[pa] * rng.uniform(1 - variacao_pct, 1 + variacao_pct), 2)
        for pa in ("PA1", "PA2", "PA3")
    }
