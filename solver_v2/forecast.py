"""Previsão de demanda — Holt-Winters de SÉRIE DENSA por produto (solver_v2).

Ideia (do briefing com o usuário):
  - Cada rodada do jogo pede UM produto. Seguir o calendário gera muitos zeros.
  - Em vez disso, montamos uma SÉRIE DENSA por produto: o histórico daquele
    produto (96 semanas, sem zeros) + as rodadas REAIS do jogo onde ele apareceu.
  - HW (auto-tunável) prevê a PRÓXIMA OCORRÊNCIA de cada produto.
  - Share = 100% (a carteira real ≈ a previsão nacional — validado R2/R3/R4).
  - De-viés ×1,05 (o HW subestima ~5% em média).
  - A cada rodada nova, anexa o realizado e re-tuna → previsão melhora sozinha.

Saída de `prever_proximas`: {pa: {cidade: [v_proxima, v_proxima+1, ...]}}.
Cada v é a demanda (frascos) de uma RODADA CHEIA daquele produto, por cidade.
"""
from __future__ import annotations
import warnings
from pathlib import Path
from typing import Dict, List

import numpy as np
import pandas as pd

warnings.filterwarnings("ignore")
from statsmodels.tsa.holtwinters import ExponentialSmoothing

BASE = Path(__file__).resolve().parent.parent
PAS = ("PA1", "PA2", "PA3")
SHARE = 1.0      # 100% — validado: carteira real ≈ previsão nacional
DEBIAS = 1.05    # HW subestima ~5% (razões R2/R3/R4: 0,99 / 1,06 / 1,06)


# ----- Rodadas REAIS do jogo (carteira Flamengo), por cidade -----
# R2 = PA1 (RODADA_02_PA1.pdf), R3 = PA3 (ops_r3), R4 = PA3 (ops_r4).
_R2_PA1 = {
    "Belém": 6009, "Belo Horizonte": 33385, "Brasília": 25595, "Campinas": 26708,
    "Campo Grande": 5119, "Cuiabá": 6143, "Curitiba": 22524, "Fortaleza": 20432,
    "Goiânia": 14333, "João Pessoa": 12019, "Joinville": 6143, "Maceió": 12019,
    "Manaus": 6009, "Natal": 12019, "Porto Alegre": 22524, "Recife": 18028,
    "Ribeirão Preto": 22257, "Rio de Janeiro": 44513, "Salvador": 24037,
    "Santos": 22257, "São Luís": 6009, "São Paulo": 55642, "Uberlândia": 11128,
    "Vitória": 6677, "Vitória da Conquista": 3606,
}
_R3_PA3 = {
    "Belém": 20155, "Belo Horizonte": 70544, "Brasília": 117573, "Campinas": 56435,
    "Campo Grande": 23515, "Cuiabá": 28218, "Curitiba": 103464, "Fortaleza": 68528,
    "Goiânia": 65841, "João Pessoa": 40311, "Joinville": 28218, "Maceió": 40311,
    "Manaus": 20155, "Natal": 40311, "Porto Alegre": 103464, "Recife": 60466,
    "Ribeirão Preto": 47029, "Rio de Janeiro": 94059, "Salvador": 80622,
    "Santos": 47029, "São Luís": 20155, "São Paulo": 117573, "Uberlândia": 23515,
    "Vitória": 14109, "Vitória da Conquista": 12093,
}
_R4_PA3 = {
    "Belém": 20902, "Belo Horizonte": 73157, "Brasília": 121928, "Campinas": 58525,
    "Campo Grande": 24386, "Cuiabá": 29263, "Curitiba": 107296, "Fortaleza": 71066,
    "Goiânia": 68279, "João Pessoa": 41804, "Joinville": 29263, "Maceió": 41804,
    "Manaus": 20902, "Natal": 41804, "Porto Alegre": 107296, "Recife": 62706,
    "Ribeirão Preto": 48771, "Rio de Janeiro": 97542, "Salvador": 83608,
    "Santos": 48771, "São Luís": 20902, "São Paulo": 121928, "Uberlândia": 24386,
    "Vitória": 14631, "Vitória da Conquista": 12541,
}
_R5_PA1 = {
    "Belém": 5225, "Belo Horizonte": 29030, "Brasília": 22257, "Campinas": 23224,
    "Campo Grande": 4451, "Cuiabá": 5342, "Curitiba": 19586, "Fortaleza": 17767,
    "Goiânia": 12464, "João Pessoa": 10451, "Joinville": 5342, "Maceió": 10451,
    "Manaus": 5225, "Natal": 10451, "Porto Alegre": 19586, "Recife": 15676,
    "Ribeirão Preto": 19354, "Rio de Janeiro": 38707, "Salvador": 20902,
    "Santos": 19354, "São Luís": 5225, "São Paulo": 48384, "Uberlândia": 9677,
    "Vitória": 5806, "Vitória da Conquista": 3135,
}
_R6_PA2 = {
    "Belém": 16838, "Belo Horizonte": 50513, "Brasília": 72161, "Campinas": 40410,
    "Campo Grande": 14432, "Cuiabá": 17319, "Curitiba": 63502, "Fortaleza": 57248,
    "Goiânia": 40410, "João Pessoa": 33675, "Joinville": 17319, "Maceió": 33675,
    "Manaus": 16838, "Natal": 33675, "Porto Alegre": 63502, "Recife": 50513,
    "Ribeirão Preto": 33675, "Rio de Janeiro": 67351, "Salvador": 67351,
    "Santos": 33675, "São Luís": 16838, "São Paulo": 84188, "Uberlândia": 16838,
    "Vitória": 10103, "Vitória da Conquista": 10103,
}
_R7_PA2 = {
    "Belém": 15676, "Belo Horizonte": 47029, "Brasília": 67185, "Campinas": 37623,
    "Campo Grande": 13437, "Cuiabá": 16124, "Curitiba": 59122, "Fortaleza": 53300,
    "Goiânia": 37623, "João Pessoa": 31353, "Joinville": 16124, "Maceió": 31353,
    "Manaus": 15676, "Natal": 31353, "Porto Alegre": 59122, "Recife": 47029,
    "Ribeirão Preto": 31353, "Rio de Janeiro": 62706, "Salvador": 62706,
    "Santos": 31353, "São Luís": 15676, "São Paulo": 78382, "Uberlândia": 15676,
    "Vitória": 9406, "Vitória da Conquista": 9406,
}
# Ordem cronológica das rodadas reais já jogadas, por produto.
# R6 = PRIMEIRA rodada PA2 do jogo → ancora a série densa de PA2 (antes só histórico).
# R7 = 2ª PA2 (real 895.793; HW previu 879.873 → erro -1,8%). Atualiza a série de PA2.
_REALIZADO = {"PA1": [_R2_PA1, _R5_PA1], "PA2": [_R6_PA2, _R7_PA2], "PA3": [_R3_PA3, _R4_PA3]}


def _carregar_historico() -> pd.DataFrame:
    df = pd.read_parquet(BASE / "data" / "demanda_long.parquet")
    df["week"] = (df["ano"] - 1) * 48 + df["rodada"]
    return df


def _fit_hw(y: np.ndarray, h: int) -> np.ndarray:
    """HW aditivo com tendência amortecida + sazonalidade (auto-tuna α/β/γ).
    Fallback sem sazonalidade se a série for curta/instável."""
    y = np.asarray(y, dtype=float)
    try:
        m = ExponentialSmoothing(
            y, trend="add", damped_trend=True,
            seasonal="add", seasonal_periods=48,
        ).fit()  # statsmodels otimiza os parâmetros internamente
        fc = m.forecast(h)
    except Exception:
        m = ExponentialSmoothing(y, trend="add", damped_trend=True).fit()
        fc = m.forecast(h)
    return np.maximum(fc, 0.0)


def _serie_densa(hist: pd.DataFrame, pa: str, cidade: str) -> np.ndarray:
    """Histórico do produto (96 sem) + rodadas reais onde ele apareceu."""
    base = (hist[(hist["pa"] == pa) & (hist["cidade"] == cidade)]
            .sort_values("week")["qtd"].values.astype(float))
    extra = [float(r.get(cidade, 0)) for r in _REALIZADO.get(pa, [])]
    return np.concatenate([base, np.array(extra, dtype=float)]) if extra else base


def prever_proximas(n_ahead: int = 3, debias: float = DEBIAS,
                    share: float = SHARE) -> Dict[str, Dict[str, List[float]]]:
    """Previsão das próximas `n_ahead` ocorrências de CADA produto, por cidade.

    Retorna {pa: {cidade: [v1, v2, ...]}} — v_k = demanda (frascos) da k-ésima
    próxima rodada cheia daquele produto naquela cidade (já com share e de-viés).
    """
    hist = _carregar_historico()
    cidades = sorted(hist["cidade"].unique())
    out: Dict[str, Dict[str, List[float]]] = {pa: {} for pa in PAS}
    for pa in PAS:
        for c in cidades:
            serie = _serie_densa(hist, pa, c)
            fc = _fit_hw(serie, n_ahead) * share * debias
            out[pa][c] = [float(round(v)) for v in fc]
    return out


def backtest_ultima_real() -> Dict[str, float]:
    """Erro % do HW na ÚLTIMA rodada real de cada produto (holdout 1 passo).
    Treina sem o último ponto real e compara a previsão com ele."""
    hist = _carregar_historico()
    cidades = sorted(hist["cidade"].unique())
    res = {}
    for pa, rodadas in _REALIZADO.items():
        if not rodadas:
            continue
        alvo = rodadas[-1]
        prev_tot = real_tot = 0.0
        for c in cidades:
            base = (hist[(hist["pa"] == pa) & (hist["cidade"] == c)]
                    .sort_values("week")["qtd"].values.astype(float))
            extra = [float(r.get(c, 0)) for r in rodadas[:-1]]
            serie = np.concatenate([base, np.array(extra)]) if extra else base
            prev = _fit_hw(serie, 1)[0] * SHARE * DEBIAS
            prev_tot += prev
            real_tot += float(alvo.get(c, 0))
        res[pa] = (prev_tot - real_tot) / real_tot * 100 if real_tot else 0.0
    return res


if __name__ == "__main__":
    import io, sys
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
    print("=== BACKTEST (erro % na última rodada real de cada produto) ===")
    for pa, err in backtest_ultima_real().items():
        print(f"  {pa}: {err:+.1f}%")
    print("\n=== PREVISÃO PRÓXIMAS 3 RODADAS (nacional = Flamengo, share 100%) ===")
    fc = prever_proximas(3)
    print(f'{"prod":<5}{"próx (R5)":>14}{"R6":>14}{"R7":>14}')
    for pa in PAS:
        tots = [sum(fc[pa][c][k] for c in fc[pa]) for k in range(3)]
        print(f'{pa:<5}' + "".join(f"{t:>14,.0f}" for t in tots))
