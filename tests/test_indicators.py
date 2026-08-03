"""단기 오실레이터·주봉 리샘플 테스트 (I1–I5).

기대값은 전부 AUTOPILOT 부록 A.1 공식에서 손계산으로 유도했다. 네트워크·파일 I/O 없음.
"""

from __future__ import annotations

import math

import numpy as np
import pandas as pd
import pytest

from oo_scan import indicators as ind


def _s(vals) -> pd.Series:
    """리스트 → float Series (RangeIndex)."""
    return pd.Series([float(v) for v in vals])


def _ohlcv_frame(index: pd.DatetimeIndex) -> pd.DataFrame:
    """리샘플 검증용 — 컬럼마다 구분되는 값을 가진 OHLCV 프레임."""
    n = len(index)
    open_ = pd.Series(np.arange(1, n + 1, dtype=float), index=index)
    return pd.DataFrame(
        {
            "open": open_,
            "high": open_ + 10.0,
            "low": open_ - 0.5,
            "close": open_ + 0.25,
            "volume": pd.Series([1.0] * n, index=index),
        }
    )


# ---------------------------------------------------------------- RSI (I1)


def test_rsi_hand_computed_wilder_20_bars() -> None:
    """교대 ±1 변화 14개(시드 평균 0.5/0.5) 뒤 +1,+1,-1,+1,+1 — Wilder 체인 손계산.

    |변화|=1이라 avg_gain+avg_loss=1이 유지되므로 RSI = 100×avg_gain.
    avg_gain: 0.5 → 7.5/14 → 111.5/196 → 1449.5/2744 → 21587.5/38416 → 319053.5/537824.
    """
    closes = [100, 101, 100, 101, 100, 101, 100, 101, 100, 101, 100, 101, 100, 101, 100,
              101, 102, 101, 102, 103]
    r = ind.rsi(_s(closes), period=14)
    assert r.iloc[:14].isna().all()
    assert r.iloc[14] == pytest.approx(50.0)
    assert r.iloc[15] == pytest.approx(100 * 7.5 / 14)
    assert r.iloc[16] == pytest.approx(100 * 111.5 / 196)
    assert r.iloc[17] == pytest.approx(100 * 1449.5 / 2744)
    assert r.iloc[18] == pytest.approx(100 * 21587.5 / 38416)
    assert r.iloc[19] == pytest.approx(100 * 319053.5 / 537824)


def test_rsi_all_up_ramp_is_100_and_all_down_is_0() -> None:
    """전부 상승이면 avg_loss=0 → RSI 100, 전부 하락이면 avg_gain=0 → RSI 0."""
    up = ind.rsi(_s(range(1, 31)))
    assert (up.iloc[14:] == 100.0).all()
    down = ind.rsi(_s(range(60, 30, -1)))
    assert (down.iloc[14:] == 0.0).all()


def test_rsi_bounds_on_random_walk() -> None:
    """결정적 랜덤워크에서 RSI ∈ [0,100]."""
    gen = np.random.default_rng(7)
    close = _s(100 + np.cumsum(gen.normal(0, 1, 200)))
    r = ind.rsi(close)
    valid = r.dropna()
    assert len(valid) == 200 - 14
    assert valid.between(0.0, 100.0).all()


def test_rsi_warmup_is_nan() -> None:
    """period+1봉 미만이면 전부 NaN, 정확히 period+1봉이면 마지막 1개만 산출."""
    assert ind.rsi(_s(range(1, 15))).isna().all()  # 14봉
    r = ind.rsi(_s(range(1, 16)))  # 15봉 상승 램프
    assert r.iloc[:14].isna().all()
    assert r.iloc[14] == 100.0


# ------------------------------------------------- Stochastic Slow (I2)


def test_stochastic_slow_known_ramp_case() -> None:
    """램프 + 대칭 밴드(h=c+1, l=c-1), k=3: FastK=(3/4)×100=75 → SlowK=SlowD=75."""
    close = _s(range(1, 9))
    slow_k, slow_d = ind.stochastic_slow(close + 1, close - 1, close, 3, 3, 3)
    assert slow_k.iloc[:4].isna().all()
    assert (slow_k.iloc[4:] == 75.0).all()
    assert slow_d.iloc[:6].isna().all()
    assert (slow_d.iloc[6:] == 75.0).all()


def test_stochastic_flat_window_is_nan() -> None:
    """HH == LL(플랫 윈도)이면 FastK 정의 불가 → 전 구간 NaN."""
    c = _s([5] * 12)
    slow_k, slow_d = ind.stochastic_slow(c, c, c, 3, 3, 3)
    assert slow_k.isna().all()
    assert slow_d.isna().all()


def test_stochastic_bounds_default_params() -> None:
    """기본 (14,3,3)에서 SlowK/SlowD ∈ [0,100]."""
    gen = np.random.default_rng(11)
    close = _s(100 + np.cumsum(gen.normal(0, 1, 120)))
    high = close + np.abs(gen.normal(0, 0.5, 120))
    low = close - np.abs(gen.normal(0, 0.5, 120))
    slow_k, slow_d = ind.stochastic_slow(high, low, close)
    assert slow_k.dropna().between(0.0, 100.0).all()
    assert slow_d.dropna().between(0.0, 100.0).all()


# --------------------------------------------------- Williams %R (I2)


def test_williams_r_top_and_bottom_of_range_exact() -> None:
    """종가가 기간 최고가면 0, 기간 최저가면 -100."""
    close = _s(range(1, 21))
    wr_top = ind.williams_r(close, close - 1, close)  # 상승 램프에서 C=HH
    assert wr_top.iloc[:13].isna().all()
    assert (wr_top.iloc[13:] == 0.0).all()
    down = _s(range(40, 20, -1))
    wr_bottom = ind.williams_r(down + 1, down, down)  # 하락 램프에서 C=LL
    assert (wr_bottom.iloc[13:] == -100.0).all()


def test_williams_r_bounds_random() -> None:
    """랜덤워크에서 W%R ∈ [-100, 0]."""
    gen = np.random.default_rng(13)
    close = _s(100 + np.cumsum(gen.normal(0, 1, 100)))
    high = close + np.abs(gen.normal(0, 0.5, 100))
    low = close - np.abs(gen.normal(0, 0.5, 100))
    wr = ind.williams_r(high, low, close)
    assert wr.dropna().between(-100.0, 0.0).all()


# ---------------------------------------------------- Bollinger %B (I3)


def test_percent_b_alternating_exact() -> None:
    """period=2, 10↔20 교대: 밴드=15±2×5 → 상단 25/하단 5, %B는 0.75/0.25 교대."""
    pb = ind.percent_b(_s([10, 20, 10, 20, 10, 20]), period=2)
    assert math.isnan(pb.iloc[0])
    assert pb.iloc[1] == pytest.approx(0.75)
    assert pb.iloc[2] == pytest.approx(0.25)
    assert pb.iloc[3] == pytest.approx(0.75)


def test_percent_b_constant_sigma_zero_is_nan() -> None:
    """상수 시계열은 σ=0 → 밴드 폭 0 → NaN."""
    assert ind.percent_b(_s([7] * 25)).isna().all()


def test_percent_b_ramp_exact_default_window() -> None:
    """1..20 램프: σ=√((20²-1)/12)=√33.25, C-SMA=9.5 → %B = 0.5 + 9.5/(4σ)."""
    pb = ind.percent_b(_s(range(1, 21)))
    assert pb.iloc[:19].isna().all()
    assert pb.iloc[19] == pytest.approx(0.5 + 9.5 / (4 * math.sqrt(33.25)))


# ------------------------------------------------------------ CCI (I3)


def test_cci_known_small_case() -> None:
    """[1,1,1,1,6], p=5: SMA(TP)=2, MeanDev=8/5=1.6 → CCI=4/(0.015×1.6)≈166.67."""
    v = _s([1, 1, 1, 1, 6])
    c = ind.cci(v, v, v, period=5)
    assert c.iloc[:4].isna().all()
    assert c.iloc[4] == pytest.approx(4 / (0.015 * 1.6))


def test_cci_ramp_constant_value_and_flat_nan() -> None:
    """정수 램프 p=5: 항상 TP-SMA=2, MeanDev=1.2 → CCI≈111.11 일정. 플랫이면 NaN."""
    v = _s(range(1, 26))
    c = ind.cci(v, v, v, period=5)
    assert np.allclose(c.iloc[4:], 2 / (0.015 * 1.2))
    flat = _s([3] * 10)
    assert ind.cci(flat, flat, flat, period=5).isna().all()


# ------------------------------------------------------ 이격도20 (I3)


def test_disparity_exact_105() -> None:
    """SMA=100인 윈도에서 C=105 → 이격도 105."""
    d = ind.disparity(_s([100, 100, 95, 105]), period=4)
    assert d.iloc[:3].isna().all()
    assert d.iloc[3] == pytest.approx(105.0)


def test_disparity_constant_is_100_with_default_warmup() -> None:
    """상수 시계열은 C=SMA → 100, 기본 20봉 워밍업 전엔 NaN."""
    d = ind.disparity(_s([50] * 25))
    assert d.iloc[:19].isna().all()
    assert (d.iloc[19:] == 100.0).all()


# ------------------------------------------------------------ MFI (I4)


def test_mfi_all_up_is_100_and_all_down_is_0() -> None:
    """전부 상승이면 음의 플로 0 → MFI 100, 전부 하락이면 양의 플로 0 → 0."""
    vol = _s([1] * 20)
    up = _s(range(1, 21))
    m = ind.mfi(up, up, up, vol)
    assert m.iloc[:14].isna().all()
    assert (m.iloc[14:] == 100.0).all()
    down = _s(range(40, 20, -1))
    assert (ind.mfi(down, down, down, vol).iloc[14:] == 0.0).all()


def test_mfi_known_two_period_case() -> None:
    """h=l=c → TP=C. 플로: +40, -45, +100 → MFI(2) = 100×40/85, 100×100/145."""
    close = _s([10, 20, 15, 25])
    vol = _s([1, 2, 3, 4])
    m = ind.mfi(close, close, close, vol, period=2)
    assert m.iloc[:2].isna().all()
    assert m.iloc[2] == pytest.approx(100 * 40 / 85)
    assert m.iloc[3] == pytest.approx(100 * 100 / 145)


def test_mfi_flat_no_information_is_nan_and_bounds() -> None:
    """TP 변화가 전혀 없으면 양·음 플로 모두 0(정보 없음) → NaN. 랜덤에선 [0,100]."""
    flat = _s([5] * 20)
    assert ind.mfi(flat, flat, flat, _s([3] * 20)).isna().all()
    gen = np.random.default_rng(17)
    close = _s(100 + np.cumsum(gen.normal(0, 1, 100)))
    vol = _s(gen.uniform(1, 10, 100))
    m = ind.mfi(close, close, close, vol)
    assert m.dropna().between(0.0, 100.0).all()


def test_has_volume_missing_or_dead_is_false() -> None:
    """볼륨 없음·전부 0·전부 NaN·정확히 50% 0(≥50% 규칙)이면 False."""
    assert ind.has_volume(None) is False
    assert ind.has_volume(pd.Series([], dtype=float)) is False
    assert ind.has_volume(_s([0] * 60)) is False
    assert ind.has_volume(pd.Series([np.nan] * 60)) is False
    assert ind.has_volume(_s([0] * 30 + [5] * 30)) is False  # 정확히 절반이 0


def test_has_volume_live_is_true() -> None:
    """살아있는 볼륨이면 True — 짧은 시계열·과거 무볼륨(트레일링 60개 기준)도 허용."""
    assert ind.has_volume(_s([5] * 60)) is True
    assert ind.has_volume(_s([7] * 10)) is True
    assert ind.has_volume(_s([0] * 29 + [5] * 31)) is True  # 0 비율 29/60 < 50%
    assert ind.has_volume(_s([0] * 100 + [5] * 60)) is True  # 최근 60개만 본다


# ------------------------------------------------ 주봉 리샘플 (I5)


def test_resample_weekly_wfri_two_full_weeks() -> None:
    """영업일 10개 → W-FRI 2행, agg(first/max/min/last/sum) 정확값."""
    idx = pd.bdate_range("2023-01-02", periods=10)  # 월요일 시작 2주
    w = ind.resample_weekly(_ohlcv_frame(idx), crypto=False)
    assert list(w.index) == [pd.Timestamp("2023-01-06"), pd.Timestamp("2023-01-13")]
    row0, row1 = w.iloc[0], w.iloc[1]
    assert row0["open"] == 1.0 and row0["close"] == 5.25
    assert row0["high"] == 15.0 and row0["low"] == 0.5 and row0["volume"] == 5.0
    assert row1["open"] == 6.0 and row1["close"] == 10.25
    assert row1["high"] == 20.0 and row1["low"] == 5.5 and row1["volume"] == 5.0


def test_resample_weekly_crypto_wsun_calendar_days() -> None:
    """달력일 14개(크립토) → W-SUN 2행, 일요일 라벨."""
    idx = pd.date_range("2023-01-02", periods=14, freq="D")
    w = ind.resample_weekly(_ohlcv_frame(idx), crypto=True)
    assert list(w.index) == [pd.Timestamp("2023-01-08"), pd.Timestamp("2023-01-15")]
    row0, row1 = w.iloc[0], w.iloc[1]
    assert row0["open"] == 1.0 and row0["close"] == 7.25 and row0["volume"] == 7.0
    assert row0["high"] == 17.0 and row0["low"] == 0.5
    assert row1["open"] == 8.0 and row1["close"] == 14.25 and row1["volume"] == 7.0


def test_resample_weekly_incomplete_last_week_included() -> None:
    """마지막 주가 월·화 2일뿐이어도 다음 금요일 라벨로 포함된다."""
    idx = pd.bdate_range("2023-01-02", periods=12)  # 2주 + 월·화
    w = ind.resample_weekly(_ohlcv_frame(idx), crypto=False)
    assert len(w) == 3
    assert w.index[-1] == pd.Timestamp("2023-01-20")
    last = w.iloc[-1]
    assert last["open"] == 11.0 and last["close"] == 12.25 and last["volume"] == 2.0


def test_resample_weekly_drops_empty_gap_week() -> None:
    """데이터가 없는 중간 주(전 컬럼 NaN)는 제거된다."""
    idx = pd.bdate_range("2023-01-02", periods=5).append(pd.bdate_range("2023-01-16", periods=5))
    w = ind.resample_weekly(_ohlcv_frame(idx), crypto=False)
    assert list(w.index) == [pd.Timestamp("2023-01-06"), pd.Timestamp("2023-01-20")]
