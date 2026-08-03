"""마크다운 리포트 빌더 (R1) — §2.5 5섹션 한국어 리포트, 10분 독서 최적화.

섹션 순서(§2.5 고정): ① 제목·요약 카운트·TOP3·전체 온도계·과열/소외 랭킹
② 소외 존 ③ 광기 존 ④ 변화 감지 ⑤ 자산별 상세 부록(원값 표·데이터 누락·각주).
핵심(①~④)이 앞, 상세(⑤)가 뒤 — 아침 10분 독서를 위한 배치다.
`now`는 테스트 결정성을 위해 호출부에서 주입한다. 이 모듈은 현재 시각을 조회하지 않는다.
"""

from __future__ import annotations

from datetime import timedelta, timezone
from typing import TYPE_CHECKING

import pandas as pd

from oo_scan.config import ASSET_CLASS_LABELS_KO
from oo_scan.score import GRADE_INSUFFICIENT, GRADES

if TYPE_CHECKING:
    from oo_scan.config import Asset
    from oo_scan.history import GradeChange
    from oo_scan.pipeline import ScanFailure, ScanResult

KST = timezone(timedelta(hours=9), name="KST")

# 서브점수 키 → 리포트 표기 한글 라벨 (소외/광기 존과 상세 부록, HTML에서 공용)
SUB_NAMES_KO: dict[str, str] = {
    "rsi": "RSI",
    "slow_d": "스토캐스틱",
    "percent_b": "볼린저 %B",
    "williams_r": "W%R",
    "cci": "CCI",
    "disparity20": "이격도20",
    "mfi": "MFI",
    "disparity200": "200일선 이격 백분위",
    "range52w": "52주 레인지",
    "range3y": "3년 레인지",
    "yearly_return": "1년 수익률 백분위",
}

SHORT_SUB_ORDER = ("rsi", "slow_d", "percent_b", "williams_r", "cci", "disparity20", "mfi")
LONG_SUB_ORDER = ("disparity200", "range52w", "range3y", "yearly_return")

NEGLECT_GRADES = ("소외", "깊은 소외")
MANIA_GRADES = ("과열", "광기")
RANK_THRESHOLD = 30.0  # |최종 온도|가 이 값 이상이면 랭킹 표에 실린다
TRADING_DAYS_PER_MONTH = 21  # 소외 지속기간 개월 환산 (§2.5)

STALE_NOTE = "STALE = 마지막 봉이 기준 시점 대비 5일(달력일) 초과 경과한 자산."
DISCLAIMER = "본 리포트는 투자 자문이 아니다. 모든 판단과 그 책임은 사용자에게 있다."


# ── 공용 포맷 헬퍼 (report_html에서도 사용) ─────────────────────────────────


def fmt_kst(now: pd.Timestamp) -> str:
    """주입된 시각을 'YYYY-MM-DD HH:MM KST'로 표기한다 (tz-aware면 KST로 변환)."""
    ts = pd.Timestamp(now)
    if ts.tzinfo is not None:
        ts = ts.tz_convert(KST).tz_localize(None)
    return f"{ts:%Y-%m-%d %H:%M} KST"


def report_date(now: pd.Timestamp) -> str:
    """리포트 제목용 날짜 문자열 (KST 기준)."""
    ts = pd.Timestamp(now)
    if ts.tzinfo is not None:
        ts = ts.tz_convert(KST).tz_localize(None)
    return f"{ts:%Y-%m-%d}"


def fmt_num(v: float | None, digits: int = 1) -> str:
    """NaN/None 안전 숫자 포맷 — 산출 불가는 '-'."""
    if v is None or pd.isna(v):
        return "-"
    return f"{float(v):.{digits}f}"


def fmt_total(v: float | None) -> str:
    """최종 온도 표기 — 부호 포함 정수, NaN은 '-'."""
    if v is None or pd.isna(v):
        return "-"
    return f"{float(v):+.0f}"


def fmt_close(r: ScanResult) -> str:
    """표시용 종가 — display_scale 반영, 천단위 콤마, display_unit 접미 (예: 4.25%)."""
    v = r.display_close
    if pd.isna(v):
        return "-"
    unit = r.asset.display_unit or ""
    return f"{v:,.2f}{unit}"


def asset_label(asset: Asset) -> str:
    """자산 표기 — '한글명(ID)'."""
    return f"{asset.name_ko}({asset.id})"


def class_label(asset: Asset) -> str:
    """자산군 한글 라벨 (미등록 class는 원문 그대로)."""
    return ASSET_CLASS_LABELS_KO.get(asset.asset_class, asset.asset_class)


def grade_counts(results: list[ScanResult]) -> dict[str, int]:
    """등급별 자산 수 — 5등급+데이터 부족을 항상 포함한다 (0도 표기)."""
    counts: dict[str, int] = {g: 0 for g in [*GRADES, GRADE_INSUFFICIENT]}
    for r in results:
        counts[r.grade] = counts.get(r.grade, 0) + 1
    return counts


def _total_sort_key(r: ScanResult) -> tuple[int, float]:
    """최종 온도 내림차순 정렬 키 — NaN(데이터 부족)은 맨 뒤."""
    nan = pd.isna(r.total)
    return (1 if nan else 0, 0.0 if nan else -float(r.total))


def sorted_by_total(results: list[ScanResult]) -> list[ScanResult]:
    """최종 온도 내림차순(NaN 뒤) 정렬 사본."""
    return sorted(results, key=_total_sort_key)


def _merged_subs(r: ScanResult) -> list[tuple[str, float]]:
    """단기+장기 서브점수를 (한글 라벨, 값)으로 합친다. NaN 제외."""
    merged = {**r.short_subs, **r.long_subs}
    return [(SUB_NAMES_KO.get(k, k), float(v)) for k, v in merged.items() if not pd.isna(v)]


def coldest_subs(r: ScanResult, k: int = 3) -> list[tuple[str, float]]:
    """가장 차가운(낮은) 서브점수 k개 — 소외 존 '어떤 지표가 차가운가'."""
    return sorted(_merged_subs(r), key=lambda t: t[1])[:k]


def hottest_subs(r: ScanResult, k: int = 3) -> list[tuple[str, float]]:
    """가장 뜨거운(높은) 서브점수 k개 — 광기 존 경고용."""
    return sorted(_merged_subs(r), key=lambda t: -t[1])[:k]


def duration_ko(days: float | None) -> str:
    """고점 이후 경과 거래일 → '약 N개월(D거래일)' (≈21거래일=1개월)."""
    if days is None or pd.isna(days):
        return "-"
    d = int(days)
    months = d / TRADING_DAYS_PER_MONTH
    if months < 1:
        return f"1개월 미만({d}거래일)"
    return f"약 {months:.0f}개월({d}거래일)"


def split_changes(
    changes: list[GradeChange],
) -> tuple[list[GradeChange], list[GradeChange], list[GradeChange]]:
    """변화 목록을 (기회, 경고, 기타)로 나눈다 — 기회 신호를 최상단에 두기 위함."""
    opp = [c for c in changes if c.is_opportunity]
    warn = [c for c in changes if c.is_warning]
    rest = [c for c in changes if not (c.is_opportunity or c.is_warning)]
    return opp, warn, rest


def change_icon(c: GradeChange) -> str:
    """변화 아이콘 — 기회 🔵 / 경고 🔴 / 그 외 ·."""
    if c.is_opportunity:
        return "🔵"
    if c.is_warning:
        return "🔴"
    return "·"


# ── 마크다운 전용 조립 ──────────────────────────────────────────────────────


def _md_table(header: list[str], rows: list[list[str]]) -> list[str]:
    """마크다운 파이프 표 라인들."""
    lines = ["| " + " | ".join(header) + " |", "|" + "|".join(["---"] * len(header)) + "|"]
    lines += ["| " + " | ".join(row) + " |" for row in rows]
    return lines


def _summary_lines(results: list[ScanResult]) -> list[str]:
    """과매수/과매도 TOP3 한 줄 요약 (NaN 최종 온도는 제외)."""
    valid = [r for r in results if not pd.isna(r.total)]
    hot = sorted(valid, key=lambda r: -float(r.total))[:3]
    cold = sorted(valid, key=lambda r: float(r.total))[:3]

    def one_liner(rs: list[ScanResult]) -> str:
        if not rs:
            return "해당 없음"
        return " · ".join(f"{asset_label(r.asset)} {fmt_total(r.total)} {r.grade}" for r in rs)

    return [f"- 과매수 TOP3: {one_liner(hot)}", f"- 과매도 TOP3: {one_liner(cold)}"]


def _grouped(results: list[ScanResult]) -> list[tuple[str, list[ScanResult]]]:
    """ASSET_CLASS_LABELS_KO 순서(미등록 class는 뒤에)로 그룹핑, 그룹 내 온도 내림차순."""
    classes = list(ASSET_CLASS_LABELS_KO)
    for r in results:
        if r.asset.asset_class not in classes:
            classes.append(r.asset.asset_class)
    out: list[tuple[str, list[ScanResult]]] = []
    for cls in classes:
        group = [r for r in results if r.asset.asset_class == cls]
        if group:
            out.append((cls, sorted_by_total(group)))
    return out


def _full_table_lines(results: list[ScanResult]) -> list[str]:
    """② 전체 온도계 — 자산군별 그룹 표 (모든 자산, 데이터 부족 포함)."""
    lines = ["## 전체 온도계", ""]
    if not results:
        return lines + ["산출된 자산 없음", ""]
    header = ["자산", "종가", "기준일", "단기(일·주)", "장기", "최종", "등급", "RSI(14)"]
    for cls, group in _grouped(results):
        rows = []
        for r in group:
            asof = f"{r.asof:%Y-%m-%d}" + (" (STALE)" if r.stale else "")
            rows.append(
                [
                    asset_label(r.asset),
                    fmt_close(r),
                    asof,
                    fmt_num(r.short),
                    fmt_num(r.long),
                    fmt_total(r.total),
                    r.grade,
                    fmt_num(r.rsi14),
                ]
            )
        label = ASSET_CLASS_LABELS_KO.get(cls, cls)
        lines += [f"### {label}", ""] + _md_table(header, rows) + [""]
    return lines


def _rank_lines(results: list[ScanResult]) -> list[str]:
    """과열·광기 / 소외·깊은 소외 랭킹 — |최종|≥30인 자산만."""
    valid = [r for r in results if not pd.isna(r.total)]
    hot = sorted(
        [r for r in valid if float(r.total) >= RANK_THRESHOLD], key=lambda r: -float(r.total)
    )
    cold = sorted(
        [r for r in valid if float(r.total) <= -RANK_THRESHOLD], key=lambda r: float(r.total)
    )
    header = ["자산", "자산군", "최종", "단기", "장기", "등급"]

    def rows(rs: list[ScanResult]) -> list[list[str]]:
        return [
            [
                asset_label(r.asset),
                class_label(r.asset),
                fmt_total(r.total),
                fmt_num(r.short),
                fmt_num(r.long),
                r.grade,
            ]
            for r in rs
        ]

    lines = ["## 과열·광기 랭킹", ""]
    if hot:
        lines += _md_table(header, rows(hot)) + [""]
    else:
        lines += ["해당 자산 없음", ""]
    lines += ["## 소외·깊은 소외 랭킹", ""]
    if cold:
        lines += _md_table(header, rows(cold)) + [""]
    else:
        lines += ["해당 자산 없음", ""]
    return lines


def _zone_lines(results: list[ScanResult], hot: bool) -> list[str]:
    """②③ 소외 존 / 광기 존 — 극단 지표 2~3개, 드로다운·지속기간·52주 위치."""
    grades = MANIA_GRADES if hot else NEGLECT_GRADES
    title = "## 광기 존" if hot else "## 소외 존"
    empty = "현재 과열·광기 구간 자산 없음" if hot else "현재 소외 구간 자산 없음"
    members = [r for r in results if r.grade in grades]
    members.sort(key=lambda r: -float(r.total) if hot else float(r.total))
    lines = [title, ""]
    if not members:
        return lines + [empty, ""]
    for r in members:
        subs = hottest_subs(r) if hot else coldest_subs(r)
        sub_label = "뜨거운 지표" if hot else "차가운 지표"
        dur_label = "고점 후" if hot else "소외 지속"
        ind = " · ".join(f"{name} {fmt_num(v)}" for name, v in subs) or "-"
        lines.append(f"- **{asset_label(r.asset)}** — 최종 {fmt_total(r.total)} ({r.grade})")
        lines.append(f"  - {sub_label}: {ind}")
        lines.append(
            f"  - 3년 고점 대비 {fmt_num(r.drawdown_pct)}% · {dur_label} "
            f"{duration_ko(r.days_since_peak)} · 52주 레인지 위치 {fmt_num(r.range52w)}%"
        )
    return lines + [""]


def _changes_lines(changes: list[GradeChange]) -> list[str]:
    """④ 변화 감지 — 기회(🔵) 최상단, 경고(🔴), 기타(·) 순."""
    lines = ["## 변화 감지", ""]
    if not changes:
        return lines + ["변화 없음", ""]
    opp, warn, rest = split_changes(changes)
    for c in [*opp, *warn, *rest]:
        lines.append(
            f"- {change_icon(c)} {c.asset_id}: {c.prev_grade} → {c.new_grade} "
            f"(직전 {c.prev_date})"
        )
    return lines + [""]


def _detail_lines(
    results: list[ScanResult], failures: list[ScanFailure], skipped: list[Asset]
) -> list[str]:
    """⑤ 자산별 상세 부록 — 전 지표 표 + 데이터 누락 + 각주."""
    lines = [
        "## 자산별 상세",
        "",
        "부록 — 서브점수 원값(정규화, -100~100)과 구조 지표, 데이터 누락, 각주.",
        "",
    ]
    ordered = sorted_by_total(results)
    if ordered:
        short_header = ["자산"] + [SUB_NAMES_KO[k] for k in SHORT_SUB_ORDER]
        short_rows = [
            [asset_label(r.asset)] + [fmt_num(r.short_subs.get(k)) for k in SHORT_SUB_ORDER]
            for r in ordered
        ]
        lines += ["### 단기 서브점수 (일봉 기준)", ""]
        lines += _md_table(short_header, short_rows) + [""]
        long_header = (
            ["자산"]
            + [SUB_NAMES_KO[k] for k in LONG_SUB_ORDER]
            + ["드로다운%", "고점 후 경과일", "52주 위치%", "봉 수"]
        )
        long_rows = [
            [asset_label(r.asset)]
            + [fmt_num(r.long_subs.get(k)) for k in LONG_SUB_ORDER]
            + [
                fmt_num(r.drawdown_pct),
                fmt_num(r.days_since_peak, 0),
                fmt_num(r.range52w),
                str(r.bars),
            ]
            for r in ordered
        ]
        lines += ["### 장기 서브점수·구조 지표", ""]
        lines += _md_table(long_header, long_rows) + [""]
    lines += ["### 데이터 누락", ""]
    if not failures and not skipped:
        lines += ["누락 없음", ""]
    else:
        for f in failures:
            lines.append(f"- {asset_label(f.asset)}: {f.reason}")
        for a in skipped:
            lines.append(f"- {asset_label(a)}: 오프라인 skip — 로컬 데이터 없음")
        lines.append("")
    lines += ["### 각주", ""]
    used = [(r.asset.id, r.exchange_used) for r in results if r.exchange_used]
    if used:
        pairs = " · ".join(f"{aid}={ex}" for aid, ex in used)
        lines.append(f"- 사용 거래소: {pairs}")
    lines.append(f"- 기준일은 자산별 마지막 가용 봉이다. {STALE_NOTE}")
    lines.append(f"- {DISCLAIMER}")
    return lines + [""]


def build_markdown_report(
    results: list[ScanResult],
    failures: list[ScanFailure],
    skipped: list[Asset],
    changes: list[GradeChange],
    now: pd.Timestamp,
) -> str:
    """§2.5 5섹션 마크다운 리포트 전체를 문자열로 조립한다.

    순서: 온도계 한 장(요약·전체 표·랭킹) → 소외 존 → 광기 존 → 변화 감지 → 자산별 상세.
    """
    counts = grade_counts(results)
    count_line = " · ".join(f"{g} {counts[g]}" for g in [*GRADES, GRADE_INSUFFICIENT])
    meta = (
        f"생성 {fmt_kst(now)} · 산출 {len(results)}종 · 누락 {len(failures)}종"
        f" · skip {len(skipped)}종"
    )
    lines: list[str] = [
        f"# 광기·소외 온도계 — {report_date(now)}",
        "",
        meta,
        "",
        f"**{count_line}**",
        "",
        "## 요약",
        "",
        *_summary_lines(results),
        "",
    ]
    lines += _full_table_lines(results)
    lines += _rank_lines(results)
    lines += _zone_lines(results, hot=False)
    lines += _zone_lines(results, hot=True)
    lines += _changes_lines(changes)
    lines += ["---", ""]
    lines += _detail_lines(results, failures, skipped)
    return "\n".join(lines).rstrip() + "\n"
