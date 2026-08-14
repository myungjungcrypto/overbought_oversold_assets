"""fetch_yf 테스트 (D2) — yfinance.download와 sleep을 전부 monkeypatch, 네트워크 없음."""

from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd
import pytest
import yfinance

from oo_scan import fetch_yf as mod
from oo_scan.cache import OHLCV_COLUMNS
from oo_scan.fetch_yf import FetchError, fetch_yf


def _yf_multiindex_frame(n: int = 10, tz: str | None = None) -> pd.DataFrame:
    """실제 yfinance 응답 모양(MultiIndex 컬럼 + Adj Close)을 재현한다."""
    idx = pd.date_range("2026-01-05", periods=n, freq="B", tz=tz)
    fields = ["Open", "High", "Low", "Close", "Adj Close", "Volume"]
    cols = pd.MultiIndex.from_product([fields, ["^GSPC"]], names=["Price", "Ticker"])
    base = np.arange(n, dtype="float64")
    data = {
        ("Open", "^GSPC"): 100.0 + base,
        ("High", "^GSPC"): 102.0 + base,
        ("Low", "^GSPC"): 99.0 + base,
        ("Close", "^GSPC"): 101.0 + base,
        ("Adj Close", "^GSPC"): 55.0 + base,  # 계약에 없어야 하는 값
        ("Volume", "^GSPC"): 1000.0 + base,
    }
    return pd.DataFrame(data, index=idx, columns=cols)


@pytest.fixture(autouse=True)
def no_short_augment(monkeypatch: pytest.MonkeyPatch) -> None:
    """기본은 짧은 응답 보강을 끈다 — 기존 테스트의 호출 수·sleep 시퀀스 보존.

    보강 경로 테스트는 _MIN_EXPECTED_ROWS를 직접 되살린다.
    """
    monkeypatch.setattr(mod, "_MIN_EXPECTED_ROWS", 0)


@pytest.fixture()
def sleeps(monkeypatch: pytest.MonkeyPatch) -> list[float]:
    """_sleep 호출을 기록만 하고 실제로 기다리지 않는다."""
    calls: list[float] = []
    monkeypatch.setattr(mod, "_sleep", calls.append)
    return calls


def _patch_download(monkeypatch: pytest.MonkeyPatch, fn: Any) -> list[dict]:
    """yfinance.download를 가짜로 바꾸고 kwargs 기록 리스트를 돌려준다."""
    calls: list[dict] = []

    def fake_download(*args: Any, **kwargs: Any) -> Any:
        calls.append(kwargs)
        return fn(*args, **kwargs)

    monkeypatch.setattr(yfinance, "download", fake_download)
    return calls


def test_success_normalizes_contract(
    monkeypatch: pytest.MonkeyPatch, sleeps: list[float]
) -> None:
    """MultiIndex 응답이 계약 프레임으로 정규화된다 (Adj Close 제외, NaN close 제거)."""
    raw = _yf_multiindex_frame(10)
    raw.iloc[3, raw.columns.get_loc(("Close", "^GSPC"))] = np.nan  # NaN close 행은 제거돼야
    calls = _patch_download(monkeypatch, lambda *a, **k: raw)

    df = fetch_yf("^GSPC")

    assert list(df.columns) == list(OHLCV_COLUMNS)
    assert all(str(dt) == "float64" for dt in df.dtypes)
    assert str(df.index.dtype) == "datetime64[ns]" and df.index.tz is None
    assert df.index.is_monotonic_increasing and df.index.is_unique
    assert len(df) == 9  # NaN close 1행 제거
    assert df["close"].iloc[0] == 101.0  # Adj Close(55.0)가 아닌 Close
    assert len(calls) == 1
    assert calls[0]["period"] == "4y" and calls[0]["interval"] == "1d"
    assert calls[0]["auto_adjust"] is False and calls[0]["progress"] is False
    assert sleeps == [0.7]  # 호출 전 대기 1회뿐


def test_retry_then_success(monkeypatch: pytest.MonkeyPatch, sleeps: list[float]) -> None:
    """1회차 빈 응답 → 1s 백오프 후 2회차 성공."""
    good = _yf_multiindex_frame(5)
    results = [pd.DataFrame(), good]
    calls = _patch_download(monkeypatch, lambda *a, **k: results.pop(0))

    df = fetch_yf("^GSPC")

    assert len(df) == 5
    assert len(calls) == 2
    assert sleeps == [0.7, 1.0, 0.7]


def test_all_retries_empty_raises(
    monkeypatch: pytest.MonkeyPatch, sleeps: list[float]
) -> None:
    """계속 빈 응답이면 4회(최초+재시도 3회) 후 FetchError."""
    calls = _patch_download(monkeypatch, lambda *a, **k: pd.DataFrame())

    with pytest.raises(FetchError, match="\\^GSPC"):
        fetch_yf("^GSPC")

    assert len(calls) == 4
    assert sleeps == [0.7, 1.0, 0.7, 2.0, 0.7, 4.0, 0.7]  # 백오프 1s→2s→4s


def test_none_and_exception_raise_fetcherror(
    monkeypatch: pytest.MonkeyPatch, sleeps: list[float]
) -> None:
    """None 응답·예외도 재시도 대상이고 끝내 실패하면 FetchError."""
    results: list[Any] = [None, RuntimeError("rate limited"), None, None]

    def flaky(*a: Any, **k: Any) -> Any:
        r = results.pop(0)
        if isinstance(r, Exception):
            raise r
        return r

    calls = _patch_download(monkeypatch, flaky)
    with pytest.raises(FetchError, match="yfinance 수집 실패"):
        fetch_yf("GC=F")
    assert len(calls) == 4


def test_typeerror_kwargs_fallback(
    monkeypatch: pytest.MonkeyPatch, sleeps: list[float]
) -> None:
    """바뀐 kwargs로 TypeError가 나면 선택 kwargs 없이 즉시 재호출한다 (yfinance 방어)."""
    raw = _yf_multiindex_frame(5)

    def picky(*a: Any, **k: Any) -> pd.DataFrame:
        if "auto_adjust" in k or "progress" in k:
            raise TypeError("unexpected keyword argument")
        return raw

    calls = _patch_download(monkeypatch, picky)
    df = fetch_yf("^GSPC")

    assert len(df) == 5
    assert len(calls) == 2  # 같은 attempt 안에서 2번째 호출로 성공
    assert "auto_adjust" not in calls[1] and "progress" not in calls[1]
    assert sleeps == [0.7]  # 백오프 없이 성공


def test_single_level_case_insensitive_columns(
    monkeypatch: pytest.MonkeyPatch, sleeps: list[float]
) -> None:
    """단일 레벨·대소문자 뒤섞인 컬럼도 정규화된다."""
    idx = pd.date_range("2026-02-02", periods=4, freq="B")
    raw = pd.DataFrame(
        {
            "OPEN": [1.0, 2.0, 3.0, 4.0],
            "high": [2.0, 3.0, 4.0, 5.0],
            "Low": [0.5, 1.5, 2.5, 3.5],
            "cLoSe": [1.5, 2.5, 3.5, 4.5],
            "Adj Close": [9.0, 9.0, 9.0, 9.0],
            "Volume": [10.0, 20.0, 30.0, 40.0],
        },
        index=idx,
    )
    _patch_download(monkeypatch, lambda *a, **k: raw)

    df = fetch_yf("^KS11")
    assert list(df.columns) == list(OHLCV_COLUMNS)
    assert df["close"].tolist() == [1.5, 2.5, 3.5, 4.5]
    assert df["volume"].tolist() == [10.0, 20.0, 30.0, 40.0]


def test_missing_volume_fills_zero_and_tz_stripped(
    monkeypatch: pytest.MonkeyPatch, sleeps: list[float]
) -> None:
    """volume이 없으면 0으로 채우고, tz-aware 인덱스는 naive로 바꾼다."""
    idx = pd.date_range("2026-03-02", periods=3, freq="B", tz="America/New_York")
    raw = pd.DataFrame(
        {"Open": [1.0, 2.0, 3.0], "High": [2.0, 3.0, 4.0],
         "Low": [0.5, 1.5, 2.5], "Close": [1.5, 2.5, 3.5]},
        index=idx,
    )
    _patch_download(monkeypatch, lambda *a, **k: raw)

    df = fetch_yf("DX-Y.NYB")
    assert df.index.tz is None
    assert (df["volume"] == 0.0).all()


def test_short_period_response_augmented_by_start(
    monkeypatch: pytest.MonkeyPatch, sleeps: list[float]
) -> None:
    """period 응답이 짧으면(^TNX 회귀) start= 재요청으로 보강한다 (2026-08-13 실측 회귀 테스트)."""
    monkeypatch.setattr(mod, "_MIN_EXPECTED_ROWS", 250)
    short = _yf_multiindex_frame(30)
    full = _yf_multiindex_frame(400)

    def route(*a: Any, **k: Any) -> pd.DataFrame:
        return full if "start" in k else short

    calls = _patch_download(monkeypatch, route)
    df = fetch_yf("^TNX")

    assert len(df) == 400  # 보강 결과 채택
    assert any("start" in k for k in calls)  # start= 재요청이 실제로 발생
    assert calls[0].get("period") == "4y"


def test_short_response_kept_when_augment_fails(
    monkeypatch: pytest.MonkeyPatch, sleeps: list[float]
) -> None:
    """보강도 전부 짧으면 원본 짧은 응답을 그대로 반환한다 (등급 가드는 파이프라인 소관)."""
    monkeypatch.setattr(mod, "_MIN_EXPECTED_ROWS", 250)
    short = _yf_multiindex_frame(30)
    shorter = _yf_multiindex_frame(10)

    def route(*a: Any, **k: Any) -> pd.DataFrame:
        return short if "period" in k and k["period"] == "4y" else shorter

    _patch_download(monkeypatch, route)
    df = fetch_yf("^TYX")
    assert len(df) == 30  # 예외 없이 원본 유지


def test_augment_trims_period_max_to_4y(
    monkeypatch: pytest.MonkeyPatch, sleeps: list[float]
) -> None:
    """period=max가 수십 년치를 줘도 4y 수준(_MAX_ROWS)으로 절단한다."""
    monkeypatch.setattr(mod, "_MIN_EXPECTED_ROWS", 250)
    short = _yf_multiindex_frame(30)
    huge = _yf_multiindex_frame(3000)

    def route(*a: Any, **k: Any) -> pd.DataFrame:
        if k.get("period") == "max":
            return huge
        if "start" in k:
            return _yf_multiindex_frame(5)
        return short

    _patch_download(monkeypatch, route)
    df = fetch_yf("^TNX")
    assert len(df) == mod._MAX_ROWS
