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


def _fmt_pct(v: float) -> str:
    """수익률·적중률 퍼센트 포맷 (NaN → '-')."""
    return "-" if pd.isna(v) else f"{v * 100:+.1f}%"


def _fmt_hit(v: float) -> str:
    return "-" if pd.isna(v) else f"{v * 100:.0f}%"


def build_backtest_md(stats_by_asset: dict[str, list[EventStats]], now: pd.Timestamp) -> str:
    """자산별 (이벤트 유형 × 호라이즌) 통계표 마크다운 리포트 (§2.6)."""
    from oo_scan.report_md import fmt_kst

    lines = [
        "# 소외 매수 가설 백테스트",
        "",
        f"생성 {fmt_kst(now)} · 대상 {len(stats_by_asset)}종",
        "",
        "구간 진입일에 매수(과열은 공매도 관점)했을 때의 전방 21/63/126거래일 수익률을",
        "같은 자산의 무조건부 평균(단순 보유)과 비교한다. 표본 5개 미만은 '표본 부족'.",
        "",
    ]
    for asset_id, stats in stats_by_asset.items():
        lines += [f"## {asset_id}", ""]
        lines.append("| 이벤트 | 호라이즌 | 표본 | 평균수익률 | 적중률 | 베이스라인 | 비고 |")
        lines.append("|---|---|---|---|---|---|---|")
        for s in stats:
            note = "표본 부족" if s.insufficient else ""
            lines.append(
                f"| {s.label} | {s.horizon}일 | {s.n_events} | {_fmt_pct(s.avg_return)} "
                f"| {_fmt_hit(s.hit_rate)} | {_fmt_pct(s.baseline)} | {note} |"
            )
        lines.append("")
    lines += ["---", "", "본 리포트는 투자 자문이 아니다.", ""]
    return "\n".join(lines)


def build_backtest_html(stats_by_asset: dict[str, list[EventStats]], now: pd.Timestamp) -> str:
    """자기완결 HTML 백테스트 리포트 (외부 리소스 0, index.html과 동일 원칙)."""
    from html import escape

    from oo_scan.report_md import fmt_kst

    rows_html = []
    for asset_id, stats in stats_by_asset.items():
        body = "".join(
            "<tr>"
            f"<td class='l'>{escape(s.label)}</td><td>{s.horizon}일</td><td>{s.n_events}</td>"
            f"<td>{escape(_fmt_pct(s.avg_return))}</td><td>{escape(_fmt_hit(s.hit_rate))}</td>"
            f"<td>{escape(_fmt_pct(s.baseline))}</td>"
            f"<td class='l'>{'표본 부족' if s.insufficient else ''}</td></tr>"
            for s in stats
        )
        rows_html.append(
            f"<h2>{escape(asset_id)}</h2><div class='wrap'><table>"
            "<tr><th>이벤트</th><th>호라이즌</th><th>표본</th><th>평균수익률</th>"
            "<th>적중률</th><th>베이스라인</th><th>비고</th></tr>"
            f"{body}</table></div>"
        )
    style = (
        "body{font-family:system-ui,sans-serif;margin:24px auto;max-width:960px;padding:0 12px}"
        "table{border-collapse:collapse;width:100%;font-size:14px}"
        "th,td{border:1px solid #8884;padding:4px 8px;text-align:right}"
        "th{background:#8881}.l{text-align:left}.wrap{overflow-x:auto}"
        "@media (prefers-color-scheme: dark){body{background:#111;color:#eee}}"
    )
    return (
        '<!doctype html><html lang="ko"><head><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width, initial-scale=1">'
        f"<title>소외 매수 백테스트</title><style>{style}</style></head><body>"
        f"<h1>소외 매수 가설 백테스트</h1><p>생성 {escape(fmt_kst(now))} · "
        f'대상 {len(stats_by_asset)}종 · <a href="index.html">온도계로 돌아가기</a></p>'
        + "".join(rows_html)
        + "<p>본 리포트는 투자 자문이 아니다.</p></body></html>"
    )


def cmd_backtest(args: argparse.Namespace) -> int:
    """backtest 서브커맨드 — 전 자산 백테스트 후 리포트 기록 (K2)."""
    from pathlib import Path

    from oo_scan.config import load_config
    from oo_scan.indicators import has_volume
    from oo_scan.pipeline import _fetch_df

    cfg = load_config()
    ids = args.assets.split(",") if args.assets else None
    stats_by_asset: dict[str, list[EventStats]] = {}
    for asset in [a for a in cfg.assets if ids is None or a.id in ids]:
        try:
            df, _ = _fetch_df(asset, offline=args.offline, no_cache=False)
            if df is None or len(df) < 200:  # 워밍업도 안 되는 자산은 제외
                continue
            stats_by_asset[asset.id] = backtest_asset(
                df, asset.asset_class == "crypto", has_volume(df.get("volume"))
            )
        except Exception as exc:  # 자산 격리 원칙
            print(f"백테스트 실패 {asset.id}: {exc}")
    if not stats_by_asset:
        print("백테스트 대상 자산 없음")
        return 1
    now = pd.Timestamp.now(tz="Asia/Seoul")
    md = build_backtest_md(stats_by_asset, now)
    html = build_backtest_html(stats_by_asset, now)
    reports, docs = Path("reports"), Path("docs")
    reports.mkdir(parents=True, exist_ok=True)
    docs.mkdir(parents=True, exist_ok=True)
    (reports / "backtest.md").write_text(md, encoding="utf-8")
    (reports / "backtest.html").write_text(html, encoding="utf-8")
    (docs / "backtest.html").write_text(html, encoding="utf-8")
    print(f"기록: {reports / 'backtest.md'} 외 2건 · 대상 {len(stats_by_asset)}종")
    return 0
