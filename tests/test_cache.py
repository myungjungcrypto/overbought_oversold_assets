"""cache.py 테스트 (D1) — 라운드트립·TTL·경로 오버라이드·파서 정규화. 네트워크 없음."""

from __future__ import annotations

import os
import time
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from oo_scan import cache


def _contract_df(n: int = 5) -> pd.DataFrame:
    """이진 표현이 딱 안 떨어지는 값을 섞은 계약 프레임 (라운드트립 정밀도 검증용)."""
    idx = pd.date_range("2026-01-01", periods=n, freq="D")
    base = np.linspace(100.0, 110.0, n) + 1.0 / 3.0
    df = pd.DataFrame(
        {
            "open": base + 0.1,
            "high": base + 2.0,
            "low": base - 2.0,
            "close": base + (0.1 + 0.2),
            "volume": np.linspace(1e6, 2e6, n) + 0.7,
        },
        index=idx,
    )
    df.index.name = "date"
    return df


@pytest.fixture()
def tmp_data_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """OO_SCAN_DATA_DIR을 임시 디렉터리로 돌려 리포 데이터를 오염시키지 않는다."""
    monkeypatch.setenv("OO_SCAN_DATA_DIR", str(tmp_path))
    return tmp_path


def test_data_dir_env_override(tmp_data_dir: Path) -> None:
    """OO_SCAN_DATA_DIR가 설정되면 그 경로를 쓴다."""
    assert cache.data_dir() == tmp_data_dir
    assert cache.cache_path("BTC") == tmp_data_dir / "BTC_1d.csv"


def test_data_dir_default(monkeypatch: pytest.MonkeyPatch) -> None:
    """env가 없으면 리포 루트의 data/cache가 기본이다 (생성은 저장 시점)."""
    monkeypatch.delenv("OO_SCAN_DATA_DIR", raising=False)
    d = cache.data_dir()
    assert d.parts[-2:] == ("data", "cache")
    assert d.parent.parent == Path(cache.__file__).resolve().parent.parent


def test_roundtrip_save_load_exact(tmp_data_dir: Path) -> None:
    """save→load 라운드트립은 값·인덱스·dtype이 정확히 보존된다."""
    df = _contract_df()
    path = cache.save_cache("BTC", df)
    assert path == tmp_data_dir / "BTC_1d.csv"
    assert path.exists()
    header = path.read_text(encoding="utf-8").splitlines()[0]
    assert header == "date,open,high,low,close,volume"

    loaded = cache.load_cached("BTC")
    assert loaded is not None
    # 계약 형태: 컬럼·dtype·인덱스
    assert list(loaded.columns) == list(cache.OHLCV_COLUMNS)
    assert all(str(dt) == "float64" for dt in loaded.dtypes)
    assert str(loaded.index.dtype) == "datetime64[ns]"
    assert loaded.index.tz is None
    # 값이 비트 단위로 동일 (float_precision="round_trip")
    for col in cache.OHLCV_COLUMNS:
        assert np.array_equal(loaded[col].to_numpy(), df[col].to_numpy())
    pd.testing.assert_frame_equal(loaded, cache.normalize_ohlcv(df))


def test_load_cached_missing_returns_none(tmp_data_dir: Path) -> None:
    """캐시 파일이 없으면 None."""
    assert cache.load_cached("NOPE") is None


def test_load_cached_ttl_by_mtime(tmp_data_dir: Path) -> None:
    """mtime이 TTL보다 오래되면 None, TTL=None이면 나이 무시하고 로드."""
    path = cache.save_cache("ETH", _contract_df())
    old = time.time() - 13 * 3600
    os.utime(path, (old, old))

    assert cache.load_cached("ETH", max_age_hours=12.0) is None  # 13h > 12h → 재수집 필요
    assert cache.load_cached("ETH", max_age_hours=None) is not None  # 오프라인: 나이 무시

    fresh = time.time() - 1 * 3600
    os.utime(path, (fresh, fresh))
    assert cache.load_cached("ETH", max_age_hours=12.0) is not None  # 1h < 12h → 신선


def test_load_ohlcv_csv_sorts_and_dedupes(tmp_path: Path) -> None:
    """공용 파서는 순서 뒤섞임·중복 날짜(마지막 우선)를 계약 형태로 정규화한다."""
    p = tmp_path / "X_1d.csv"
    p.write_text(
        "date,open,high,low,close,volume\n"
        "2026-01-03,3,4,2,3.5,30\n"
        "2026-01-01,1,2,0.5,1.5,10\n"
        "2026-01-02,2,3,1,2.5,20\n"
        "2026-01-02,2,3,1,9.9,21\n",  # 중복 날짜 — 뒤 행이 이겨야 한다
        encoding="utf-8",
    )
    df = cache.load_ohlcv_csv(p)
    assert list(df.index) == list(pd.to_datetime(["2026-01-01", "2026-01-02", "2026-01-03"]))
    assert df.index.is_monotonic_increasing and df.index.is_unique
    assert df.loc[pd.Timestamp("2026-01-02"), "close"] == 9.9


def test_load_ohlcv_csv_rejects_bad_schema(tmp_path: Path) -> None:
    """date 컬럼이나 계약 컬럼이 빠진 CSV는 ValueError."""
    no_date = tmp_path / "a.csv"
    no_date.write_text("open,high,low,close,volume\n1,2,0,1,5\n", encoding="utf-8")
    with pytest.raises(ValueError, match="date"):
        cache.load_ohlcv_csv(no_date)

    no_volume = tmp_path / "b.csv"
    no_volume.write_text("date,open,high,low,close\n2026-01-01,1,2,0,1\n", encoding="utf-8")
    with pytest.raises(ValueError, match="누락"):
        cache.load_ohlcv_csv(no_volume)
