"""HTML 대시보드 빌더 (R2) — 단일 파일, 외부 리소스 0 (인라인 CSS·SVG만).

GitHub Pages의 docs/index.html이 되는 자급자족 문서다: 요약 카드 → 변화 감지 배너 →
온도계 테이블(최종 온도 히트맵·60봉 스파크라인) → 소외/광기 존 카드 → 데이터 누락 → 각주.
라이트/다크는 prefers-color-scheme로 대응하고, 히트맵 셀은 rgba 배경+명시적 글자색이라
어느 테마에서도 대비가 유지된다. 폰트는 시스템 스택만 사용한다.
"""

from __future__ import annotations

from html import escape
from typing import TYPE_CHECKING

import pandas as pd

from oo_scan.report_md import (
    DISCLAIMER,
    MANIA_GRADES,
    NEGLECT_GRADES,
    STALE_NOTE,
    asset_label,
    change_icon,
    class_label,
    coldest_subs,
    fmt_delta,
    duration_ko,
    fmt_close,
    fmt_kst,
    fmt_num,
    fmt_total,
    grade_counts,
    hottest_subs,
    report_date,
    sorted_by_total,
    split_changes,
)
from oo_scan.score import GRADE_INSUFFICIENT, GRADES

if TYPE_CHECKING:
    from oo_scan.config import Asset
    from oo_scan.history import GradeChange
    from oo_scan.pipeline import ScanFailure, ScanResult

# 등급 배지·요약 카드용 진한 배경색 — 흰 글자 대비 확보 (라이트/다크 공통)
GRADE_BADGE_COLORS: dict[str, str] = {
    "광기": "#c62828",
    "과열": "#e65100",
    "중립": "#6d6d73",
    "소외": "#1976d2",
    "깊은 소외": "#0d47a1",
    GRADE_INSUFFICIENT: "#616161",
}

# 스파크라인 스트로크용 중간 밝기 색 — 밝은/어두운 배경 모두에서 식별 가능
GRADE_ACCENT_COLORS: dict[str, str] = {
    "광기": "#e53935",
    "과열": "#fb8c00",
    "중립": "#8e8e93",
    "소외": "#42a5f5",
    "깊은 소외": "#1e88e5",
    GRADE_INSUFFICIENT: "#9e9e9e",
}

# 히트맵 앵커: -100 청색 ↔ 0 중립 회백 ↔ +100 적색 선형 보간 (§2.5)
HEAT_COLD = (33, 102, 172)
HEAT_MID = (232, 232, 232)
HEAT_HOT = (178, 24, 43)
HEAT_ALPHA = 0.92

_CSS = """
:root{color-scheme:light dark}
*{box-sizing:border-box}
body{margin:0 auto;max-width:1100px;padding:24px 16px;line-height:1.55;
font-family:-apple-system,BlinkMacSystemFont,"Segoe UI","Apple SD Gothic Neo",
"Malgun Gothic","Noto Sans KR",Arial,sans-serif;background:#fafafa;color:#1c1c1e}
h1{font-size:1.55rem;margin:0 0 4px}
h2{font-size:1.15rem;margin:28px 0 10px;padding-bottom:6px;
border-bottom:1px solid rgba(128,128,128,.3)}
.muted{color:#82828a;font-size:.85rem}
.cards{display:flex;flex-wrap:wrap;gap:10px;margin:18px 0}
.card{flex:1 1 130px;min-width:110px;border-radius:12px;padding:12px 14px;color:#fff}
.card .n{font-size:1.7rem;font-weight:700;line-height:1.1}
.card .g{font-size:.85rem;opacity:.92}
.wrap{overflow-x:auto}
table{border-collapse:collapse;width:100%;font-size:.88rem}
th,td{padding:6px 9px;border-bottom:1px solid rgba(128,128,128,.25);
text-align:right;white-space:nowrap}
th:first-child,td:first-child,td.l{text-align:left}
td.heat{font-weight:700;text-align:center}
.badge{display:inline-block;padding:2px 9px;border-radius:999px;font-size:.78rem;color:#fff}
ul.changes{list-style:none;padding:0;margin:0}
ul.changes li{border-radius:8px;padding:7px 12px;margin:6px 0;background:rgba(128,128,128,.08)}
ul.changes li.opp{background:rgba(30,136,229,.16)}
ul.changes li.warn{background:rgba(229,57,53,.14)}
.zone-card{border:1px solid rgba(128,128,128,.25);border-radius:12px;
padding:12px 14px;margin:10px 0;background:rgba(128,128,128,.06)}
footer{margin-top:32px;font-size:.82rem;color:#82828a}
footer a{color:inherit}
@media (prefers-color-scheme:dark){
body{background:#121212;color:#e8e8e8}
.muted,footer{color:#9a9aa0}
}
"""


def heat_style(total: float | None) -> str:
    """최종 온도 → 히트맵 셀 inline style. NaN(데이터 부족)이면 빈 문자열.

    -100 청색 ↔ 0 중립 회백 ↔ +100 적색을 채널별 선형 보간한다.
    rgba 배경 + 명시적 글자색이라 라이트/다크 모두에서 읽힌다.
    """
    if total is None or pd.isna(total):
        return ""
    t = max(-100.0, min(100.0, float(total))) / 100.0
    hi = HEAT_HOT if t >= 0 else HEAT_COLD
    frac = abs(t)
    r, g, b = (round(HEAT_MID[i] + (hi[i] - HEAT_MID[i]) * frac) for i in range(3))
    text = "#ffffff" if frac >= 0.55 else "#1a1a1a"
    return f"background:rgba({r},{g},{b},{HEAT_ALPHA});color:{text}"


def sparkline_svg(spark: list[float], color: str) -> str:
    """최근 종가 리스트 → 인라인 SVG 폴리라인 (min-max 정규화).

    flat이거나 점 1개면 수평선, 빈 리스트면 빈 문자열. 외부 리소스·라이브러리 없음.
    """
    vals = [float(v) for v in spark if not pd.isna(v)]
    if not vals:
        return ""
    w, h, pad = 120.0, 28.0, 2.0
    vmin, vmax = min(vals), max(vals)
    n = len(vals)
    if n == 1 or vmax == vmin:
        pts = f"{pad:.1f},{h / 2:.1f} {w - pad:.1f},{h / 2:.1f}"
    else:
        span = vmax - vmin
        pts = " ".join(
            f"{pad + (w - 2 * pad) * i / (n - 1):.1f},"
            f"{pad + (h - 2 * pad) * (1.0 - (v - vmin) / span):.1f}"
            for i, v in enumerate(vals)
        )
    return (
        '<svg viewBox="0 0 120 28" width="120" height="28" aria-hidden="true">'
        f'<polyline points="{pts}" fill="none" stroke="{color}" stroke-width="1.5"/></svg>'
    )


def _cards_html(counts: dict[str, int]) -> str:
    """상단 요약 카드 5+1개 (광기~깊은 소외 + 데이터 부족)."""
    cards = []
    for g in [*GRADES, GRADE_INSUFFICIENT]:
        color = GRADE_BADGE_COLORS.get(g, "#616161")
        cards.append(
            f'<div class="card" style="background:{color}">'
            f'<div class="n">{counts.get(g, 0)}</div><div class="g">{escape(g)}</div></div>'
        )
    return '<div class="cards">' + "".join(cards) + "</div>"


def _changes_html(changes: list[GradeChange]) -> str:
    """변화 감지 배너 — 기회(🔵) 최상단, 경고(🔴), 기타(·) 순."""
    if not changes:
        return '<p class="muted">변화 없음</p>'
    opp, warn, rest = split_changes(changes)
    items = []
    for cls, group in (("opp", opp), ("warn", warn), ("flat", rest)):
        for c in group:
            items.append(
                f'<li class="{cls}">{change_icon(c)} {escape(c.asset_id)}: '
                f"{escape(c.prev_grade)} → {escape(c.new_grade)} "
                f'<span class="muted">(직전 {escape(c.prev_date)})</span></li>'
            )
    return '<ul class="changes">' + "".join(items) + "</ul>"


def _badge(grade: str) -> str:
    """등급 배지 span."""
    color = GRADE_BADGE_COLORS.get(grade, "#616161")
    return f'<span class="badge" style="background:{color}">{escape(grade)}</span>'


def _thermo_table_html(
    results: list[ScanResult], prev_totals: dict[str, float] | None = None
) -> str:
    """온도계 테이블 — 전 자산 최종 온도 내림차순, 히트맵 셀·Δ전일·스파크라인 포함."""
    head = (
        "<tr><th>자산</th><th>자산군</th><th>종가</th><th>추이(60봉)</th><th>단기</th>"
        "<th>장기</th><th>최종</th><th>Δ전일</th><th>등급</th><th>기준일</th></tr>"
    )
    rows = []
    for r in sorted_by_total(results):
        accent = GRADE_ACCENT_COLORS.get(r.grade, "#9e9e9e")
        asof = f"{r.asof:%Y-%m-%d}" + (' <span class="muted">STALE</span>' if r.stale else "")
        style = heat_style(r.total)
        heat_attr = f' style="{style}"' if style else ""
        rows.append(
            "<tr>"
            f'<td class="l">{escape(asset_label(r.asset))}</td>'
            f'<td class="l">{escape(class_label(r.asset))}</td>'
            f"<td>{escape(fmt_close(r))}</td>"
            f'<td class="l">{sparkline_svg(r.spark, accent)}</td>'
            f"<td>{fmt_num(r.short)}</td><td>{fmt_num(r.long)}</td>"
            f'<td class="heat"{heat_attr}>{fmt_total(r.total)}</td>'
            f"<td>{escape(fmt_delta(r, prev_totals))}</td>"
            f"<td>{_badge(r.grade)}</td>"
            f"<td>{asof}</td>"
            "</tr>"
        )
    if not rows:
        rows.append('<tr><td colspan="10" class="l">산출된 자산 없음</td></tr>')
    return '<div class="wrap"><table>' + head + "".join(rows) + "</table></div>"


def _zone_html(results: list[ScanResult], hot: bool) -> str:
    """소외 존 / 광기 존 상세 카드 — 극단 지표 2~3개와 구조 지표 한 줄."""
    grades = MANIA_GRADES if hot else NEGLECT_GRADES
    members = [r for r in results if r.grade in grades]
    members.sort(key=lambda r: -float(r.total) if hot else float(r.total))
    if not members:
        empty = "현재 과열·광기 구간 자산 없음" if hot else "현재 소외 구간 자산 없음"
        return f'<p class="muted">{empty}</p>'
    cards = []
    for r in members:
        subs = hottest_subs(r) if hot else coldest_subs(r)
        sub_label = "뜨거운 지표" if hot else "차가운 지표"
        dur_label = "고점 후" if hot else "소외 지속"
        ind = " · ".join(f"{escape(n)} {fmt_num(v)}" for n, v in subs) or "-"
        cards.append(
            '<div class="zone-card">'
            f"<div><strong>{escape(asset_label(r.asset))}</strong> {_badge(r.grade)} "
            f"최종 {fmt_total(r.total)}</div>"
            f"<div>{sub_label}: {ind}</div>"
            f'<div class="muted">3년 고점 대비 {fmt_num(r.drawdown_pct)}% · {dur_label} '
            f"{duration_ko(r.days_since_peak)} · 52주 레인지 위치 {fmt_num(r.range52w)}%</div>"
            "</div>"
        )
    return "".join(cards)


def _gaps_html(failures: list[ScanFailure], skipped: list[Asset]) -> str:
    """데이터 누락 — 실패 사유와 오프라인 skip 자산."""
    if not failures and not skipped:
        return '<p class="muted">누락 없음</p>'
    items = [f"<li>{escape(asset_label(f.asset))}: {escape(f.reason)}</li>" for f in failures]
    items += [
        f"<li>{escape(asset_label(a))}: 오프라인 skip — 로컬 데이터 없음</li>" for a in skipped
    ]
    return "<ul>" + "".join(items) + "</ul>"


def _footer_html(results: list[ScanResult]) -> str:
    """각주 — 사용 거래소·STALE 설명·면책·백테스트 상대 링크."""
    used = [(r.asset.id, r.exchange_used) for r in results if r.exchange_used]
    items = []
    if used:
        pairs = " · ".join(f"{escape(a)}={escape(e)}" for a, e in used)
        items.append(f"<li>사용 거래소: {pairs}</li>")
    items.append(f"<li>기준일은 자산별 마지막 가용 봉이다. {escape(STALE_NOTE)}</li>")
    items.append(f"<li>{escape(DISCLAIMER)}</li>")
    items.append('<li><a href="backtest.html">백테스트 리포트 보기</a></li>')
    return "<footer><ul>" + "".join(items) + "</ul></footer>"


def build_html_report(
    results: list[ScanResult],
    failures: list[ScanFailure],
    skipped: list[Asset],
    changes: list[GradeChange],
    now: pd.Timestamp,
    prev_totals: dict[str, float] | None = None,
) -> str:
    """단일 파일 HTML 대시보드 전체를 문자열로 조립한다 (`now` 주입으로 결정적)."""
    counts = grade_counts(results)
    meta = (
        f"생성 {fmt_kst(now)} · 산출 {len(results)}종 · 누락 {len(failures)}종"
        f" · skip {len(skipped)}종"
    )
    body = [
        f"<h1>광기·소외 온도계 — {report_date(now)}</h1>",
        f'<p class="muted">{meta}</p>',
        _cards_html(counts),
        "<h2>변화 감지</h2>",
        _changes_html(changes),
        "<h2>전체 온도계</h2>",
        _thermo_table_html(results, prev_totals),
        "<h2>소외 존</h2>",
        _zone_html(results, hot=False),
        "<h2>광기 존</h2>",
        _zone_html(results, hot=True),
        "<h2>데이터 누락</h2>",
        _gaps_html(failures, skipped),
        _footer_html(results),
    ]
    doc = [
        "<!DOCTYPE html>",
        '<html lang="ko">',
        "<head>",
        '<meta charset="utf-8">',
        '<meta name="viewport" content="width=device-width, initial-scale=1">',
        "<title>광기·소외 온도계</title>",
        f"<style>{_CSS}</style>",
        "</head>",
        "<body>",
        *body,
        "</body>",
        "</html>",
    ]
    return "\n".join(doc) + "\n"
