"""CSV 캐시 계층 (D1) — OHLCV 데이터 계약의 저장·로드·정규화를 담당한다.

데이터 계약 (파이프라인·지표 엔진이 그대로 의존한다):
- DataFrame: index는 naive pd.DatetimeIndex(datetime64[ns], 오름차순·중복 없음),
  컬럼은 정확히 ``open, high, low, close, volume`` (모두 float64).
  무볼륨 자산은 volume이 전부 0일 수 있다.
- CSV: 헤더 ``date,open,high,low,close,volume``, 날짜는 YYYY-MM-DD, 오름차순·중복 없음.
"""

from __future__ import annotations

import os
import time
from pathlib import Path

import pandas as pd

# 계약 컬럼 (순서 고정)
OHLCV_COLUMNS: tuple[str, ...] = ("open", "high", "low", "close", "volume")

# 파이프라인이 쓰는 기본 캐시 TTL (시간) — §2.7 "TTL 12h"
DEFAULT_TTL_HOURS: float = 12.0


class FetchError(Exception):
    """데이터 수집 실패 — fetch_yf·fetch_crypto가 공유하는 데이터 계층 예외."""


def data_dir() -> Path:
    """데이터 디렉터리 경로 — env ``OO_SCAN_DATA_DIR`` 우선, 기본 ``<repo>/data/cache``."""
    env = os.environ.get("OO_SCAN_DATA_DIR")
    if env:
        return Path(env)
    return Path(__file__).resolve().parent.parent / "data" / "cache"


def cache_path(asset_id: str) -> Path:
    """자산 1종의 캐시 CSV 경로 (``{data_dir()}/{asset_id}_1d.csv``)."""
    return data_dir() / f"{asset_id}_1d.csv"


def normalize_ohlcv(df: pd.DataFrame) -> pd.DataFrame:
    """임의 형태의 OHLCV 프레임을 데이터 계약 형태로 정규화한다.

    - 인덱스: naive datetime64[ns] 자정으로 통일 (tz 제거, pandas 3의 us/ms 해상도 통일)
    - 중복 날짜는 마지막 행 우선(나중 페이지의 갱신 캔들이 이김), 오름차순 정렬
    - 컬럼: 계약 순서의 float64만 유지 (그 외 컬럼은 버림)
    """
    missing = [c for c in OHLCV_COLUMNS if c not in df.columns]
    if missing:
        raise ValueError(f"OHLCV 계약 컬럼 누락: {missing}")
    idx = pd.DatetimeIndex(pd.to_datetime(df.index))
    if idx.tz is not None:
        idx = idx.tz_localize(None)
    idx = idx.normalize().astype("datetime64[ns]")
    out = df.loc[:, list(OHLCV_COLUMNS)].astype("float64")
    out.index = idx
    out.index.name = "date"
    out = out[~out.index.duplicated(keep="last")].sort_index()
    return out


def load_ohlcv_csv(path: Path) -> pd.DataFrame:
    """계약 CSV 1개를 계약 DataFrame으로 파싱한다 (캐시·픽스처 공용 파서).

    float_precision="round_trip"으로 저장→로드 시 float64 값이 비트 단위로 보존된다.
    """
    df = pd.read_csv(path, float_precision="round_trip")
    if "date" not in df.columns:
        raise ValueError(f"{path}: 'date' 컬럼이 없다")
    df.index = pd.to_datetime(df["date"], format="%Y-%m-%d")
    return normalize_ohlcv(df)


def save_cache(asset_id: str, df: pd.DataFrame) -> Path:
    """계약 프레임을 캐시 CSV로 저장한다 (디렉터리 자동 생성). 저장 경로를 반환한다."""
    out = normalize_ohlcv(df)
    path = cache_path(asset_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    out.to_csv(path, date_format="%Y-%m-%d")
    return path


def load_cached(asset_id: str, max_age_hours: float | None = None) -> pd.DataFrame | None:
    """캐시를 읽는다. 파일이 없으면 None.

    max_age_hours가 주어지고 파일 mtime이 그보다 오래됐으면 None(신선한 재수집 필요).
    max_age_hours=None이면 나이를 무시하고 무조건 읽는다 (오프라인 모드).
    """
    path = cache_path(asset_id)
    if not path.exists():
        return None
    if max_age_hours is not None:
        age_sec = time.time() - path.stat().st_mtime
        if age_sec > max_age_hours * 3600.0:
            return None
    return load_ohlcv_csv(path)
