"""히스토리·변화 감지 테스트 (H1)."""

from pathlib import Path

import pandas as pd

from oo_scan.history import GradeChange, detect_changes, load_history, upsert_history


def _rows(**grades: str) -> list[dict]:
    return [
        {"asset_id": aid, "short": 1.0, "long": 2.0, "total": 3.0, "grade": g}
        for aid, g in grades.items()
    ]


def test_upsert_creates_and_overwrites(tmp_path: Path) -> None:
    """첫 upsert는 파일 생성, 같은 날짜 재실행은 덮어쓴다 (중복 없음)."""
    p = tmp_path / "history.csv"
    upsert_history(p, "2026-08-03", _rows(BTC="중립"))
    df = upsert_history(p, "2026-08-03", _rows(BTC="과열"))
    assert len(df) == 1
    assert df.iloc[0]["grade"] == "과열"


def test_upsert_appends_new_dates_sorted(tmp_path: Path) -> None:
    """다른 날짜는 누적되고 (date, asset_id) 정렬이 고정된다."""
    p = tmp_path / "history.csv"
    upsert_history(p, "2026-08-02", _rows(ETH="소외", BTC="중립"))
    df = upsert_history(p, "2026-08-03", _rows(BTC="중립", ETH="중립"))
    assert len(df) == 4
    assert df["date"].tolist() == ["2026-08-02", "2026-08-02", "2026-08-03", "2026-08-03"]
    assert df["asset_id"].tolist() == ["BTC", "ETH", "BTC", "ETH"]
    # 재로드해도 동일 (직렬화 안정성)
    assert load_history(p)["asset_id"].tolist() == ["BTC", "ETH", "BTC", "ETH"]


def test_detect_changes_finds_transition(tmp_path: Path) -> None:
    """소외→중립 전이는 기회(🔵), 중립→과열 진입은 경고(🔴)로 분류된다."""
    p = tmp_path / "history.csv"
    upsert_history(p, "2026-08-02", _rows(BTC="소외", ETH="중립", SPX="중립"))
    hist = upsert_history(p, "2026-08-03", _rows(BTC="중립", ETH="중립", SPX="과열"))
    changes = detect_changes(hist, "2026-08-03")
    assert [c.asset_id for c in changes] == ["BTC", "SPX"]
    btc, spx = changes
    assert btc.prev_grade == "소외" and btc.new_grade == "중립"
    assert btc.is_opportunity and btc.warming and not btc.is_warning
    assert spx.is_warning and not spx.is_opportunity


def test_deep_neglect_easing_is_opportunity() -> None:
    """깊은 소외→소외 완화도 기회 신호다."""
    c = GradeChange("X", "2026-08-02", "깊은 소외", "소외")
    assert c.is_opportunity


def test_detect_skips_new_assets_and_insufficient(tmp_path: Path) -> None:
    """직전 기록 없는 신규 자산과 '데이터 부족' 전이는 변화로 치지 않는다."""
    p = tmp_path / "history.csv"
    upsert_history(p, "2026-08-02", _rows(BTC="데이터 부족"))
    hist = upsert_history(p, "2026-08-03", _rows(BTC="중립", NEW="소외"))
    assert detect_changes(hist, "2026-08-03") == []


def test_detect_uses_most_recent_prior(tmp_path: Path) -> None:
    """휴장 등으로 며칠 비어도 가장 최근 직전 기록과 비교한다."""
    p = tmp_path / "history.csv"
    upsert_history(p, "2026-07-25", _rows(KOSPI="소외"))
    upsert_history(p, "2026-08-01", _rows(KOSPI="깊은 소외"))
    hist = upsert_history(p, "2026-08-03", _rows(KOSPI="소외"))
    (c,) = detect_changes(hist, "2026-08-03")
    assert c.prev_date == "2026-08-01"
    assert c.prev_grade == "깊은 소외" and c.new_grade == "소외"
    assert c.is_opportunity


def test_nan_scores_serialization(tmp_path: Path) -> None:
    """NaN 점수(데이터 부족)도 기록·재로드가 안전하다."""
    p = tmp_path / "history.csv"
    rows = [{"asset_id": "HYPE", "short": float("nan"), "long": None, "total": None,
             "grade": "데이터 부족"}]
    upsert_history(p, "2026-08-03", rows)
    df = load_history(p)
    assert df.iloc[0]["grade"] == "데이터 부족"
    assert pd.isna(df.iloc[0]["total_score"])
