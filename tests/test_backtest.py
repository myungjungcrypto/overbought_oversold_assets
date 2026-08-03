"""백테스트 코어(K1) 테스트 — AUTOPILOT §2.6.

네트워크·파일 쓰기 없음. 손계산 시계열과 합성 프레임, 픽스처 읽기 전용만 사용한다.
정확값 검증은 온도 시계열을 monkeypatch로 주입해 이벤트·수익률을 손으로 설계한다.
"""

from __future__ import annotations

import math
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from oo_scan import backtest as bt
from oo_scan import cache, indicators
from oo_scan.cli import main

FIXTURES = Path(__file__).parent / "fixtures"


def _make_df(close: pd.Series) -> pd.DataFrame:
    """close 시계열로 최소 OHLCV 계약 프레임을 만든다 (o=h=l=c, volume=1)."""
    return pd.DataFrame(
        {"open": close, "high": close, "low": close, "close": close, "volume": 1.0},
        index=close.index,
    )


def _patch_total(monkeypatch: pytest.MonkeyPatch, total: pd.Series) -> None:
    """score.total_temperature_series를 하드코딩된 온도 시계열로 대체한다."""
    monkeypatch.setattr(bt.score, "total_temperature_series", lambda df, crypto, use_mfi: total)


# ------------------------------------------------------- extract_events


def test_extract_events_hand_built_series() -> None:
    """손계산 시계열: 소외 진입 2건(idx 2·5), 깊은 소외 1건(idx 6), 과열 2건(idx 8·10)."""
    vals = [0.0, -10.0, -31.0, -40.0, -25.0, -35.0, -61.0, -10.0, 31.0, 29.0, 35.0]
    idx = pd.bdate_range("2024-01-01", periods=len(vals))
    ev = bt.extract_events(pd.Series(vals, index=idx))
    assert set(ev) == set(bt.EVENT_LABELS)
    assert list(ev[bt.LABEL_NEGLECTED]) == [idx[2], idx[5]]
    # idx 6은 직전 봉이 이미 ≤ -30이라 소외 진입은 아니고 깊은 소외 진입만이다
    assert list(ev[bt.LABEL_DEEP_NEGLECTED]) == [idx[6]]
    assert list(ev[bt.LABEL_OVERHEATED]) == [idx[8], idx[10]]


def test_extract_events_nan_prefix_and_boundary_values() -> None:
    """워밍업 NaN 직후 첫 값은 이벤트가 아니고, 경계값 -30/30은 극단 쪽에 포함된다."""
    vals = [np.nan, np.nan, -40.0, -20.0, -30.0, 29.0, 30.0]
    idx = pd.bdate_range("2024-02-01", periods=len(vals))
    ev = bt.extract_events(pd.Series(vals, index=idx))
    assert list(ev[bt.LABEL_NEGLECTED]) == [idx[4]]  # -20 → -30 (경계 포함)
    assert list(ev[bt.LABEL_OVERHEATED]) == [idx[6]]  # 29 → 30 (경계 포함)
    assert len(ev[bt.LABEL_DEEP_NEGLECTED]) == 0


def test_extract_events_single_bar_crosses_both_thresholds() -> None:
    """중립에서 -70으로 급락한 봉은 소외 진입과 깊은 소외 진입에 각각 집계된다."""
    vals = [0.0, -70.0, 0.0, -70.0]
    idx = pd.bdate_range("2024-03-01", periods=len(vals))
    ev = bt.extract_events(pd.Series(vals, index=idx))
    assert list(ev[bt.LABEL_NEGLECTED]) == [idx[1], idx[3]]
    assert list(ev[bt.LABEL_DEEP_NEGLECTED]) == [idx[1], idx[3]]
    assert len(ev[bt.LABEL_OVERHEATED]) == 0  # -70 → 0 복귀는 이벤트가 아니다


# ------------------------------------------------------ forward_returns


def test_forward_returns_exact_fractions_and_tail_nan() -> None:
    """기하 수열 종가에서 h=1/2 전방 수익률 정확값, 끝단 h봉 이내는 NaN."""
    idx = pd.bdate_range("2024-01-01", periods=4)
    close = pd.Series([100.0, 110.0, 121.0, 133.1], index=idx)
    r1 = bt.forward_returns(close, idx, horizon=1)
    assert list(r1.index) == list(idx)
    assert list(r1.iloc[:3]) == pytest.approx([0.10, 0.10, 0.10])
    assert math.isnan(r1.iloc[3])  # 마지막 봉: t+1 없음
    r2 = bt.forward_returns(close, pd.DatetimeIndex([idx[0], idx[2], idx[3]]), horizon=2)
    assert r2.iloc[0] == pytest.approx(0.21)  # 121/100 - 1
    assert math.isnan(r2.iloc[1]) and math.isnan(r2.iloc[2])


# --------------------------------------- backtest_asset 정확값 (온도 주입)


def test_backtest_asset_engineered_exact_stats(monkeypatch: pytest.MonkeyPatch) -> None:
    """이벤트 수익률 [+10%, -5%, +20%, 0%, -10%]를 설계해 평균·적중률·베이스라인 정확값 검증.

    상수 100 종가에 이벤트 21봉 뒤에만 범프를 심었다. h=21 전방 수익률이 0이 아닌
    봉은 이벤트 5개(t=10..50)와 그 에코(범프 봉 자신, t=31..71)뿐이라 베이스라인을
    손으로 합산할 수 있다. 0% 수익률은 미적중(엄격 부등호) 검증용이다.
    """
    n = 100
    idx = pd.bdate_range("2022-01-03", periods=n)
    close = np.full(n, 100.0)
    # 이벤트 t ∈ {10,20,30,40,50} → close[t+21] 범프로 전방 수익률 설계
    close[31], close[41], close[51], close[61], close[71] = 110.0, 95.0, 120.0, 100.0, 90.0
    df = _make_df(pd.Series(close, index=idx))
    total = np.zeros(n)
    total[[10, 20, 30, 40, 50]] = -35.0  # 각 이벤트 직전 봉은 0 → 소외 진입 5건
    _patch_total(monkeypatch, pd.Series(total, index=idx))

    stats = bt.backtest_asset(df, crypto=False, use_mfi=True)
    by = {(s.label, s.horizon): s for s in stats}

    cold = by[(bt.LABEL_NEGLECTED, 21)]
    event_returns = [0.10, -0.05, 0.20, 0.0, -0.10]
    echo_returns = [100 / 110 - 1, 100 / 95 - 1, 100 / 120 - 1, 0.0, 100 / 90 - 1]
    assert cold.n_events == 5
    assert cold.insufficient is False  # 표본 5개 경계 → 부족 아님
    assert cold.avg_return == pytest.approx(sum(event_returns) / 5)  # 0.03
    assert cold.hit_rate == pytest.approx(2 / 5)  # 0%는 미적중
    assert cold.baseline == pytest.approx((sum(event_returns) + sum(echo_returns)) / (n - 21))

    # h=63: t+63 < 100 인 이벤트는 t=10,20,30뿐 → 끝단 이벤트 2건은 표본에서 제외
    cold63 = by[(bt.LABEL_NEGLECTED, 63)]
    assert cold63.n_events == 3
    assert cold63.insufficient is True
    assert cold63.avg_return == pytest.approx(0.0)  # close[73]=close[83]=close[93]=100

    # 이벤트 0건 유형: 평균·적중률 NaN, 표본 부족, 베이스라인은 그대로 산출
    hot = by[(bt.LABEL_OVERHEATED, 21)]
    assert hot.n_events == 0
    assert math.isnan(hot.avg_return) and math.isnan(hot.hit_rate)
    assert hot.insufficient is True
    assert hot.baseline == pytest.approx(cold.baseline)

    # h=126 > 봉 수: 전방 수익률이 정의된 봉이 없어 베이스라인도 NaN
    assert math.isnan(by[(bt.LABEL_NEGLECTED, 126)].baseline)
    assert by[(bt.LABEL_NEGLECTED, 126)].n_events == 0


def test_backtest_asset_geometric_hit_rate_directions(monkeypatch: pytest.MonkeyPatch) -> None:
    """일정 상승률 g의 기하 종가: 전 구간 전방 수익률 = g^h - 1 = 베이스라인.

    소외류 적중률은 1.0(전부 양수), 과열 적중률은 0.0(음수 없음)이어야 한다 —
    적중 방향이 라벨에 따라 반대임을 검증한다.
    """
    n = 250
    g = 1.001
    idx = pd.bdate_range("2021-01-04", periods=n)
    df = _make_df(pd.Series(100.0 * g ** np.arange(n), index=idx))
    total = np.zeros(n)
    total[[10, 20, 30, 40, 50]] = -35.0  # 소외 진입 5건
    total[90] = -70.0  # 깊은 소외 1건 + 소외 진입 동시 집계 → 소외 6건
    total[[60, 70, 80]] = 35.0  # 과열 진입 3건
    _patch_total(monkeypatch, pd.Series(total, index=idx))

    stats = bt.backtest_asset(df, crypto=False, use_mfi=True)
    assert len(stats) == 9
    by = {(s.label, s.horizon): s for s in stats}
    for h in bt.HORIZONS:  # 최대 이벤트 t=90, 90+126 < 250 → 전 이벤트 실현
        expected = g**h - 1.0
        cold = by[(bt.LABEL_NEGLECTED, h)]
        assert cold.n_events == 6 and cold.insufficient is False
        assert cold.avg_return == pytest.approx(expected)
        assert cold.hit_rate == 1.0
        assert cold.baseline == pytest.approx(expected)
        deep = by[(bt.LABEL_DEEP_NEGLECTED, h)]
        assert deep.n_events == 1 and deep.insufficient is True
        assert deep.hit_rate == 1.0
        hot = by[(bt.LABEL_OVERHEATED, h)]
        assert hot.n_events == 3 and hot.insufficient is True
        assert hot.avg_return == pytest.approx(expected)  # 수익률은 같지만
        assert hot.hit_rate == 0.0  # 하락 적중은 0


def test_insufficient_boundary_four_true_five_false(monkeypatch: pytest.MonkeyPatch) -> None:
    """표본 부족 경계: 이벤트 4건 → insufficient True, 5건 → False (§2.6)."""
    n = 60
    idx = pd.bdate_range("2023-01-02", periods=n)
    df = _make_df(pd.Series(np.linspace(100.0, 110.0, n), index=idx))

    def run(positions: list[int]) -> bt.EventStats:
        total = np.zeros(n)
        total[positions] = -35.0  # 모두 t+21 < 60 → 전방 수익률 전건 실현
        _patch_total(monkeypatch, pd.Series(total, index=idx))
        stats = bt.backtest_asset(df, crypto=False, use_mfi=True)
        return {(s.label, s.horizon): s for s in stats}[(bt.LABEL_NEGLECTED, 21)]

    four = run([2, 4, 6, 8])
    assert four.n_events == 4 and four.insufficient is True
    five = run([2, 4, 6, 8, 10])
    assert five.n_events == 5 and five.insufficient is False


# ----------------------------------------- 통합 (실제 온도 엔진, 합성 프레임)


def test_backtest_asset_integration_synthetic_frame() -> None:
    """900봉 사인+추세 합성 프레임(고정 시드): 실제 엔진으로 9칸 산출, 소외 진입 발생."""
    n = 900
    rs = np.random.RandomState(7)
    t = np.arange(n)
    log_p = (
        np.log(100.0)
        + 0.45 * np.sin(2.0 * np.pi * t / 300.0)  # 큰 파동으로 온도가 ±30을 넘도록
        + 0.0003 * t
        + rs.normal(0.0, 0.006, n).cumsum()
    )
    close = pd.Series(np.exp(log_p), index=pd.bdate_range("2021-01-04", periods=n))
    df = pd.DataFrame(
        {
            "open": close.shift(1).fillna(close.iloc[0]),
            "high": close * 1.004,
            "low": close * 0.996,
            "close": close,
            "volume": pd.Series(1000.0 + 50.0 * rs.rand(n), index=close.index),
        }
    )

    stats = bt.backtest_asset(df, crypto=False, use_mfi=True)
    assert len(stats) == 9
    assert {(s.label, s.horizon) for s in stats} == {
        (label, h) for label in bt.EVENT_LABELS for h in bt.HORIZONS
    }
    by = {(s.label, s.horizon): s for s in stats}
    assert by[(bt.LABEL_NEGLECTED, 21)].n_events >= 1  # 소외 진입이 실제로 발생
    for s in stats:
        assert math.isfinite(s.baseline)  # 900봉 ≫ 126 → 베이스라인 항상 정의
        assert s.insufficient is (s.n_events < bt.MIN_EVENTS)
        if s.n_events > 0:
            assert math.isfinite(s.avg_return)
            assert 0.0 <= s.hit_rate <= 1.0
    for label in bt.EVENT_LABELS:  # 끝단 제외로 긴 호라이즌 표본은 늘 수 없다
        assert by[(label, 126)].n_events <= by[(label, 21)].n_events


# -------------------------------------------------- 픽스처 스모크 (읽기 전용)


def test_backtest_btc_fixture_smoke() -> None:
    """BTC 픽스처(1460봉) 엔드투엔드: 9칸 전부 필드가 온전해야 한다."""
    df = cache.load_ohlcv_csv(FIXTURES / "BTC_1d.csv")
    stats = bt.backtest_asset(df, crypto=True, use_mfi=indicators.has_volume(df["volume"]))
    assert len(stats) == 9
    for s in stats:
        assert s.label in bt.EVENT_LABELS and s.horizon in bt.HORIZONS
        assert math.isfinite(s.baseline)
        assert s.n_events >= 0
        assert s.insufficient is (s.n_events < bt.MIN_EVENTS)
        if s.n_events == 0:
            assert math.isnan(s.avg_return) and math.isnan(s.hit_rate)
        else:
            assert math.isfinite(s.avg_return)
            assert 0.0 <= s.hit_rate <= 1.0


# ------------------------------------------------------------ CLI


def test_cmd_backtest_importable_and_empty_env_returns_one(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """cli.py가 임포트하는 cmd_backtest가 유지되고, 데이터 없으면 exit 1 (K2)."""
    from oo_scan.backtest import cmd_backtest

    assert callable(cmd_backtest)
    monkeypatch.setenv("OO_SCAN_DATA_DIR", str(tmp_path / "empty"))
    monkeypatch.chdir(tmp_path)
    assert main(["backtest", "--offline"]) == 1
    assert "백테스트" in capsys.readouterr().out
