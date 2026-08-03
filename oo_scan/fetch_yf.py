"""yfinance 일봉 페처 (D2) — 단일 티커·period 4y·컬럼 정규화·지수 백오프 재시도.

§6 리스크 대응: 단일 티커 호출 + auto_adjust 명시 + MultiIndex 평탄화,
호출 전 sleep 0.7s, 실패(예외·빈 응답) 시 1s→2s→4s 백오프로 최대 3회 재시도.
"""

from __future__ import annotations

import time

import pandas as pd
import yfinance as yf

from oo_scan.cache import FetchError, normalize_ohlcv

__all__ = ["FetchError", "fetch_yf"]

# 테스트에서 monkeypatch 하는 간접 sleep (레이트리밋 대기·백오프 공용)
_sleep = time.sleep

# 네트워크 호출 직전 대기 (초) — yfinance 레이트리밋 완화
_PRE_CALL_SLEEP = 0.7

# 재시도 백오프 (초) — 최초 1회 + 재시도 3회 = 최대 4회 호출
_RETRY_DELAYS: tuple[float, ...] = (1.0, 2.0, 4.0)

# volume은 없으면 0으로 채우므로 필수 목록에서 제외
_REQUIRED_COLUMNS = ("open", "high", "low", "close")


def _download(symbol: str, period: str) -> pd.DataFrame | None:
    """yf.download 1회 호출. 버전 차이로 선택 kwargs가 거부되면(TypeError) 빼고 재호출."""
    try:
        return yf.download(
            symbol, period=period, interval="1d", auto_adjust=False, progress=False
        )
    except TypeError:
        # yfinance 1.x 방어: 선택 kwargs(auto_adjust/progress)가 사라진 경우 최소 인자로
        return yf.download(symbol, period=period, interval="1d")


def _flatten_columns(df: pd.DataFrame) -> pd.DataFrame:
    """MultiIndex 컬럼을 가격 필드명 레벨로 평탄화한다 (단일 티커 전제).

    yfinance 버전에 따라 (필드, 티커) 또는 (티커, 필드) 순서가 달라
    'close'가 들어 있는 레벨을 찾아 쓴다.
    """
    if not isinstance(df.columns, pd.MultiIndex):
        return df
    chosen = 0
    for level in range(df.columns.nlevels):
        values = {str(v).strip().lower() for v in df.columns.get_level_values(level)}
        if "close" in values:
            chosen = level
            break
    out = df.copy()
    out.columns = df.columns.get_level_values(chosen)
    return out


def _normalize(df: pd.DataFrame) -> pd.DataFrame:
    """yfinance 응답을 데이터 계약 프레임으로 정규화한다.

    대소문자 무시 매칭으로 open/high/low/close/volume만 취하고 ('Adj Close'는 버림),
    close가 NaN인 행을 제거한 뒤 naive 일자 인덱스로 맞춘다.
    """
    df = _flatten_columns(df)
    by_lower: dict[str, object] = {}
    for col in df.columns:
        key = str(col).strip().lower()
        by_lower.setdefault(key, col)  # 중복 시 첫 컬럼 우선
    missing = [c for c in _REQUIRED_COLUMNS if c not in by_lower]
    if missing:
        raise FetchError(f"yfinance 응답 컬럼 누락: {missing}")
    out = pd.DataFrame({c: df[by_lower[c]] for c in _REQUIRED_COLUMNS})
    out["volume"] = df[by_lower["volume"]] if "volume" in by_lower else 0.0
    out = out.dropna(subset=["close"])
    return normalize_ohlcv(out)


def fetch_yf(symbol: str, period: str = "4y") -> pd.DataFrame:
    """야후 파이낸스에서 일봉 OHLCV를 받아 계약 프레임으로 반환한다.

    호출 전마다 0.7s 대기하고, 예외·빈 응답은 1s→2s→4s 지수 백오프로 재시도한다.
    끝내 실패하면 FetchError.
    """
    last_error = "빈 응답"
    for attempt in range(1 + len(_RETRY_DELAYS)):
        if attempt > 0:
            _sleep(_RETRY_DELAYS[attempt - 1])
        _sleep(_PRE_CALL_SLEEP)
        try:
            raw = _download(symbol, period)
        except Exception as exc:  # 네트워크·파서 등 어떤 실패든 재시도 대상
            last_error = f"{type(exc).__name__}: {exc}"
            continue
        if raw is None or raw.empty:
            last_error = "빈 응답"
            continue
        try:
            df = _normalize(raw)
        except Exception as exc:
            last_error = f"{type(exc).__name__}: {exc}"
            continue
        if not df.empty:
            return df
        last_error = "정규화 후 빈 데이터"
    raise FetchError(f"yfinance 수집 실패 — {symbol} ({last_error})")
