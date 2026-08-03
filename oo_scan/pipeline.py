"""전 자산 스캔 파이프라인 (P1) — fetch → 온도 계산 → 결과 집계.

자산별 실패는 격리한다: 한 자산의 페치/계산 실패가 런 전체를 죽이지 않고
ScanFailure로 집계돼 리포트의 "데이터 누락" 섹션에 실린다.
exit code 정책(§2.4): 라이브 = 시도 자산의 70% 이상 산출 시 0,
오프라인 = skip 제외 1개 이상 산출 시 0.
"""

from __future__ import annotations

import argparse
import sys
from dataclasses import dataclass, field

import pandas as pd

from oo_scan import indicators, long_term, score
from oo_scan.cache import DEFAULT_TTL_HOURS, FetchError, load_cached, save_cache
from oo_scan.config import AppConfig, Asset, load_config

STALE_CALENDAR_DAYS = 5  # 마지막 봉이 이보다 오래되면 STALE 표시 (§6)


@dataclass
class ScanResult:
    """자산 1종의 스캔 결과 (리포트 렌더링에 필요한 전부)."""

    asset: Asset
    asof: pd.Timestamp
    close: float
    bars: int
    short: float
    long: float
    total: float
    grade: str
    rsi14: float
    drawdown_pct: float
    days_since_peak: float
    range52w: float
    short_subs: dict[str, float] = field(default_factory=dict)
    long_subs: dict[str, float] = field(default_factory=dict)
    exchange_used: str | None = None
    stale: bool = False

    @property
    def display_close(self) -> float:
        """display_scale을 반영한 표시용 종가 (예: ^TNX 42.5 → 4.25%)."""
        return self.close * self.asset.display_scale


@dataclass
class ScanFailure:
    """자산 1종의 실패 기록."""

    asset: Asset
    reason: str


def _fetch_df(
    asset: Asset, *, offline: bool, no_cache: bool
) -> tuple[pd.DataFrame | None, str | None]:
    """자산 데이터를 확보한다. 반환 (df|None, 사용 거래소|None). None df = 오프라인 skip."""
    if offline:
        return load_cached(asset.id, max_age_hours=None), None
    if not no_cache:
        cached = load_cached(asset.id, max_age_hours=DEFAULT_TTL_HOURS)
        if cached is not None:
            return cached, None
    if asset.source == "yfinance":
        from oo_scan.fetch_yf import fetch_yf

        df = fetch_yf(asset.symbol)
        save_cache(asset.id, df)
        return df, None
    from oo_scan.fetch_crypto import fetch_ccxt

    df, exchange_used = fetch_ccxt(asset)
    save_cache(asset.id, df)
    return df, exchange_used


def _latest_subscores(df: pd.DataFrame, use_mfi: bool) -> dict[str, float]:
    """일봉 기준 단기 서브점수 최신값 (리포트 상세·소외 존 '차가운 지표' 선별용)."""
    close, high, low = df["close"], df["high"], df["low"]
    _, slow_d = indicators.stochastic_slow(high, low, close)
    raw: dict[str, pd.Series] = {
        "rsi": indicators.rsi(close),
        "slow_d": slow_d,
        "percent_b": indicators.percent_b(close),
        "williams_r": indicators.williams_r(high, low, close),
        "cci": indicators.cci(high, low, close),
        "disparity20": indicators.disparity(close),
    }
    if use_mfi:
        raw["mfi"] = indicators.mfi(high, low, close, df["volume"])
    return {
        name: float(score.SHORT_TRANSFORMS[name](s).iloc[-1]) for name, s in raw.items()
    }


def _latest_long_subs(close: pd.Series) -> dict[str, float]:
    """장기 서브점수 최신값."""
    return {
        "disparity200": float(long_term.disparity200_score(close).iloc[-1]),
        "range52w": float(long_term.range_position_score(close, long_term.WINDOW_1Y).iloc[-1]),
        "range3y": float(long_term.range_position_score(close, long_term.WINDOW_3Y).iloc[-1]),
        "yearly_return": float(long_term.yearly_return_score(close).iloc[-1]),
    }


def scan_asset(
    asset: Asset,
    df: pd.DataFrame,
    *,
    exchange_used: str | None = None,
    now: pd.Timestamp | None = None,
) -> ScanResult:
    """확보된 데이터프레임 하나를 온도·등급으로 변환한다."""
    crypto = asset.asset_class == "crypto"
    use_mfi = indicators.has_volume(df.get("volume"))
    scores = score.latest_scores(df, crypto, use_mfi)
    close = df["close"]
    dd_pct, dd_days = long_term.drawdown_stats(close)
    range52w_raw = long_term.range_position(close, long_term.WINDOW_1Y)
    rsi_series = indicators.rsi(close)
    asof = pd.Timestamp(df.index[-1])
    ref_now = pd.Timestamp.now().normalize() if now is None else pd.Timestamp(now).normalize()
    return ScanResult(
        asset=asset,
        asof=asof,
        close=float(close.iloc[-1]),
        bars=len(df),
        short=float(scores["short"]),
        long=float(scores["long"]),
        total=float(scores["total"]),
        grade=str(scores["grade"]),
        rsi14=float(rsi_series.iloc[-1]),
        drawdown_pct=dd_pct,
        days_since_peak=dd_days,
        range52w=float(range52w_raw.iloc[-1]),
        short_subs=_latest_subscores(df, use_mfi),
        long_subs=_latest_long_subs(close),
        exchange_used=exchange_used,
        stale=(ref_now - asof.normalize()).days > STALE_CALENDAR_DAYS,
    )


def run_scan(
    cfg: AppConfig,
    *,
    offline: bool = False,
    no_cache: bool = False,
    ids: list[str] | None = None,
    now: pd.Timestamp | None = None,
) -> tuple[list[ScanResult], list[ScanFailure], list[Asset]]:
    """전 자산 스캔. 반환 (성공, 실패, 오프라인 skip)."""
    results: list[ScanResult] = []
    failures: list[ScanFailure] = []
    skipped: list[Asset] = []
    targets = [a for a in cfg.assets if ids is None or a.id in ids]
    for asset in targets:
        try:
            df, exchange_used = _fetch_df(asset, offline=offline, no_cache=no_cache)
            if df is None:
                skipped.append(asset)
                continue
            results.append(scan_asset(asset, df, exchange_used=exchange_used, now=now))
        except FetchError as exc:
            failures.append(ScanFailure(asset, str(exc)))
        except Exception as exc:  # 계산 단계 방어 — 자산 격리 원칙
            failures.append(ScanFailure(asset, f"{type(exc).__name__}: {exc}"))
    return results, failures, skipped


def exit_code_for(
    *, produced: int, attempted: int, offline: bool
) -> int:
    """§2.4 exit code 정책."""
    if offline:
        return 0 if produced >= 1 else 1
    if attempted == 0:
        return 1
    return 0 if produced / attempted >= 0.7 else 1


def _fmt(v: float, digits: int = 1) -> str:
    """NaN 안전 숫자 포맷."""
    return "-" if pd.isna(v) else f"{v:.{digits}f}"


def render_table(results: list[ScanResult]) -> str:
    """stdout용 온도계 표 — 최종 온도 내림차순."""
    ordered = sorted(results, key=lambda r: (pd.isna(r.total), -(r.total if r.total == r.total else 0)))
    lines = [
        f"{'자산':<8} {'이름':<16} {'종가':>12} {'기준일':<10} "
        f"{'단기':>6} {'장기':>6} {'최종':>6} 등급"
    ]
    for r in ordered:
        stale_mark = " (STALE)" if r.stale else ""
        lines.append(
            f"{r.asset.id:<8} {r.asset.name_ko:<16} {r.display_close:>12,.2f} "
            f"{r.asof.date()!s:<10} {_fmt(r.short):>6} {_fmt(r.long):>6} "
            f"{_fmt(r.total, 0):>6} {r.grade}{stale_mark}"
        )
    return "\n".join(lines)


def cmd_run(args: argparse.Namespace) -> int:
    """run 서브커맨드 — 스캔 후 표 출력 (파일 기록은 R3에서 연결)."""
    cfg = load_config()
    ids = args.assets.split(",") if args.assets else None
    results, failures, skipped = run_scan(
        cfg, offline=args.offline, no_cache=getattr(args, "no_cache", False), ids=ids
    )
    print(render_table(results))
    if skipped:
        print(f"\nskip {len(skipped)}종 (오프라인, 로컬 데이터 없음): "
              + ", ".join(a.id for a in skipped))
    for f in failures:
        print(f"실패 {f.asset.id}: {f.reason}", file=sys.stderr)
    if not getattr(args, "no_write", False):
        print("(리포트 파일 기록은 R3 노드에서 활성화된다)")
    attempted = len(results) + len(failures)
    return exit_code_for(produced=len(results), attempted=attempted, offline=args.offline)


def cmd_fetch(args: argparse.Namespace) -> int:
    """fetch 서브커맨드 — 데이터만 받아 캐시에 저장."""
    cfg = load_config()
    ids = args.assets.split(",") if args.assets else None
    ok, fail = 0, 0
    for asset in [a for a in cfg.assets if ids is None or a.id in ids]:
        try:
            df, _ = _fetch_df(asset, offline=False, no_cache=True)
            assert df is not None
            print(f"{asset.id}: {len(df)}봉 캐시 저장")
            ok += 1
        except Exception as exc:
            print(f"실패 {asset.id}: {exc}", file=sys.stderr)
            fail += 1
    return exit_code_for(produced=ok, attempted=ok + fail, offline=False)
