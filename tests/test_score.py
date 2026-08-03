"""서브점수 정규화·단기/최종 온도·5단계 등급 테스트 (I6·S1).

기대값은 AUTOPILOT 부록 A.2·A.4 공식에서 손계산으로 유도했다. 네트워크·파일 I/O 없음.
"""

from __future__ import annotations

import math

import numpy as np
import pandas as pd
import pytest

from oo_scan import indicators as ind
from oo_scan import long_term as lt
from oo_scan import score as sc


def _ramp_df(n: int, calendar: bool = False) -> pd.DataFrame:
    """h=l=c=o 램프(1..n) OHLCV 프레임 — 영업일 또는 달력일(크립토) 인덱스."""
    if calendar:
        idx = pd.date_range("2024-01-01", periods=n, freq="D")
    else:
        idx = pd.bdate_range("2023-01-02", periods=n)
    c = pd.Series(np.arange(1, n + 1, dtype=float), index=idx)
    return pd.DataFrame({"open": c, "high": c, "low": c, "close": c, "volume": 1.0}, index=idx)


def _const_df(n: int, value: float = 100.0) -> pd.DataFrame:
    """상수 가격 OHLCV 프레임."""
    idx = pd.bdate_range("2023-01-02", periods=n)
    c = pd.Series([value] * n, index=idx)
    return pd.DataFrame({"open": c, "high": c, "low": c, "close": c, "volume": 1.0}, index=idx)


def _ramp_expected_scores() -> list[float]:
    """정수 램프 마지막 봉의 7개 서브점수 (부록 A.1·A.2 손계산).

    RSI=100→100, SlowD=100→100, %B=0.5+9.5/(4√33.25)→1900/(4√33.25),
    W%R=0→100, CCI=9.5/0.075=380/3→190/3, 이격도 클립→100, MFI=100→100.
    """
    pb_t = 1900 / (4 * math.sqrt(33.25))
    return [100.0, 100.0, pb_t, 100.0, 190.0 / 3.0, 100.0, 100.0]


# ------------------------------------------------ 서브점수 변환 (I6)


def test_short_transforms_exact_and_clip_saturation() -> None:
    """각 변환식의 정확값과 [-100,100] 클립 포화."""
    cases: dict[str, list[tuple[float, float]]] = {
        "rsi": [(50, 0), (75, 50), (100, 100), (0, -100)],
        "slow_d": [(50, 0), (80, 60), (0, -100)],
        "percent_b": [(0.5, 0), (0.75, 50), (1.0, 100), (1.6, 100), (-0.5, -100)],
        "williams_r": [(-50, 0), (0, 100), (-100, -100)],
        "cci": [(0, 0), (100, 50), (300, 100), (-250, -100)],
        "disparity20": [(100, 0), (105, 50), (112, 100), (88, -100)],
        "mfi": [(50, 0), (100, 100), (0, -100)],
    }
    for name, pairs in cases.items():
        xs = pd.Series([float(x) for x, _ in pairs])
        out = sc.SHORT_TRANSFORMS[name](xs)
        assert list(out) == pytest.approx([want for _, want in pairs]), name


def test_short_transforms_cover_seven_indicators() -> None:
    """변환 딕셔너리는 부록 A.2의 7개 지표를 정확히 커버한다."""
    assert set(sc.SHORT_TRANSFORMS) == {
        "rsi", "slow_d", "percent_b", "williams_r", "cci", "disparity20", "mfi",
    }


# ------------------------------------------- 오실레이터 점수 시계열 (I6)


def test_oscillator_score_constant_single_component_nan_skip() -> None:
    """상수 시계열: 이격도20(=100→0점)만 정의 → NaN 제외 평균 = 0."""
    df = _const_df(30)
    s = sc.oscillator_score_series(df, use_mfi=True)
    assert math.isnan(s.iloc[18])  # 이격도 워밍업 전엔 가용 서브점수 0개
    assert s.iloc[19] == pytest.approx(0.0)
    assert s.iloc[-1] == pytest.approx(0.0)


def test_oscillator_score_ramp_exact_with_and_without_mfi() -> None:
    """40봉 램프 마지막 봉: 7개(또는 MFI 제외 6개) 서브점수의 동일가중 평균."""
    df = _ramp_df(40)
    comps = _ramp_expected_scores()
    with_mfi = sc.oscillator_score_series(df, use_mfi=True)
    assert with_mfi.iloc[-1] == pytest.approx(sum(comps) / 7)
    without_mfi = sc.oscillator_score_series(df, use_mfi=False)
    assert without_mfi.iloc[-1] == pytest.approx((sum(comps) - 100.0) / 6)


# ------------------------------------------------- 가중 결합 (I6·S1)


def test_combine_weighted_renormalization() -> None:
    """NaN 쪽 가중을 제외한 재정규화 — 한쪽만 있으면 그 값 그대로."""
    a = pd.Series([10.0, np.nan, np.nan, 20.0])
    b = pd.Series([30.0, 40.0, np.nan, 60.0])
    out = sc.combine_weighted(a, b, 0.6, 0.4)
    assert out.iloc[0] == pytest.approx(18.0)  # 0.6×10+0.4×30
    assert out.iloc[1] == pytest.approx(40.0)  # b만 가용 → 가중 1.0
    assert math.isnan(out.iloc[2])  # 둘 다 NaN
    assert out.iloc[3] == pytest.approx(36.0)


# ---------------------------------------------------- 단기 온도 (I6)


def test_short_temperature_weekly_nan_fallback_weight_one() -> None:
    """주봉 8개뿐이라 주봉 점수 전 구간 NaN → 단기 온도 = 일봉 점수 그대로."""
    df = _ramp_df(40)
    weekly_score = sc.oscillator_score_series(ind.resample_weekly(df, crypto=False), True)
    assert weekly_score.isna().all()
    short = sc.short_temperature_series(df, crypto=False, use_mfi=True)
    daily = sc.oscillator_score_series(df, use_mfi=True)
    pd.testing.assert_series_equal(short, daily, check_names=False)


def test_short_temperature_daily_weekly_composition() -> None:
    """28주(140영업일) 램프: 마지막 금요일에서 단기 = 0.6×일봉 + 0.4×주봉."""
    df = _ramp_df(140)  # 월요일 시작 → 마지막 봉은 금요일 = 주봉 라벨
    daily_last = sc.oscillator_score_series(df, True).iloc[-1]
    weekly_last = sc.oscillator_score_series(ind.resample_weekly(df, False), True).iloc[-1]
    assert not math.isnan(weekly_last)  # 주봉 28개 → 주봉 점수 가용
    short = sc.short_temperature_series(df, crypto=False, use_mfi=True)
    assert short.iloc[-1] == pytest.approx(0.6 * daily_last + 0.4 * weekly_last)


# ---------------------------------------------------- 최종 온도 (S1)


def test_total_temperature_long_nan_equals_short() -> None:
    """봉 40개: 장기 서브점수 전무 → 최종 온도 = 단기 100%."""
    df = _ramp_df(40)
    assert lt.long_temperature_series(df["close"]).isna().all()
    total = sc.total_temperature_series(df, crypto=False, use_mfi=True)
    short = sc.short_temperature_series(df, crypto=False, use_mfi=True)
    pd.testing.assert_series_equal(total, short, check_names=False)


def test_total_temperature_composition_both_available() -> None:
    """봉 340개: 단기·장기 모두 가용 → 최종 = 0.4×단기 + 0.6×장기."""
    df = _ramp_df(340)
    short_last = sc.short_temperature_series(df, False, True).iloc[-1]
    long_last = lt.long_temperature_series(df["close"]).iloc[-1]
    assert not math.isnan(short_last) and not math.isnan(long_last)
    total = sc.total_temperature_series(df, crypto=False, use_mfi=True)
    assert total.iloc[-1] == pytest.approx(0.4 * short_last + 0.6 * long_last)


# ------------------------------------------------------- 등급 (S1)


def test_grade_boundaries_exact() -> None:
    """경계값은 극단 쪽 포함: ≥60 광기 / [30,60) 과열 / (-30,30) 중립 / (-60,-30] 소외."""
    assert sc.grade(100.0) == "광기"
    assert sc.grade(60.0) == "광기"
    assert sc.grade(59.999) == "과열"
    assert sc.grade(30.0) == "과열"
    assert sc.grade(29.999) == "중립"
    assert sc.grade(0.0) == "중립"
    assert sc.grade(-29.999) == "중립"
    assert sc.grade(-30.0) == "소외"
    assert sc.grade(-59.999) == "소외"
    assert sc.grade(-60.0) == "깊은 소외"
    assert sc.grade(-100.0) == "깊은 소외"


def test_grade_nan_and_grades_export() -> None:
    """NaN은 '데이터 부족', GRADES 명칭·순서 고정."""
    assert sc.grade(float("nan")) == "데이터 부족"
    assert sc.GRADES == ["광기", "과열", "중립", "소외", "깊은 소외"]


# ------------------------------------------------- 최신 스코어 (S1)


def test_latest_scores_below_60_bars_insufficient() -> None:
    """봉 59개(<60) → 전부 NaN + '데이터 부족' (§2.3)."""
    res = sc.latest_scores(_ramp_df(59), crypto=False, use_mfi=True)
    assert set(res) == {"short", "long", "total", "grade"}
    assert math.isnan(res["short"]) and math.isnan(res["long"]) and math.isnan(res["total"])
    assert res["grade"] == "데이터 부족"


def test_latest_scores_at_exactly_60_bars_graded() -> None:
    """봉 60개면 등급이 산정된다 — 레인지 점수 2개로 장기 100."""
    res = sc.latest_scores(_ramp_df(60), crypto=False, use_mfi=True)
    assert res["grade"] != "데이터 부족"
    assert res["grade"] in sc.GRADES
    assert res["long"] == pytest.approx(100.0)
    assert not math.isnan(res["total"])
    assert res["total"] == round(res["total"])  # 최종 온도는 반올림돼 있다


def test_latest_scores_hype_like_220_bars_renormalized() -> None:
    """HYPE류 220봉(크립토): 장기 2/4개(레인지)만 가용 → 재정규화로 총점 산출."""
    df = _ramp_df(220, calendar=True)
    close = df["close"]
    assert math.isnan(lt.disparity200_score(close).iloc[-1])  # 관측 부족
    assert math.isnan(lt.yearly_return_score(close).iloc[-1])
    res = sc.latest_scores(df, crypto=True, use_mfi=True)
    assert res["long"] == pytest.approx(100.0)  # 가용 레인지 점수 2개 모두 100
    short_last = sc.short_temperature_series(df, crypto=True, use_mfi=True).iloc[-1]
    assert res["short"] == pytest.approx(short_last)
    assert res["total"] == pytest.approx(round(0.4 * short_last + 0.6 * 100.0))
    assert res["grade"] == "광기"
