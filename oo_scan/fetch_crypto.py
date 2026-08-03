"""ccxt 일봉 페처 (D3) — 거래소 폴백 체인 + since 기반 페이지네이션.

§6 리스크 대응: 1회 1000봉 제한은 since를 마지막 캔들 뒤로 전진시키는 루프로 우회해
약 4년(기본 1460일)을 수집한다. 한 거래소 실패(451·심볼 없음 등)는 stderr에 기록하고
다음 거래소로 폴백하며, 사용한 거래소 id를 리포트 각주용으로 함께 반환한다.
"""

from __future__ import annotations

import sys
import time
from collections.abc import Callable
from typing import Any

import ccxt
import pandas as pd

from oo_scan.cache import FetchError, normalize_ohlcv
from oo_scan.config import Asset

__all__ = ["FetchError", "fetch_ccxt"]

# 1일봉의 밀리초 간격
_DAY_MS = 86_400_000

# 한 번에 요청하는 최대 봉 수 (주요 거래소 공통 안전값)
_PAGE_LIMIT = 1000


def _default_exchange_factory(exchange_id: str) -> Any:
    """ccxt 거래소 클라이언트를 생성한다 (레이트리밋 준수)."""
    return getattr(ccxt, exchange_id)({"enableRateLimit": True})


def _paginate_ohlcv(client: Any, symbol: str, days: int) -> list[list[float]]:
    """since 페이지네이션으로 최근 days일의 1d 캔들을 전부 수집한다.

    limit 미만이 돌아오거나 현재 시각에 도달하면 종료. since가 전진하지 않으면
    (거래소가 같은 페이지를 반복 반환) 무한 루프 방지를 위해 중단한다.
    """
    now_ms = int(time.time() * 1000)
    since = now_ms - days * _DAY_MS
    rows: list[list[float]] = []
    while since < now_ms:
        batch = client.fetch_ohlcv(symbol, timeframe="1d", since=since, limit=_PAGE_LIMIT)
        if not batch:
            break
        rows.extend(batch)
        next_since = int(batch[-1][0]) + _DAY_MS  # 마지막 캔들 바로 다음 봉부터
        if next_since <= since:
            break  # since 미전진 → 무한 루프 방지
        since = next_since
        if len(batch) < _PAGE_LIMIT:
            break  # 마지막 페이지
    # 신선도 보정: 일부 거래소(gate 등)는 since 페이지네이션의 2페이지째를 주지 않아
    # 과거 구간에서 수집이 멈춘다 (Actions 실측: gate가 첫 1000봉 이후 중단).
    # 마지막 캔들이 2일 이상 과거면 since 없이 최신 구간을 한 번 더 받아 병합한다.
    # (days ≤ 1460, 페이지 1000봉이므로 남은 공백은 항상 최신 1000봉 안에 들어온다.
    #  중복 캔들은 _to_frame의 keep-last 정리에서 최신 페이지가 이긴다.)
    if not rows or int(rows[-1][0]) < now_ms - 2 * _DAY_MS:
        try:
            latest = client.fetch_ohlcv(symbol, timeframe="1d", limit=_PAGE_LIMIT)
        except Exception:
            latest = []
        if latest:
            rows.extend(latest)
    return rows


def _to_frame(rows: list[list[float]]) -> pd.DataFrame:
    """ccxt 캔들 리스트([ts, o, h, l, c, v])를 데이터 계약 프레임으로 변환한다.

    ms 타임스탬프를 naive 일자로 바꾸고, 페이지 경계에서 겹친 (부분 캔들일 수 있는)
    중복 날짜는 마지막 행 우선으로 제거한다.
    """
    df = pd.DataFrame(rows, columns=["ts", "open", "high", "low", "close", "volume"])
    idx = pd.to_datetime(df["ts"].astype("int64"), unit="ms")
    df = df.drop(columns=["ts"])
    df.index = idx
    df = df.dropna(subset=["close"])
    return normalize_ohlcv(df)


def fetch_ccxt(
    asset: Asset,
    days: int = 1460,
    exchange_factory: Callable[[str], Any] | None = None,
) -> tuple[pd.DataFrame, str]:
    """폴백 체인을 따라 거래소에서 일봉 OHLCV를 수집한다.

    asset.exchanges 순서대로 시도하며 거래소별 심볼 오버라이드(symbol_for)를 존중한다.
    성공 시 (계약 프레임, 사용한 거래소 id)를 반환하고, 전부 실패하면 FetchError.
    테스트·특수 환경용으로 exchange_factory(exchange_id) 주입을 지원한다.
    """
    factory = exchange_factory if exchange_factory is not None else _default_exchange_factory
    failures: list[str] = []
    for exchange_id in asset.exchanges:
        symbol = asset.symbol_for(exchange_id)
        try:
            client = factory(exchange_id)
            rows = _paginate_ohlcv(client, symbol, days)
            df = _to_frame(rows)
            if df.empty:
                raise FetchError("빈 응답")
            return df, exchange_id
        except Exception as exc:  # 어떤 실패든 (심볼 없음·네트워크·451) 다음 거래소로
            print(
                f"[fetch_crypto] {asset.id}: {exchange_id} ({symbol}) 실패 — {exc}",
                file=sys.stderr,
            )
            failures.append(f"{exchange_id}: {exc}")
    detail = " / ".join(failures) if failures else "거래소 목록이 비어 있다"
    raise FetchError(f"{asset.id}: 모든 거래소 실패 — {detail}")
