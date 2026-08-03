"""fetch_crypto 테스트 (D3) — exchange_factory로 가짜 거래소 주입, 네트워크 없음."""

from __future__ import annotations

import time
from typing import Any

import pandas as pd
import pytest

from oo_scan.cache import OHLCV_COLUMNS, FetchError
from oo_scan.config import Asset
from oo_scan.fetch_crypto import _DAY_MS, fetch_ccxt


def _asset(
    exchanges: tuple[str, ...] = ("binance", "bybit"),
    symbol: str = "BTC/USDT",
    overrides: dict[str, str] | None = None,
) -> Asset:
    """테스트용 crypto Asset을 직접 만든다."""
    return Asset(
        id="BTC",
        name_ko="비트코인",
        asset_class="crypto",
        source="ccxt",
        symbol=symbol,
        exchanges=exchanges,
        symbol_overrides=dict(overrides or {}),
    )


class FakeExchange:
    """첫 호출의 since를 기점으로 total개의 일봉을 만들어 since 이후를 잘라 주는 가짜."""

    def __init__(self, total: int) -> None:
        self.total = total
        self.base: int | None = None
        self.calls: list[tuple[str, str, int, int]] = []

    def _candles(self) -> list[list[float]]:
        assert self.base is not None
        return [
            [self.base + k * _DAY_MS, 100.0 + k, 101.0 + k, 99.0 + k, 100.5 + k, 10.0 + k]
            for k in range(self.total)
        ]

    def fetch_ohlcv(
        self, symbol: str, timeframe: str = "1d", since: int | None = None, limit: int = 1000
    ) -> list[list[float]]:
        assert since is not None
        if self.base is None:
            self.base = int(since)
        self.calls.append((symbol, timeframe, int(since), int(limit)))
        eligible = [c for c in self._candles() if c[0] >= since]
        return eligible[:limit]


class BrokenExchange:
    """항상 실패하는 가짜 (심볼 없음·네트워크 오류 등을 뭉뚱그려 재현)."""

    def fetch_ohlcv(self, *args: Any, **kwargs: Any) -> list[list[float]]:
        raise RuntimeError("boom: symbol not found")


class StuckExchange:
    """since를 무시하고 항상 같은 1000봉 풀 페이지를 돌려주는 가짜 (무한 루프 유발형)."""

    def __init__(self) -> None:
        self.base: int | None = None
        self.calls = 0

    def fetch_ohlcv(
        self, symbol: str, timeframe: str = "1d", since: int | None = None, limit: int = 1000
    ) -> list[list[float]]:
        assert since is not None
        if self.base is None:
            self.base = int(since)
        self.calls += 1
        return [
            [self.base + k * _DAY_MS, 1.0, 2.0, 0.5, 1.5, 9.0] for k in range(1000)
        ]


def test_pagination_three_pages_stitch(capsys: pytest.CaptureFixture[str]) -> None:
    """1000/1000/200 세 페이지가 이어 붙어 2200봉 계약 프레임이 된다."""
    fake = FakeExchange(total=2200)
    df, used = fetch_ccxt(
        _asset(exchanges=("binance",)), days=2200, exchange_factory=lambda eid: fake
    )

    assert used == "binance"
    assert len(fake.calls) == 3
    sinces = [c[2] for c in fake.calls]
    assert sinces[1] == sinces[0] + 1000 * _DAY_MS  # 마지막 캔들 다음 봉으로 전진
    assert sinces[2] == sinces[0] + 2000 * _DAY_MS
    assert all(c[1] == "1d" and c[3] == 1000 for c in fake.calls)

    assert list(df.columns) == list(OHLCV_COLUMNS)
    assert all(str(dt) == "float64" for dt in df.dtypes)
    assert str(df.index.dtype) == "datetime64[ns]" and df.index.tz is None
    assert len(df) == 2200
    assert df.index.is_monotonic_increasing and df.index.is_unique
    diffs = df.index.to_series().diff().dropna()
    assert (diffs == pd.Timedelta(days=1)).all()  # 달력일 연속
    assert df["close"].iloc[0] == 100.5 and df["close"].iloc[-1] == 100.5 + 2199


def test_fallback_to_second_exchange(capsys: pytest.CaptureFixture[str]) -> None:
    """첫 거래소가 죽으면 stderr 로그 후 둘째 거래소로 폴백하고 그 id를 보고한다."""
    fakes: dict[str, Any] = {"binance": BrokenExchange(), "bybit": FakeExchange(total=300)}
    df, used = fetch_ccxt(_asset(), days=300, exchange_factory=lambda eid: fakes[eid])

    assert used == "bybit"
    assert len(df) == 300
    err = capsys.readouterr().err
    assert "binance" in err and "실패" in err


def test_symbol_override_respected() -> None:
    """symbol_overrides가 있는 거래소에는 오버라이드 심볼이 전달된다."""
    hyper = FakeExchange(total=220)
    asset = Asset(
        id="HYPE",
        name_ko="하이퍼리퀴드",
        asset_class="crypto",
        source="ccxt",
        symbol="HYPE/USDT",
        exchanges=("hyperliquid", "bybit"),
        symbol_overrides={"hyperliquid": "HYPE/USDC"},
    )
    df, used = fetch_ccxt(asset, days=220, exchange_factory=lambda eid: {"hyperliquid": hyper}[eid])

    assert used == "hyperliquid"
    assert hyper.calls[0][0] == "HYPE/USDC"  # 오버라이드 심볼
    assert len(df) == 220


def test_override_only_for_that_exchange(capsys: pytest.CaptureFixture[str]) -> None:
    """오버라이드가 없는 폴백 거래소에는 기본 심볼이 전달된다."""
    bybit = FakeExchange(total=100)
    fakes: dict[str, Any] = {"hyperliquid": BrokenExchange(), "bybit": bybit}
    asset = Asset(
        id="HYPE",
        name_ko="하이퍼리퀴드",
        asset_class="crypto",
        source="ccxt",
        symbol="HYPE/USDT",
        exchanges=("hyperliquid", "bybit"),
        symbol_overrides={"hyperliquid": "HYPE/USDC"},
    )
    _, used = fetch_ccxt(asset, days=100, exchange_factory=lambda eid: fakes[eid])

    assert used == "bybit"
    assert bybit.calls[0][0] == "HYPE/USDT"  # 기본 심볼


def test_all_exchanges_fail_raises(capsys: pytest.CaptureFixture[str]) -> None:
    """전 거래소 실패(예외·빈 응답 섞임)면 FetchError에 자산 id가 담긴다."""

    class EmptyExchange:
        def fetch_ohlcv(self, *args: Any, **kwargs: Any) -> list[list[float]]:
            return []

    fakes: dict[str, Any] = {"binance": BrokenExchange(), "bybit": EmptyExchange()}
    with pytest.raises(FetchError, match="BTC.*모든 거래소 실패"):
        fetch_ccxt(_asset(), days=100, exchange_factory=lambda eid: fakes[eid])
    err = capsys.readouterr().err
    assert "binance" in err and "bybit" in err


def test_stuck_exchange_terminates(capsys: pytest.CaptureFixture[str]) -> None:
    """since가 전진하지 않는 거래소도 무한 루프 없이 종료하고 중복은 제거된다."""
    stuck = StuckExchange()
    df, _ = fetch_ccxt(
        _asset(exchanges=("binance",)), days=5000, exchange_factory=lambda eid: stuck
    )
    assert stuck.calls == 2  # 2회째에 미전진을 감지하고 중단
    assert len(df) == 1000  # 같은 1000봉의 중복 제거 결과
    assert df.index.is_unique


def test_page_boundary_duplicate_keeps_last() -> None:
    """페이지 경계에서 겹친 캔들(갱신된 부분 캔들)은 나중 페이지 값이 이긴다."""
    base = int(time.time() * 1000) - 1200 * _DAY_MS

    def candle(k: int, close: float) -> list[float]:
        return [base + k * _DAY_MS, 1.0, 2.0, 0.5, close, 7.0]

    page1 = [candle(k, 10.0 + k) for k in range(1000)]
    page2 = [candle(999, 999999.0)] + [candle(k, 10.0 + k) for k in range(1000, 1200)]

    class ScriptedExchange:
        def __init__(self) -> None:
            self.pages = [page1, page2]

        def fetch_ohlcv(self, *args: Any, **kwargs: Any) -> list[list[float]]:
            return self.pages.pop(0) if self.pages else []

    df, _ = fetch_ccxt(
        _asset(exchanges=("binance",)), days=1200, exchange_factory=lambda eid: ScriptedExchange()
    )
    assert len(df) == 1200
    assert df.index.is_unique
    dup_date = pd.Timestamp(base + 999 * _DAY_MS, unit="ms").normalize()
    assert df.loc[dup_date, "close"] == 999999.0  # keep="last"
