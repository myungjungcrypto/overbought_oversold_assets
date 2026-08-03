"""백테스트 코어 (K1) — "소외 매수" 가설 검증 (AUTOPILOT §2.6).

과거 전 구간의 최종 온도 시계열에서 구간 진입 이벤트를 추출하고, 이벤트 후 전방
21/63/126 거래일(≈1/3/6개월) 종가 수익률·적중률을 같은 자산의 무조건부 평균 전방
수익률(베이스라인 = 단순 보유)과 비교한다. 리포트·CLI 연결은 K2가 담당한다.

규칙 (모호점 해석 포함):
- 이벤트는 **반올림하지 않은 연속 온도 시계열**의 임계값 돌파로 정의한다
  (``score.total_temperature_series`` 그대로 — 반올림은 최신값 표시 전용).
- 직전 봉이 NaN(워밍업)이면 이벤트가 아니다 (NaN 비교는 False → 자동 제외).
- 한 봉에서 여러 임계값을 한꺼번에 지나면(예: -20 → -70) 소외 진입과 깊은 소외
  진입이 각각 집계된다 — 이벤트 유형은 서로 독립이다.
- 전방 수익률은 포지셔널(거래일) 기준 ``close[t+h]/close[t] - 1``. 시계열 끝에서
  h봉 이내라 전방 수익률이 정의되지 않는 이벤트는 **해당 호라이즌의 n_events에서
  제외**한다 (통계·표본 수 모두 실현된 수익률만 집계).
- 베이스라인은 이벤트와 무관하게 전방 수익률이 정의된 **모든 봉**의 평균.
- 적중률은 엄격 부등호 — 소외류는 수익률 > 0, 과열은 < 0 (정확히 0이면 미적중).
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass

import pandas as pd

from oo_scan import score

# 이벤트 라벨 (리포트 문자열 — §2.6)
LABEL_NEGLECTED = "소외 진입"
LABEL_DEEP_NEGLECTED = "깊은 소외 진입"
LABEL_OVERHEATED = "과열 진입"
EVENT_LABELS: tuple[str, ...] = (LABEL_NEGLECTED, LABEL_DEEP_NEGLECTED, LABEL_OVERHEATED)

# 임계값 (§2.3 등급 경계와 동일 — 경계값은 극단 쪽 포함)
NEGLECTED_THRESHOLD = -30.0
DEEP_NEGLECTED_THRESHOLD = -60.0
OVERHEATED_THRESHOLD = 30.0

HORIZONS: tuple[int, ...] = (21, 63, 126)  # 전방 거래일 ≈ 1/3/6개월
MIN_EVENTS = 5  # §2.6 "표본 부족" 기준


@dataclass
class EventStats:
    """(이벤트 유형 × 호라이즌) 1칸의 백테스트 통계."""

    label: str  # "소외 진입" | "깊은 소외 진입" | "과열 진입"
    horizon: int  # 전방 거래일 수 (21 | 63 | 126)
    n_events: int  # 전방 수익률이 정의된 이벤트 수 (끝단 h봉 이내 이벤트는 제외)
    avg_return: float  # 이벤트 후 h일 전방 수익률 평균 (n_events=0이면 NaN)
    hit_rate: float  # 소외류: 양수 비율 / 과열: 음수 비율 (n_events=0이면 NaN)
    baseline: float  # 같은 자산의 무조건부 평균 h일 전방 수익률 (단순 보유 비교)
    insufficient: bool  # n_events < 5 → 표본 부족 표기 (§2.6)


def extract_events(total: pd.Series) -> dict[str, pd.DatetimeIndex]:
    """최종 온도 시계열에서 3가지 구간 진입 이벤트 날짜를 추출한다.

    - 소외 진입: 직전 봉 > -30 이고 현재 봉 ≤ -30
    - 깊은 소외 진입: 직전 봉 > -60 이고 현재 봉 ≤ -60
    - 과열 진입: 직전 봉 < 30 이고 현재 봉 ≥ 30

    직전 봉이 NaN이면(워밍업 직후 첫 값 등) 이벤트가 아니다. 반환 dict는 세 라벨
    키를 항상 갖고, 값은 total 인덱스의 부분집합이다.
    """
    prev = total.shift(1)
    into_neglected = (prev > NEGLECTED_THRESHOLD) & (total <= NEGLECTED_THRESHOLD)
    into_deep = (prev > DEEP_NEGLECTED_THRESHOLD) & (total <= DEEP_NEGLECTED_THRESHOLD)
    into_overheat = (prev < OVERHEATED_THRESHOLD) & (total >= OVERHEATED_THRESHOLD)
    return {
        LABEL_NEGLECTED: total.index[into_neglected],
        LABEL_DEEP_NEGLECTED: total.index[into_deep],
        LABEL_OVERHEATED: total.index[into_overheat],
    }


def _forward_return_series(close: pd.Series, horizon: int) -> pd.Series:
    """전 구간 h-전방 수익률 시계열 = close.shift(-h)/close - 1 (포지셔널 t+h).

    마지막 h봉과 종가가 0/NaN인 봉은 NaN.
    """
    return close.shift(-horizon) / close.where(close != 0) - 1.0


def forward_returns(close: pd.Series, dates: pd.DatetimeIndex, horizon: int) -> pd.Series:
    """이벤트 날짜별 전방 수익률 close[t+h]/close[t]-1 (거래일 포지션 기준).

    시계열 끝에서 h봉 이내인 이벤트와 close 인덱스에 없는 날짜는 NaN.
    반환 Series의 인덱스는 dates 그대로다.
    """
    return _forward_return_series(close, horizon).reindex(dates)


def _event_stats(
    label: str, horizon: int, fwd_all: pd.Series, event_dates: pd.DatetimeIndex
) -> EventStats:
    """한 (이벤트 유형, 호라이즌) 칸의 통계.

    전방 수익률이 NaN인 이벤트(끝단 h봉 이내)는 n_events·통계에서 제외한다.
    """
    realized = fwd_all.reindex(event_dates).dropna()
    n = int(len(realized))
    if n == 0:
        avg = float("nan")
        hit = float("nan")
    else:
        avg = float(realized.mean())
        if label == LABEL_OVERHEATED:
            hit = float((realized < 0).mean())  # 과열 → 하락 적중
        else:
            hit = float((realized > 0).mean())  # 소외류 → 상승 적중 (0은 미적중)
    return EventStats(
        label=label,
        horizon=horizon,
        n_events=n,
        avg_return=avg,
        hit_rate=hit,
        baseline=float(fwd_all.mean()),  # 정의된 봉이 없으면 NaN
        insufficient=n < MIN_EVENTS,
    )


def backtest_asset(df: pd.DataFrame, crypto: bool, use_mfi: bool) -> list[EventStats]:
    """자산 1종 백테스트 — 온도 시계열 1회 계산 후 3 이벤트 유형 × 3 호라이즌 = 9칸.

    df는 데이터 계약 일봉 프레임(naive DatetimeIndex, open/high/low/close/volume).
    반환 순서는 EVENT_LABELS × HORIZONS (라벨 우선, 호라이즌 오름차순).
    """
    total = score.total_temperature_series(df, crypto, use_mfi)
    events = extract_events(total)
    close = df["close"]
    fwd_by_horizon = {h: _forward_return_series(close, h) for h in HORIZONS}
    return [
        _event_stats(label, horizon, fwd_by_horizon[horizon], events[label])
        for label in EVENT_LABELS
        for horizon in HORIZONS
    ]


def cmd_backtest(args: argparse.Namespace) -> int:
    """backtest 서브커맨드 — 코어(K1)만 구현된 상태의 스텁. 리포트 연결은 K2에서."""
    print("backtest: 코어(K1) 구현 완료 — 리포트 생성은 K2에서 연결 예정")
    return 0
