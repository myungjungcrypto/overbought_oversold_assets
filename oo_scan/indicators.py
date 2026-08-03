"""단기 오실레이터 지표와 주봉 리샘플 (AUTOPILOT 부록 A.1).

모든 함수는 데이터 레인이 만든 일봉 DataFrame/Series(오름차순 naive DatetimeIndex)를 받아
입력 인덱스에 정렬된 전체 시계열 pd.Series를 반환한다. 최신값은 `.iloc[-1]`.
"""

from __future__ import annotations

import numpy as np
import pandas as pd


def rsi(close: pd.Series, period: int = 14) -> pd.Series:
    """RSI(period) — Wilder 평활.

    첫 평균은 최초 period개 변화분의 단순평균, 이후 `avg = (prev*(period-1)+cur)/period`.
    RSI = 100*avg_gain/(avg_gain+avg_loss) ∈ [0,100]. 상승/하락 평균이 모두 0이면 NaN.
    """
    n = len(close)
    out = np.full(n, np.nan)
    if n <= period:
        return pd.Series(out, index=close.index)
    diff = close.diff().to_numpy(dtype=float)
    # NaN 변화분(첫 값 등)은 0으로 취급 — 기여 없음
    gains = np.where(diff > 0, diff, 0.0)
    losses = np.where(diff < 0, -diff, 0.0)
    avg_gain = gains[1 : period + 1].mean()
    avg_loss = losses[1 : period + 1].mean()
    for t in range(period, n):
        if t > period:
            avg_gain = (avg_gain * (period - 1) + gains[t]) / period
            avg_loss = (avg_loss * (period - 1) + losses[t]) / period
        denom = avg_gain + avg_loss
        if denom > 0:
            out[t] = 100.0 * avg_gain / denom
    return pd.Series(out, index=close.index)


def stochastic_slow(
    high: pd.Series,
    low: pd.Series,
    close: pd.Series,
    k_period: int = 14,
    k_smooth: int = 3,
    d_smooth: int = 3,
) -> tuple[pd.Series, pd.Series]:
    """Stochastic Slow — (SlowK, SlowD)를 반환한다.

    FastK = (C-LL)/(HH-LL)*100, SlowK = SMA(k_smooth)(FastK), SlowD = SMA(d_smooth)(SlowK).
    윈도 내 최고가 == 최저가(플랫)이면 NaN.
    """
    hh = high.rolling(k_period).max()
    ll = low.rolling(k_period).min()
    rng = hh - ll
    fast_k = (close - ll) / rng.where(rng != 0) * 100.0
    slow_k = fast_k.rolling(k_smooth).mean()
    slow_d = slow_k.rolling(d_smooth).mean()
    return slow_k, slow_d


def percent_b(close: pd.Series, period: int = 20, num_std: float = 2.0) -> pd.Series:
    """볼린저 %B — 밴드는 SMA(period) ± num_std*σ (σ는 모집단 표준편차, ddof=0).

    %B = (C-하단)/(상단-하단). σ=0(상수 구간)이면 NaN.
    """
    mid = close.rolling(period).mean()
    sigma = close.rolling(period).std(ddof=0)
    lower = mid - num_std * sigma
    band_width = 2.0 * num_std * sigma  # 상단-하단
    return (close - lower) / band_width.where(band_width != 0)


def williams_r(high: pd.Series, low: pd.Series, close: pd.Series, period: int = 14) -> pd.Series:
    """Williams %R = (HH-C)/(HH-LL)×(-100) ∈ [-100, 0]. 플랫 윈도는 NaN."""
    hh = high.rolling(period).max()
    ll = low.rolling(period).min()
    rng = hh - ll
    return (hh - close) / rng.where(rng != 0) * -100.0


def cci(high: pd.Series, low: pd.Series, close: pd.Series, period: int = 20) -> pd.Series:
    """CCI = (TP-SMA(TP))/(0.015×MeanDev), TP=(H+L+C)/3.

    MeanDev는 윈도 내 TP의 SMA 대비 평균절대편차. 편차 0(플랫)이면 NaN.
    """
    tp = (high + low + close) / 3.0
    sma_tp = tp.rolling(period).mean()
    mean_dev = tp.rolling(period).apply(lambda w: float(np.abs(w - w.mean()).mean()), raw=True)
    denom = 0.015 * mean_dev
    return (tp - sma_tp) / denom.where(denom != 0)


def disparity(close: pd.Series, period: int = 20) -> pd.Series:
    """이격도 = C/SMA(period)×100."""
    sma = close.rolling(period).mean()
    return close / sma.where(sma != 0) * 100.0


def mfi(
    high: pd.Series,
    low: pd.Series,
    close: pd.Series,
    volume: pd.Series,
    period: int = 14,
) -> pd.Series:
    """MFI ∈ [0,100]. Raw MF = TP×volume, TP 변화 방향으로 양/음 머니플로 분리.

    음의 플로 합이 0이고 양의 플로가 있으면 100. 양·음이 모두 0(정보 없음)이면 NaN.
    """
    tp = (high + low + close) / 3.0
    raw_mf = tp * volume
    dtp = tp.diff()
    # 첫 봉(변화분 NaN)은 플로 미정 → NaN 유지
    pos_flow = raw_mf.where(dtp > 0, 0.0).where(dtp.notna())
    neg_flow = raw_mf.where(dtp < 0, 0.0).where(dtp.notna())
    pos_sum = pos_flow.rolling(period).sum()
    neg_sum = neg_flow.rolling(period).sum()
    denom = pos_sum + neg_sum
    return 100.0 * pos_sum / denom.where(denom != 0)


def has_volume(volume: pd.Series | None, window: int = 60) -> bool:
    """볼륨 사용 가능 여부 — 최근 window개 중 0/NaN이 50% 이상이면 False (부록 §6 무볼륨 규칙)."""
    if volume is None or len(volume) == 0:
        return False
    tail = volume.iloc[-window:]
    dead = tail.isna() | (tail == 0)
    frac_dead = float(dead.mean())
    return frac_dead < 0.5


def resample_weekly(df: pd.DataFrame, crypto: bool) -> pd.DataFrame:
    """일봉 → 주봉 리샘플. 크립토는 W-SUN, 전통자산은 W-FRI.

    agg: open=first, high=max, low=min, close=last, volume=sum.
    가격 4컬럼이 전부 NaN인 빈 주는 제거하고, 미완성 마지막 주는 포함한다.
    """
    rule = "W-SUN" if crypto else "W-FRI"
    agg_map = {"open": "first", "high": "max", "low": "min", "close": "last", "volume": "sum"}
    agg = {col: how for col, how in agg_map.items() if col in df.columns}
    weekly = df.resample(rule).agg(agg)
    price_cols = [c for c in ("open", "high", "low", "close") if c in weekly.columns]
    return weekly.dropna(how="all", subset=price_cols)
