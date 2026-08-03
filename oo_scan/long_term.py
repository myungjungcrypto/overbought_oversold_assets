"""장기 온도 지표 (AUTOPILOT 부록 A.3) — 구조적 광기/소외 측정.

백분위 정의: pct(x, W) = mean(W ≤ x) × 100 — 현재값을 포함한 트레일링 윈도 W 내 비율.
모든 점수는 [-100, 100]으로 클립되며 광기 방향이 +다.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

WINDOW_3Y = 756  # 3년 ≈ 756거래일
WINDOW_1Y = 252  # 1년 ≈ 252거래일
SMA_LONG = 200  # 장기 이격도 기준 SMA
MIN_PERCENTILE_OBS = 120  # 백분위 산출 최소 관측치
MIN_RANGE_OBS = 60  # 레인지 위치 최소 봉 수

SCORE_MIN, SCORE_MAX = -100.0, 100.0


def _to_score(pct: pd.Series) -> pd.Series:
    """백분위/레인지 위치(0~100)를 점수(-100~100)로 변환·클립한다."""
    return ((pct - 50.0) * 2.0).clip(SCORE_MIN, SCORE_MAX)


def trailing_percentile(
    s: pd.Series,
    window: int = WINDOW_3Y,
    min_obs: int = MIN_PERCENTILE_OBS,
) -> pd.Series:
    """트레일링 백분위 — 각 시점에서 최근 ≤window개 관측(현재 포함, NaN 제외) 중
    현재값 이하 비율×100. 윈도 내 비NaN 관측이 min_obs 미만이면 NaN."""

    def _pct(w: np.ndarray) -> float:
        cur = w[-1]
        if np.isnan(cur):
            return np.nan
        vals = w[~np.isnan(w)]
        if len(vals) < min_obs:
            return np.nan
        return float((vals <= cur).mean() * 100.0)

    return s.rolling(window, min_periods=1).apply(_pct, raw=True)


def disparity200(close: pd.Series, period: int = SMA_LONG) -> pd.Series:
    """SMA200 이격도 원값 = C/SMA(period)×100 (표시·검증용). 200봉 미만 구간은 NaN."""
    sma = close.rolling(period).mean()
    return close / sma.where(sma != 0) * 100.0


def disparity200_score(close: pd.Series) -> pd.Series:
    """이격도200의 3년(756일) 트레일링 백분위 점수 = (pct-50)×2."""
    pct = trailing_percentile(disparity200(close), WINDOW_3Y, MIN_PERCENTILE_OBS)
    return _to_score(pct)


def range_position(close: pd.Series, window: int) -> pd.Series:
    """레인지 위치 원값 = (C-롤링최저)/(롤링최고-롤링최저)×100 ∈ [0,100].

    min_periods=60, 최고 == 최저이면 NaN.
    """
    rmin = close.rolling(window, min_periods=MIN_RANGE_OBS).min()
    rmax = close.rolling(window, min_periods=MIN_RANGE_OBS).max()
    rng = rmax - rmin
    return (close - rmin) / rng.where(rng != 0) * 100.0


def range_position_score(close: pd.Series, window: int) -> pd.Series:
    """레인지 위치 점수 = (pos-50)×2. 호출처는 window=252(52주)와 756(3년)."""
    return _to_score(range_position(close, window))


def yearly_return_score(close: pd.Series) -> pd.Series:
    """1년(252거래일) 수익률의 3년 트레일링 백분위 점수 = (pct-50)×2."""
    r = close / close.shift(WINDOW_1Y) - 1.0
    pct = trailing_percentile(r, WINDOW_3Y, MIN_PERCENTILE_OBS)
    return _to_score(pct)


def drawdown_stats(close: pd.Series, window: int = WINDOW_3Y) -> tuple[float, float]:
    """표시 전용 — 최근 window 내 최고가 대비 (드로다운%, 그 최고가 이후 경과 거래일).

    최고가가 여러 번이면 마지막 도달 시점 기준. 산출 불가 시 (NaN, NaN).
    """
    tail = close.iloc[-window:]
    vals = tail.to_numpy(dtype=float)
    if vals.size == 0 or np.all(np.isnan(vals)) or np.isnan(vals[-1]):
        return (float("nan"), float("nan"))
    peak = float(np.nanmax(vals))
    if peak == 0:
        return (float("nan"), float("nan"))
    dd_pct = (vals[-1] / peak - 1.0) * 100.0
    peak_pos = int(np.where(vals == peak)[0][-1])
    days_since = float(len(vals) - 1 - peak_pos)
    return (float(dd_pct), days_since)


def long_temperature_series(close: pd.Series) -> pd.Series:
    """장기 온도 = 장기 서브점수 4개의 가용분(NaN 제외) 동일가중 평균.

    구성: 이격도200 백분위·52주 레인지·3년 레인지·1년 수익률 백분위.
    각 서브점수와 평균 모두 [-100,100] 클립, 전부 NaN인 행은 NaN.
    """
    components = pd.DataFrame(
        {
            "d200_pct": disparity200_score(close).clip(SCORE_MIN, SCORE_MAX),
            "range_52w": range_position_score(close, WINDOW_1Y).clip(SCORE_MIN, SCORE_MAX),
            "range_3y": range_position_score(close, WINDOW_3Y).clip(SCORE_MIN, SCORE_MAX),
            "yearly_pct": yearly_return_score(close).clip(SCORE_MIN, SCORE_MAX),
        }
    )
    return components.mean(axis=1).clip(SCORE_MIN, SCORE_MAX)
