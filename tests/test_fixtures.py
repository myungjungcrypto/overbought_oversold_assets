"""픽스처 계약 검증 (D4) — 모든 픽스처가 공용 파서로 로드되고 데이터 계약을 만족한다.

재생성 결정성(바이트 일치)은 pytest가 아니라 M1 수락 기준의
``python scripts/make_fixtures.py && git diff --exit-code tests/fixtures``가 담당한다.
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest

from oo_scan.cache import OHLCV_COLUMNS, load_ohlcv_csv

FIXTURES_DIR = Path(__file__).resolve().parent / "fixtures"

ALL_IDS = ("BTC", "ETH", "SPX", "KOSPI", "US10Y", "HYPE")
EXACT_ROWS = {"BTC": 1460, "ETH": 1460, "HYPE": 220}  # 달력일 자산
MIN_ROWS = {"SPX": 1000, "KOSPI": 1000, "US10Y": 1000}  # 영업일 자산 (~1100봉)
CRYPTO_IDS = ("BTC", "ETH", "HYPE")
BUSINESS_IDS = ("SPX", "KOSPI", "US10Y")


def _load(asset_id: str) -> pd.DataFrame:
    return load_ohlcv_csv(FIXTURES_DIR / f"{asset_id}_1d.csv")


@pytest.mark.parametrize("asset_id", ALL_IDS)
def test_fixture_satisfies_contract(asset_id: str) -> None:
    """컬럼·dtype·인덱스·OHLC 부등식·비음수 볼륨·NaN 없음."""
    df = _load(asset_id)
    assert list(df.columns) == list(OHLCV_COLUMNS)
    assert all(str(dt) == "float64" for dt in df.dtypes)
    assert isinstance(df.index, pd.DatetimeIndex)
    assert df.index.tz is None
    assert df.index.is_monotonic_increasing and df.index.is_unique
    assert not df.isna().any().any()
    assert (df["high"] >= df["low"]).all()
    assert (df["high"] >= df["open"]).all() and (df["high"] >= df["close"]).all()
    assert (df["low"] <= df["open"]).all() and (df["low"] <= df["close"]).all()
    assert (df["close"] > 0).all()
    assert (df["volume"] >= 0).all()


def test_row_counts() -> None:
    """BTC/ETH 1460봉, HYPE 220봉(데이터 부족 케이스), 영업일 자산 1000봉 이상."""
    for asset_id, expected in EXACT_ROWS.items():
        assert len(_load(asset_id)) == expected, asset_id
    for asset_id, minimum in MIN_ROWS.items():
        assert len(_load(asset_id)) >= minimum, asset_id


def test_us10y_is_volumeless_others_not() -> None:
    """US10Y는 volume 전부 0 (무볼륨 자산), BTC는 실제 볼륨이 있다."""
    assert (_load("US10Y")["volume"] == 0.0).all()
    assert (_load("BTC")["volume"] > 0.0).all()


@pytest.mark.parametrize("asset_id", CRYPTO_IDS)
def test_crypto_is_daily_continuous(asset_id: str) -> None:
    """크립토는 24/7 — 달력일 연속이고 END_DATE(2026-08-01)에 끝난다."""
    df = _load(asset_id)
    diffs = df.index.to_series().diff().dropna()
    assert (diffs == pd.Timedelta(days=1)).all()
    assert df.index[-1] == pd.Timestamp("2026-08-01")


@pytest.mark.parametrize("asset_id", BUSINESS_IDS)
def test_business_assets_weekdays_only(asset_id: str) -> None:
    """영업일 자산은 주말 봉이 없고 END_DATE 직전 금요일(2026-07-31)에 끝난다."""
    df = _load(asset_id)
    assert (df.index.dayofweek < 5).all()
    assert df.index[-1] == pd.Timestamp("2026-07-31")


@pytest.mark.parametrize("asset_id", ALL_IDS)
def test_raw_csv_on_disk_shape(asset_id: str) -> None:
    """디스크 형식 계약: 헤더·YYYY-MM-DD·오름차순·중복 없음 (파서 정규화에 기대지 않는 검사)."""
    lines = (FIXTURES_DIR / f"{asset_id}_1d.csv").read_text(encoding="utf-8").splitlines()
    assert lines[0] == "date,open,high,low,close,volume"
    dates = [ln.split(",", 1)[0] for ln in lines[1:]]
    assert all(len(d) == 10 and d[4] == "-" and d[7] == "-" for d in dates)
    assert dates == sorted(dates)
    assert len(dates) == len(set(dates))
