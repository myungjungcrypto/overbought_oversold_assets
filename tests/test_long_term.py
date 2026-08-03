"""장기 온도 지표 테스트 (L1–L3).

기대값은 전부 AUTOPILOT 부록 A.3 공식(pct(x,W)=mean(W≤x)×100, 트레일링 윈도)에서
손계산으로 유도했다. 네트워크·파일 I/O 없음.
"""

from __future__ import annotations

import math

import numpy as np
import pandas as pd
import pytest

from oo_scan import long_term as lt


def _s(vals) -> pd.Series:
    """리스트 → float Series."""
    return pd.Series([float(v) for v in vals])


def _ramp(n: int) -> pd.Series:
    """1..n 정수 램프."""
    return pd.Series(np.arange(1, n + 1, dtype=float))


# --------------------------------------------- 트레일링 백분위 (L1·L2 공통)


def test_trailing_percentile_ramp_current_is_max_100() -> None:
    """상승 램프에선 현재값이 윈도 최대 → 백분위 100. min_obs 전엔 NaN."""
    p = lt.trailing_percentile(_ramp(10), window=10, min_obs=5)
    assert p.iloc[:4].isna().all()
    assert (p.iloc[4:] == 100.0).all()


def test_trailing_percentile_decreasing_current_is_min() -> None:
    """하락 램프에선 현재값만 자기 이하 → 백분위 = 1/n×100."""
    p = lt.trailing_percentile(_s(range(10, 0, -1)), window=10, min_obs=5)
    assert p.iloc[4] == pytest.approx(20.0)  # 관측 5개 중 1개
    assert p.iloc[9] == pytest.approx(10.0)  # 관측 10개 중 1개


def test_trailing_percentile_ties_and_nan_skip() -> None:
    """동률(≤)은 전부 포함하고 윈도 내 NaN은 관측에서 제외한다."""
    p = lt.trailing_percentile(_s([1, np.nan, 3, 2, 2]), window=5, min_obs=3)
    assert math.isnan(p.iloc[2])  # 비NaN 관측 2개 < min_obs
    assert p.iloc[3] == pytest.approx(200 / 3)  # [1,3,2]에서 2 이하 = 2/3
    assert p.iloc[4] == pytest.approx(75.0)  # [1,3,2,2]에서 2 이하 = 3/4


def test_trailing_percentile_default_min_obs_gate() -> None:
    """기본 min_obs=120: 관측 120개째부터 산출된다."""
    p = lt.trailing_percentile(_ramp(130))
    assert math.isnan(p.iloc[118])
    assert p.iloc[119] == pytest.approx(100.0)
    assert p.iloc[-1] == pytest.approx(100.0)


# ------------------------------------------- 이격도200 백분위 점수 (L1)


def test_disparity200_score_linear_ramp_exact() -> None:
    """선형 램프: d200=C/SMA200×100은 단조 감소 → 현재값이 최소 → pct=100/n.

    첫 산출은 d200 관측 120개째(idx 318): 점수 = (100/120-50)×2 = -295/3.
    """
    close = _ramp(320)
    d200 = lt.disparity200(close)
    assert d200.iloc[:199].isna().all()
    assert d200.iloc[199] == pytest.approx(200 / 100.5 * 100)  # SMA200(1..200)=100.5
    score = lt.disparity200_score(close)
    assert score.iloc[:318].isna().all()
    assert score.iloc[318] == pytest.approx((100 / 120 - 50) * 2)
    assert score.iloc[319] == pytest.approx((100 / 121 - 50) * 2)


def test_disparity200_score_warmup_all_nan() -> None:
    """d200 관측이 120개 미만(봉 318개 미만)이면 전 구간 NaN."""
    assert lt.disparity200_score(_ramp(317)).isna().all()


# ------------------------------------------------ 레인지 위치 점수 (L1)


def test_range_position_score_triangle_exact() -> None:
    """삼각파(0↑60↓30): 꼭짓점=100, 종점은 정확히 중앙(pos 50) → 점수 0."""
    close = _s(list(range(61)) + list(range(59, 29, -1)))  # 91봉, min=0/max=60/끝=30
    score = lt.range_position_score(close, 756)
    assert math.isnan(score.iloc[58])  # min_periods=60 게이트
    assert score.iloc[59] == pytest.approx(100.0)  # C=59가 당시 최고
    assert score.iloc[60] == pytest.approx(100.0)  # 꼭짓점 C=60
    assert score.iloc[90] == pytest.approx(0.0)  # (30-0)/(60-0)=50% → 0
    assert lt.range_position(close, 756).iloc[90] == pytest.approx(50.0)
    # 윈도가 시계열보다 길면 252/756 결과 동일
    pd.testing.assert_series_equal(score, lt.range_position_score(close, 252))


def test_range_position_score_descending_is_minus_100() -> None:
    """하락 램프에선 항상 C=롤링 최저 → pos 0 → 점수 -100."""
    score = lt.range_position_score(_s(range(100, -1, -1)), 252)
    assert score.iloc[59] == pytest.approx(-100.0)
    assert score.iloc[-1] == pytest.approx(-100.0)


def test_range_position_score_flat_window_nan() -> None:
    """max == min(플랫)이면 NaN."""
    assert lt.range_position_score(_s([5] * 80), 252).isna().all()


# ------------------------------------------- 1년 수익률 백분위 점수 (L2)


def test_yearly_return_score_ramp_exact_and_warmup() -> None:
    """선형 램프: r=C/C[-252]-1은 단조 감소 → 첫 산출(idx 371)에서 pct=100/120."""
    score = lt.yearly_return_score(_ramp(372))
    assert score.iloc[:371].isna().all()  # r 관측 120개 필요 (252+119)
    assert score.iloc[371] == pytest.approx((100 / 120 - 50) * 2)


def test_yearly_return_score_constant_ties_100() -> None:
    """상수 가격은 r=0 동률 → pct=100(≤ 정의) → 점수 100."""
    score = lt.yearly_return_score(_s([80] * 372))
    assert math.isnan(score.iloc[370])
    assert score.iloc[371] == pytest.approx(100.0)


# ------------------------------------------------------ 드로다운 (L2)


def test_drawdown_stats_peak_then_fall_exact() -> None:
    """고점 100 후 80까지 하락: 드로다운 -20%, 고점 후 4거래일."""
    dd, days = lt.drawdown_stats(_s([50, 60, 70, 80, 90, 100, 95, 90, 85, 80]))
    assert dd == pytest.approx(-20.0)
    assert days == pytest.approx(4.0)


def test_drawdown_stats_window_and_retouch() -> None:
    """고점 재터치 시 마지막 도달 기준, 윈도 밖 고점은 무시."""
    dd, days = lt.drawdown_stats(_s([100, 90, 100, 90]))
    assert dd == pytest.approx(-10.0)
    assert days == pytest.approx(1.0)
    dd2, days2 = lt.drawdown_stats(_s([100, 50, 60, 55]), window=2)
    assert dd2 == pytest.approx((55 / 60 - 1) * 100)  # 윈도 내 고점은 60
    assert days2 == pytest.approx(1.0)


def test_drawdown_stats_fresh_high_and_empty() -> None:
    """신고가면 (0%, 0일), 빈 시계열이면 (NaN, NaN)."""
    dd, days = lt.drawdown_stats(_ramp(50))
    assert dd == pytest.approx(0.0)
    assert days == pytest.approx(0.0)
    dd_nan, days_nan = lt.drawdown_stats(pd.Series([], dtype=float))
    assert math.isnan(dd_nan) and math.isnan(days_nan)


# ---------------------------------------------------- 장기 온도 합성 (L3)


def test_long_temperature_two_components_ramp() -> None:
    """봉 130개 램프: 레인지 점수 2개만 가용(각 100) → 장기 온도 100."""
    temp = lt.long_temperature_series(_ramp(130))
    assert math.isnan(temp.iloc[58])  # 전 서브점수 NaN
    assert temp.iloc[-1] == pytest.approx(100.0)


def test_long_temperature_single_component_flat_series() -> None:
    """플랫 340봉: 레인지 NaN(플랫)·수익률 NaN(관측 부족) → 이격도200 점수 하나로 결정."""
    temp = lt.long_temperature_series(_s([50] * 340))
    assert math.isnan(temp.iloc[317])
    assert temp.iloc[-1] == pytest.approx(100.0)  # d200=100 동률 → pct 100 → 점수 100


def test_long_temperature_three_components_exact() -> None:
    """램프 340봉: d200 점수 (100/141-50)×2, 레인지 2개 100 → 평균 14300/423."""
    temp = lt.long_temperature_series(_ramp(340))
    assert temp.iloc[-1] == pytest.approx(14300 / 423)


def test_long_temperature_short_series_all_nan() -> None:
    """봉 60개 미만이면 어떤 서브점수도 없어 전 구간 NaN."""
    assert lt.long_temperature_series(_ramp(59)).isna().all()
