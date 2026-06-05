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
    """Grid search com holdout das últimas 8 observações.

    Testa combinações de (trend, seasonal, damped, seasonal_periods) e escolhe
    a com menor RMSE no holdout. Se a série for muito curta (<24 pontos), cai
    direto pro Holt simples.
    """
    n = len(valores)
    if n < 24:
        return _fit_holt_simples(valores)

    holdout = min(8, max(2, n // 12))
    treino = valores[:-holdout]
    teste = valores[-holdout:]

    # Espaço de busca
    candidatos = []
    for trend in ("add", None):
        for damped in (True, False) if trend == "add" else (False,):
            for seasonal, sp in (("add", 48), ("add", 12), (None, None)):
                if seasonal is not None and len(treino) < 2 * sp:
                    continue
                candidatos.append((trend, damped, seasonal, sp))

    melhor = None
    melhor_rmse = float("inf")
    melhor_fit = None

    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        for trend, damped, seasonal, sp in candidatos:
            try:
                kwargs = dict(trend=trend, initialization_method="estimated")
                if trend == "add":
                    kwargs["damped_trend"] = damped
                if seasonal is not None:
                    kwargs["seasonal"] = seasonal
                    kwargs["seasonal_periods"] = sp
                model = ExponentialSmoothing(treino, **kwargs)
                fit = model.fit(optimized=True)
                pred = fit.forecast(holdout)
                rmse = float(np.sqrt(np.mean((pred - teste) ** 2)))
                if rmse < melhor_rmse:
                    melhor_rmse = rmse
                    melhor = (trend, damped, seasonal, sp)
                    melhor_fit = fit
            except Exception:
                continue

    if melhor is None:
        return _fit_holt_simples(valores)

    # Refita na série completa com a config vencedora
    trend, damped, seasonal, sp = melhor
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        kwargs = dict(trend=trend, initialization_method="estimated")
        if trend == "add":
            kwargs["damped_trend"] = damped
        if seasonal is not None:
            kwargs["seasonal"] = seasonal
            kwargs["seasonal_periods"] = sp
        fit_final = ExponentialSmoothing(valores, **kwargs).fit(optimized=True)
        rmse_in = float(np.sqrt(np.mean((fit_final.fittedvalues - valores) ** 2)))

    tipo = f"HW_{trend or 'none'}_{seasonal or 'none'}_sp{sp or 0}_d{int(damped)}"
    return {
        "tipo": tipo,
        "config": {"trend": trend, "seasonal": seasonal,
                   "seasonal_periods": sp, "damped": damped},
        "ultimo_periodo_treino": len(valores),
        "ultimo_valor": float(valores[-1]),
        "ultimo_nivel": float(fit_final.level[-1]) if hasattr(fit_final, "level") and len(fit_final.level) else float(np.mean(valores[-8:])),
        "ultimo_trend": float(fit_final.trend[-1]) if hasattr(fit_final, "trend") and len(fit_final.trend) else 0.0,
        "season_final": [float(x) for x in fit_final.season[-sp:]] if (seasonal is not None and hasattr(fit_final, "season") and len(fit_final.season) >= sp) else [],
        "seasonal_periods_final": sp if seasonal else 0,
        "rmse_in_sample": rmse_in,
        "rmse_holdout": melhor_rmse,
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
        season = info.get("season_final", [])
        sp = info.get("seasonal_periods_final", 0)
        if season and sp > 0:
            for h in range(1, horizonte + 1):
                s_idx = (info["ultimo_periodo_treino"] + h - 1) % sp
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


def refit(
    historico_path: Path,
    modelos_atuais: Dict[Tuple[str, str], Dict],
    ops_da_rodada: Dict[Tuple[str, str], float],
    rodada_n: int,
) -> Dict[Tuple[str, str], Dict]:
    historico_path = Path(historico_path)
    df = pd.read_parquet(historico_path)

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
