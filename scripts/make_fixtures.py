"""결정적 합성 OHLCV 픽스처 생성기 (D4).

재실행해도 바이트 단위로 동일해야 한다 (검증: 생성 후 git diff --exit-code tests/fixtures).
결정성 3원칙:
- END_DATE 고정 상수 — 절대 today()로 바꾸지 말 것
- 자산별 고정 시드의 numpy RandomState (레거시 생성기 = 스트림 불변 보장)
- 가격 4자리 반올림 + 고정 float 포맷("%.4f")으로 기록해 repr 흔들림 차단

실행: python scripts/make_fixtures.py  (표준 라이브러리 + numpy/pandas만 사용, 네트워크 없음)
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pandas as pd

# 고정 종료일 (토요일) — 영업일 자산은 이 날짜 이전 마지막 영업일(2026-07-31)에 끝난다
END_DATE = "2026-08-01"

FIXTURES_DIR = Path(__file__).resolve().parent.parent / "tests" / "fixtures"

# 데이터 계약 컬럼 (oo_scan.cache.OHLCV_COLUMNS와 동일 — 스크립트 단독 실행을 위해 재정의)
COLUMNS: tuple[str, ...] = ("open", "high", "low", "close", "volume")


@dataclass(frozen=True)
class FixtureSpec:
    """자산 1종의 합성 파라미터."""

    asset_id: str
    seed: int  # RandomState 시드 (자산별 고정)
    rows: int  # 봉 수
    freq: str  # "D"=달력일(크립토 24/7), "B"=영업일(전통자산)
    start_price: float
    drift: float  # 일간 로그수익률 평균
    vol: float  # 일간 로그수익률 표준편차
    volume_base: float  # 거래량 스케일, 0이면 무볼륨 자산(volume 전부 0)


# BTC/ETH: 4년 달력일, SPX/KOSPI: ~4.4년 영업일, US10Y: 무볼륨 금리(^TNX 스케일),
# HYPE: 220봉 단기 상장 케이스 (§2.3 데이터 부족 규칙 검증용)
SPECS: tuple[FixtureSpec, ...] = (
    FixtureSpec("BTC", 101, 1460, "D", 30_000.0, 0.0007, 0.035, 25_000.0),
    FixtureSpec("ETH", 102, 1460, "D", 2_000.0, 0.0005, 0.040, 300_000.0),
    FixtureSpec("SPX", 103, 1100, "B", 4_000.0, 0.0004, 0.010, 2.5e9),
    FixtureSpec("KOSPI", 104, 1100, "B", 2_400.0, 0.0002, 0.011, 5.0e8),
    FixtureSpec("US10Y", 105, 1100, "B", 35.0, 0.0, 0.008, 0.0),
    FixtureSpec("HYPE", 106, 220, "D", 25.0, 0.0010, 0.050, 8.0e6),
)


def _dates(spec: FixtureSpec) -> pd.DatetimeIndex:
    """END_DATE에서 거꾸로 rows개의 날짜를 만든다 ("B"는 END_DATE 이전 영업일로 스냅)."""
    if spec.freq == "B":
        return pd.bdate_range(end=END_DATE, periods=spec.rows)
    return pd.date_range(end=END_DATE, periods=spec.rows, freq="D")


def make_ohlcv(spec: FixtureSpec) -> pd.DataFrame:
    """기하 랜덤워크 가격 경로로 계약 OHLCV 프레임 1개를 생성한다.

    open은 전일 close, high/low는 몸통(open·close)에 절대값 노이즈를 더해
    high >= max(open, close) >= min(open, close) >= low 가 항상 성립한다
    (4자리 반올림은 단조 변환이라 부등식이 보존된다).
    """
    rng = np.random.RandomState(spec.seed)
    n = spec.rows

    rets = rng.normal(spec.drift, spec.vol, n)
    close = spec.start_price * np.exp(np.cumsum(rets))
    open_ = np.empty(n)
    open_[0] = spec.start_price
    open_[1:] = close[:-1]

    wick_hi = np.abs(rng.normal(0.0, spec.vol * 0.5, n))
    wick_lo = np.abs(rng.normal(0.0, spec.vol * 0.5, n))
    high = np.maximum(open_, close) * (1.0 + wick_hi)
    low = np.minimum(open_, close) * (1.0 - wick_lo)

    if spec.volume_base > 0:
        volume = spec.volume_base * rng.lognormal(0.0, 0.6, n)
    else:
        volume = np.zeros(n)  # 무볼륨 자산 (금리 등)

    df = pd.DataFrame(
        {
            "open": np.round(open_, 4),
            "high": np.round(high, 4),
            "low": np.round(low, 4),
            "close": np.round(close, 4),
            "volume": np.round(volume, 4),
        },
        index=_dates(spec),
    )
    df.index.name = "date"
    return df[list(COLUMNS)]


def main() -> None:
    """전 자산 픽스처를 tests/fixtures/{ID}_1d.csv로 기록한다 (바이트 결정적)."""
    FIXTURES_DIR.mkdir(parents=True, exist_ok=True)
    for spec in SPECS:
        df = make_ohlcv(spec)
        path = FIXTURES_DIR / f"{spec.asset_id}_1d.csv"
        df.to_csv(path, date_format="%Y-%m-%d", float_format="%.4f")
        first = df.index[0].date()
        last = df.index[-1].date()
        print(f"{path.name}: {len(df)} rows ({first} ~ {last})")


if __name__ == "__main__":
    main()
