"""서브점수 정규화와 단기/장기/최종 온도·5단계 등급 (AUTOPILOT 부록 A.2·A.4).

- 단기 온도 = 0.6×일봉 오실레이터 점수 + 0.4×주봉 점수 (한쪽 NaN이면 가중 재정규화)
- 최종 온도 = 0.4×단기 + 0.6×장기 (한쪽 NaN이면 다른 쪽 100%), 최신값에서만 반올림
- 등급: ≥60 광기 / [30,60) 과열 / (-30,30) 중립 / (-60,-30] 소외 / ≤-60 깊은 소외
"""

from __future__ import annotations

from collections.abc import Callable

import pandas as pd

from oo_scan import indicators, long_term

SCORE_MIN, SCORE_MAX = -100.0, 100.0
DAILY_WEIGHT, WEEKLY_WEIGHT = 0.6, 0.4  # 단기 온도 내 일봉/주봉 가중
SHORT_WEIGHT, LONG_WEIGHT = 0.4, 0.6  # 최종 온도 내 단기/장기 가중
MIN_BARS_FOR_GRADE = 60  # §2.3 데이터 부족 규칙 — 봉 수 미만이면 등급 산정 제외

GRADES = ["광기", "과열", "중립", "소외", "깊은 소외"]
GRADE_INSUFFICIENT = "데이터 부족"


def _clip(s: pd.Series) -> pd.Series:
    """점수를 [-100, 100]으로 클립한다."""
    return s.clip(SCORE_MIN, SCORE_MAX)


# 부록 A.2 — 지표 원값 → 서브점수 변환 (전부 클립 포함, 광기 방향 = +)
SHORT_TRANSFORMS: dict[str, Callable[[pd.Series], pd.Series]] = {
    "rsi": lambda x: _clip((x - 50.0) * 2.0),
    "slow_d": lambda x: _clip((x - 50.0) * 2.0),
    "percent_b": lambda x: _clip((x - 0.5) * 200.0),
    "williams_r": lambda x: _clip((x + 50.0) * 2.0),
    "cci": lambda x: _clip(x / 2.0),
    "disparity20": lambda x: _clip((x - 100.0) * 10.0),
    "mfi": lambda x: _clip((x - 50.0) * 2.0),
}


def oscillator_score_series(df: pd.DataFrame, use_mfi: bool) -> pd.Series:
    """한 타임프레임의 오실레이터 점수 — 서브점수(가용분)의 행별 동일가중 평균.

    구성: RSI·SlowD·%B·W%R·CCI·이격도20 (+ use_mfi면 MFI). NaN은 제외하고 평균한다.
    """
    close, high, low = df["close"], df["high"], df["low"]
    _, slow_d = indicators.stochastic_slow(high, low, close)
    raw: dict[str, pd.Series] = {
        "rsi": indicators.rsi(close),
        "slow_d": slow_d,
        "percent_b": indicators.percent_b(close),
        "williams_r": indicators.williams_r(high, low, close),
        "cci": indicators.cci(high, low, close),
        "disparity20": indicators.disparity(close),
    }
    if use_mfi and "volume" in df.columns:
        raw["mfi"] = indicators.mfi(high, low, close, df["volume"])
    scores = pd.DataFrame({name: SHORT_TRANSFORMS[name](series) for name, series in raw.items()})
    return _clip(scores.mean(axis=1))


def combine_weighted(a: pd.Series, b: pd.Series, weight_a: float, weight_b: float) -> pd.Series:
    """두 점수 시계열의 가중 결합 — 행별로 NaN 쪽 가중을 제외하고 재정규화한다.

    둘 다 NaN인 행은 NaN. b는 a의 인덱스로 재정렬된다.
    """
    b = b.reindex(a.index)
    w_a = a.notna().astype(float) * weight_a
    w_b = b.notna().astype(float) * weight_b
    denom = w_a + w_b
    num = a.fillna(0.0) * weight_a + b.fillna(0.0) * weight_b
    return num / denom.where(denom > 0)


def short_temperature_series(daily_df: pd.DataFrame, crypto: bool, use_mfi: bool) -> pd.Series:
    """단기 온도 = 일봉 점수×0.6 + 주봉 점수×0.4.

    주봉 점수는 주봉 리샘플 위에서 계산한 뒤 일봉 인덱스로 ffill 재정렬한다.
    주봉이 NaN인 행은 일봉 가중 1.0 (행별 재정규화).
    """
    daily_score = oscillator_score_series(daily_df, use_mfi)
    weekly_df = indicators.resample_weekly(daily_df, crypto)
    weekly_score = oscillator_score_series(weekly_df, use_mfi)
    weekly_on_daily = weekly_score.reindex(daily_df.index, method="ffill")
    return combine_weighted(daily_score, weekly_on_daily, DAILY_WEIGHT, WEEKLY_WEIGHT)


def total_temperature_series(daily_df: pd.DataFrame, crypto: bool, use_mfi: bool) -> pd.Series:
    """최종 온도 시계열 = 0.4×단기 + 0.6×장기 (한쪽 NaN이면 다른 쪽 100%).

    시계열 단계에서는 반올림하지 않는다 — 반올림은 최신값 추출 시에만.
    """
    short_s = short_temperature_series(daily_df, crypto, use_mfi)
    long_s = long_term.long_temperature_series(daily_df["close"])
    return combine_weighted(short_s, long_s, SHORT_WEIGHT, LONG_WEIGHT)


def grade(total: float) -> str:
    """최종 온도 → 5단계 등급. 경계값은 극단 쪽에 포함, NaN은 '데이터 부족'."""
    if pd.isna(total):
        return GRADE_INSUFFICIENT
    if total >= 60:
        return "광기"
    if total >= 30:
        return "과열"
    if total > -30:
        return "중립"
    if total > -60:
        return "소외"
    return "깊은 소외"


def latest_scores(daily_df: pd.DataFrame, crypto: bool, use_mfi: bool) -> dict[str, float | str]:
    """최신 시점의 단기/장기/최종 온도와 등급을 dict로 반환한다.

    종가 봉 수 < 60이면 전부 NaN에 등급 '데이터 부족' (§2.3). 최종 온도는 여기서만 반올림.
    """
    nan = float("nan")
    if len(daily_df) < MIN_BARS_FOR_GRADE:
        return {"short": nan, "long": nan, "total": nan, "grade": GRADE_INSUFFICIENT}
    short_s = short_temperature_series(daily_df, crypto, use_mfi)
    long_s = long_term.long_temperature_series(daily_df["close"])
    total_s = combine_weighted(short_s, long_s, SHORT_WEIGHT, LONG_WEIGHT)
    short_v = float(short_s.iloc[-1])
    long_v = float(long_s.iloc[-1])
    total_raw = total_s.iloc[-1]
    total_v = nan if pd.isna(total_raw) else float(round(float(total_raw)))
    return {"short": short_v, "long": long_v, "total": total_v, "grade": grade(total_v)}
