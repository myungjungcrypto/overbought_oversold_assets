"""리포트 빌더 테스트 (R1 마크다운 + R2 HTML) — 네트워크·리포 파일 기록 없음.

ScanResult/GradeChange를 인라인으로 만들어 순수 문자열 출력만 검증한다.
테스트 이름 규칙: `-k markdown` → R1, `-k html` → R2 (AUTOPILOT 노드 필터).
"""

from __future__ import annotations

import re

import pandas as pd

from oo_scan.config import Asset
from oo_scan.history import GradeChange
from oo_scan.pipeline import ScanFailure, ScanResult
from oo_scan.report_html import build_html_report, heat_style, sparkline_svg
from oo_scan.report_md import build_markdown_report
from oo_scan.score import grade as grade_of

NOW = pd.Timestamp("2026-08-03 07:30")

SHORT_SUBS = {
    "rsi": 12.0,
    "slow_d": 8.0,
    "percent_b": -4.0,
    "williams_r": 6.0,
    "cci": 20.0,
    "disparity20": 3.0,
}
LONG_SUBS = {"disparity200": 15.0, "range52w": 10.0, "range3y": 5.0, "yearly_return": -2.0}


def make_asset(
    asset_id: str = "BTC",
    name_ko: str = "비트코인",
    asset_class: str = "crypto",
    display_scale: float = 1.0,
    display_unit: str | None = None,
) -> Asset:
    """테스트용 Asset — crypto면 ccxt, 그 외 yfinance."""
    source = "ccxt" if asset_class == "crypto" else "yfinance"
    return Asset(
        id=asset_id,
        name_ko=name_ko,
        asset_class=asset_class,
        source=source,
        symbol=asset_id,
        exchanges=("binance",) if source == "ccxt" else (),
        display_scale=display_scale,
        display_unit=display_unit,
    )


def make_result(
    asset: Asset,
    total: float,
    *,
    short: float = 10.0,
    long_score: float = 20.0,
    close: float = 100.0,
    stale: bool = False,
    spark: list[float] | None = None,
    short_subs: dict[str, float] | None = None,
    long_subs: dict[str, float] | None = None,
    drawdown_pct: float = -12.5,
    days_since_peak: float = 42.0,
    range52w: float = 55.0,
    exchange_used: str | None = None,
) -> ScanResult:
    """테스트용 ScanResult — 등급은 total에서 자동 산정."""
    return ScanResult(
        asset=asset,
        asof=pd.Timestamp("2026-08-01"),
        close=close,
        bars=1100,
        short=short,
        long=long_score,
        total=total,
        grade=grade_of(total),
        rsi14=48.6,
        drawdown_pct=drawdown_pct,
        days_since_peak=days_since_peak,
        range52w=range52w,
        short_subs=dict(SHORT_SUBS) if short_subs is None else short_subs,
        long_subs=dict(LONG_SUBS) if long_subs is None else long_subs,
        exchange_used=exchange_used,
        stale=stale,
        spark=[100.0, 101.0, 99.5, 102.0] if spark is None else spark,
    )


def sample_world() -> tuple[list[ScanResult], list[ScanFailure], list[Asset], list[GradeChange]]:
    """등급 6종을 전부 커버하는 표준 시나리오 (광기~데이터 부족 + 실패 + skip + 변화)."""
    btc = make_result(make_asset(), 72.0, exchange_used="binance", spark=[1.0, 2.0, 3.0])
    spx = make_result(make_asset("SPX", "S&P500", "index"), 45.0)
    gold = make_result(make_asset("GOLD", "금", "commodity"), 10.0, close=3300.5)
    us10y = make_result(
        make_asset("US10Y", "미국 10년물 금리", "rate", display_scale=0.1, display_unit="%"),
        -10.0,
        close=42.5,
        stale=True,
    )
    kospi = make_result(
        make_asset("KOSPI", "코스피", "index"),
        -45.0,
        short_subs={**SHORT_SUBS, "williams_r": -90.0, "rsi": -70.0},
        long_subs={**LONG_SUBS, "range52w": -80.0},
        drawdown_pct=-32.5,
        days_since_peak=148.0,
        range52w=12.3,
    )
    vnm = make_result(make_asset("VNM", "베트남", "em_index"), -65.0)
    hype = make_result(make_asset("HYPE", "하이퍼리퀴드", "crypto"), float("nan"), spark=[])
    results = [btc, spx, gold, us10y, kospi, vnm, hype]
    failures = [ScanFailure(make_asset("WTI", "WTI 원유", "commodity"), "빈 응답 (백오프 3회 소진)")]
    skipped = [make_asset("DXY", "달러인덱스", "fx")]
    changes = [
        GradeChange("KOSPI", "2026-08-01", "소외", "중립"),
        GradeChange("SPX", "2026-08-01", "중립", "과열"),
        GradeChange("ETH", "2026-08-01", "중립", "소외"),
    ]
    return results, failures, skipped, changes


def _pos(text: str, pattern: str) -> int:
    """정규식 첫 매치 위치 — 없으면 실패."""
    m = re.search(pattern, text, flags=re.MULTILINE)
    assert m is not None, f"패턴 미발견: {pattern}"
    return m.start()


def _section(text: str, start: str, end: str) -> str:
    """start 헤딩부터 end 마커 직전까지의 조각."""
    i = text.index(start)
    j = text.index(end, i + len(start))
    return text[i:j]


# ── R1 마크다운 ─────────────────────────────────────────────────────────────


def test_markdown_sections_in_order() -> None:
    """§2.5 순서: 온도계 → 소외 존 → 광기 존 → 변화 감지 → 자산별 상세."""
    md = build_markdown_report(*sample_world(), NOW)
    positions = [
        _pos(md, r"^## 전체 온도계$"),
        _pos(md, r"^## 소외 존$"),
        _pos(md, r"^## 광기 존$"),
        _pos(md, r"^## 변화 감지$"),
        _pos(md, r"^## 자산별 상세$"),
    ]
    assert positions == sorted(positions)
    assert md.startswith("# 광기·소외 온도계 — 2026-08-03")
    assert "07:30 KST" in md


def test_markdown_summary_count_line() -> None:
    """한 줄 요약 카운트가 6개 등급 전부(0 포함)를 정확히 센다."""
    md = build_markdown_report(*sample_world(), NOW)
    assert "광기 1 · 과열 1 · 중립 2 · 소외 1 · 깊은 소외 1 · 데이터 부족 1" in md


def test_markdown_ranking_only_extreme_totals() -> None:
    """랭킹 표에는 |최종|≥30인 자산만 실린다."""
    md = build_markdown_report(*sample_world(), NOW)
    hot = _section(md, "## 과열·광기 랭킹", "## 소외·깊은 소외 랭킹")
    cold = _section(md, "## 소외·깊은 소외 랭킹", "## 소외 존")
    assert "비트코인(BTC)" in hot and "S&P500(SPX)" in hot
    assert "코스피(KOSPI)" in cold and "베트남(VNM)" in cold
    assert "금(GOLD)" not in hot and "금(GOLD)" not in cold  # +10 → 제외
    assert "미국 10년물 금리(US10Y)" not in cold  # -10 → 제외
    assert "하이퍼리퀴드(HYPE)" not in hot and "하이퍼리퀴드(HYPE)" not in cold  # NaN 제외


def test_markdown_ranking_includes_boundary_30() -> None:
    """경계값 ±30은 랭킹에 포함, 29는 제외."""
    results = [
        make_result(make_asset("AAA", "가나다", "index"), 30.0),
        make_result(make_asset("BBB", "라마바", "index"), -30.0),
        make_result(make_asset("CCC", "사아자", "index"), 29.0),
    ]
    md = build_markdown_report(results, [], [], [], NOW)
    hot = _section(md, "## 과열·광기 랭킹", "## 소외·깊은 소외 랭킹")
    cold = _section(md, "## 소외·깊은 소외 랭킹", "## 소외 존")
    assert "가나다(AAA)" in hot
    assert "라마바(BBB)" in cold
    assert "사아자(CCC)" not in hot and "사아자(CCC)" not in cold


def test_markdown_full_table_grouped_all_assets_and_stale() -> None:
    """전체 온도계는 모든 자산 포함, 자산군 그룹 순서 고정, STALE 표기."""
    results, failures, skipped, changes = sample_world()
    md = build_markdown_report(results, failures, skipped, changes, NOW)
    table = _section(md, "## 전체 온도계", "## 과열·광기 랭킹")
    for aid in ["BTC", "SPX", "GOLD", "US10Y", "KOSPI", "VNM", "HYPE"]:
        assert f"({aid})" in table
    assert "(STALE)" in table
    order = [table.index(f"### {g}") for g in ["크립토", "주요 지수", "신흥국 지수", "금리", "원자재"]]
    assert order == sorted(order)  # ASSET_CLASS_LABELS_KO 순서


def test_markdown_change_icons_and_opportunity_first() -> None:
    """변화 감지: 소외→중립 🔵, 중립→과열 🔴, 그 외 ·, 기회가 최상단."""
    md = build_markdown_report(*sample_world(), NOW)
    assert "🔵 KOSPI: 소외 → 중립 (직전 2026-08-01)" in md
    assert "🔴 SPX: 중립 → 과열 (직전 2026-08-01)" in md
    assert "· ETH: 중립 → 소외 (직전 2026-08-01)" in md
    sec = _section(md, "## 변화 감지", "## 자산별 상세")
    assert sec.index("🔵") < sec.index("🔴") < sec.index("· ETH")


def test_markdown_changes_empty() -> None:
    """변화가 없으면 '변화 없음'."""
    results, failures, skipped, _ = sample_world()
    md = build_markdown_report(results, failures, skipped, [], NOW)
    sec = _section(md, "## 변화 감지", "## 자산별 상세")
    assert "변화 없음" in sec


def test_markdown_neglect_zone_coldest_indicators() -> None:
    """소외 존: 가장 차가운 지표 한글명, 드로다운·개월 환산·52주 위치."""
    md = build_markdown_report(*sample_world(), NOW)
    sec = _section(md, "## 소외 존", "## 광기 존")
    assert "코스피(KOSPI)" in sec and "베트남(VNM)" in sec
    assert "차가운 지표" in sec
    assert "W%R" in sec and "52주 레인지" in sec and "RSI" in sec  # -90/-80/-70 하위 3개
    assert "-32.5%" in sec
    assert "약 7개월(148거래일)" in sec  # 148/21 ≈ 7개월
    assert "52주 레인지 위치 12.3%" in sec


def test_markdown_mania_zone_hottest_indicators() -> None:
    """광기 존: 과열·광기 자산과 가장 뜨거운 지표."""
    md = build_markdown_report(*sample_world(), NOW)
    sec = _section(md, "## 광기 존", "## 변화 감지")
    assert "비트코인(BTC)" in sec and "S&P500(SPX)" in sec
    assert "뜨거운 지표" in sec
    assert "CCI" in sec  # BTC 기본 서브점수 최고값(+20)


def test_markdown_data_gaps_failures_and_skipped() -> None:
    """데이터 누락에 실패 사유와 오프라인 skip 자산이 실린다."""
    md = build_markdown_report(*sample_world(), NOW)
    sec = _section(md, "### 데이터 누락", "### 각주")
    assert "WTI 원유(WTI): 빈 응답 (백오프 3회 소진)" in sec
    assert "달러인덱스(DXY)" in sec and "오프라인 skip" in sec
    footer = md[md.index("### 각주") :]
    assert "사용 거래소: BTC=binance" in footer
    assert "본 리포트는 투자 자문이 아니다" in footer


def test_markdown_display_unit_and_thousand_comma() -> None:
    """US10Y는 display_scale·unit 반영(4.25%), 종가는 천단위 콤마."""
    md = build_markdown_report(*sample_world(), NOW)
    assert "4.25%" in md  # 42.5 × 0.1 + '%'
    assert "3,300.50" in md  # GOLD 종가 콤마


def test_markdown_nan_total_lands_in_table_not_summary() -> None:
    """NaN 최종 온도(데이터 부족)는 크래시 없이 전체 표에만 실린다."""
    md = build_markdown_report(*sample_world(), NOW)
    table = _section(md, "## 전체 온도계", "## 과열·광기 랭킹")
    assert "하이퍼리퀴드(HYPE)" in table and "데이터 부족" in table
    summary = _section(md, "## 요약", "## 전체 온도계")
    assert "HYPE" not in summary


def test_markdown_empty_results_no_crash() -> None:
    """빈 입력도 5섹션 골격을 유지한다."""
    md = build_markdown_report([], [], [], [], NOW)
    assert md.startswith("# 광기·소외 온도계 — 2026-08-03")
    assert "광기 0" in md and "데이터 부족 0" in md
    assert "변화 없음" in md
    assert "현재 소외 구간 자산 없음" in md and "현재 과열·광기 구간 자산 없음" in md
    assert "누락 없음" in md


# ── R2 HTML ────────────────────────────────────────────────────────────────


def test_html_self_contained_no_external_resources() -> None:
    """외부 리소스 0: script/src/link/@import/절대 URL 전부 없음."""
    doc = build_html_report(*sample_world(), NOW)
    assert "<script" not in doc
    assert "src=" not in doc
    assert "<link" not in doc
    assert "@import" not in doc
    assert "http://" not in doc and "https://" not in doc


def test_html_meta_title_lang() -> None:
    """charset·viewport·title·lang=ko."""
    doc = build_html_report(*sample_world(), NOW)
    assert '<meta charset="utf-8">' in doc
    assert '<meta name="viewport"' in doc
    assert "<title>광기·소외 온도계</title>" in doc
    assert '<html lang="ko">' in doc


def test_html_summary_cards_counts() -> None:
    """요약 카드 5+1개와 등급별 카운트."""
    doc = build_html_report(*sample_world(), NOW)
    assert doc.count('class="card"') == 6
    for g in ["광기", "과열", "중립", "소외", "깊은 소외", "데이터 부족"]:
        assert g in doc
    assert '<div class="n">2</div>' in doc  # 중립 2종


def test_html_sparkline_svg_count_matches_results_with_spark() -> None:
    """스파크라인 SVG 수 == spark가 있는 결과 수 (빈 spark는 생략)."""
    results, failures, skipped, changes = sample_world()
    doc = build_html_report(results, failures, skipped, changes, NOW)
    with_spark = sum(1 for r in results if r.spark)
    assert with_spark == 6  # HYPE만 spark 없음
    assert doc.count("<svg") == with_spark
    assert doc.count("<polyline") == with_spark


def test_html_sparkline_flat_and_empty() -> None:
    """flat 시계열은 수평선, 빈 리스트는 빈 문자열."""
    svg = sparkline_svg([5.0, 5.0, 5.0], "#e53935")
    assert "<svg" in svg and "14.0" in svg  # 수평선 y=14
    assert sparkline_svg([], "#e53935") == ""


def test_html_heatmap_style_interpolation() -> None:
    """히트맵: -100 청색 ↔ 0 회백 ↔ +100 적색 선형 보간, NaN은 스타일 없음."""
    assert heat_style(100.0) == "background:rgba(178,24,43,0.92);color:#ffffff"
    assert heat_style(-100.0) == "background:rgba(33,102,172,0.92);color:#ffffff"
    assert heat_style(0.0) == "background:rgba(232,232,232,0.92);color:#1a1a1a"
    assert heat_style(float("nan")) == ""
    doc = build_html_report(*sample_world(), NOW)
    assert "background:rgba(" in doc  # 셀 inline style 존재


def test_html_backtest_relative_link() -> None:
    """각주에 backtest.html 상대 링크 (외부 리소스 아님)."""
    doc = build_html_report(*sample_world(), NOW)
    assert 'href="backtest.html"' in doc


def test_html_change_banner_and_stale_marker() -> None:
    """변화 배너에 🔵·🔴 (기회가 먼저), 온도계 표에 STALE 표기."""
    doc = build_html_report(*sample_world(), NOW)
    assert "🔵" in doc and "🔴" in doc
    assert doc.index("🔵") < doc.index("🔴")
    assert "STALE" in doc


def test_html_empty_results_no_crash() -> None:
    """빈 입력도 자급자족 문서를 만든다."""
    doc = build_html_report([], [], [], [], NOW)
    assert "<title>광기·소외 온도계</title>" in doc
    assert "변화 없음" in doc and "산출된 자산 없음" in doc
    assert doc.count("<svg") == 0
    assert "src=" not in doc and "<link" not in doc and "<script" not in doc
