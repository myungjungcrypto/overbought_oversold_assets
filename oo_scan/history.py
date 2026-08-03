"""스코어 히스토리 적재와 등급 변화 감지 (H1).

`reports/history.csv`에 run마다 당일 행을 upsert하고(같은 날짜 재실행은 덮어씀),
직전 기록과 비교해 등급이 움직인 자산을 찾아낸다.
정렬(date, asset_id 고정)로 diff가 안정적이라 커밋 충돌·중복이 없다 (§6).
"""

from __future__ import annotations

import csv
from dataclasses import dataclass
from pathlib import Path

import pandas as pd

from oo_scan.score import GRADE_INSUFFICIENT, GRADES

HISTORY_COLUMNS = ["date", "asset_id", "short_score", "long_score", "total_score", "grade"]


@dataclass(frozen=True)
class GradeChange:
    """자산 1종의 등급 변화."""

    asset_id: str
    prev_date: str
    prev_grade: str
    new_grade: str

    @property
    def warming(self) -> bool:
        """소외 쪽에서 광기 쪽으로 이동했는가 (온도 상승)."""
        return GRADES.index(self.new_grade) < GRADES.index(self.prev_grade)

    @property
    def is_opportunity(self) -> bool:
        """🔵 기회 형성 신호 — 깊은 소외→소외, 소외→중립 복귀 (§2.5)."""
        prev_i, new_i = GRADES.index(self.prev_grade), GRADES.index(self.new_grade)
        return prev_i >= 3 and new_i == prev_i - 1

    @property
    def is_warning(self) -> bool:
        """🔴 경고 신호 — 과열/광기 구간 진입."""
        prev_i, new_i = GRADES.index(self.prev_grade), GRADES.index(self.new_grade)
        return new_i <= 1 and new_i < prev_i


def load_history(path: Path) -> pd.DataFrame:
    """히스토리 CSV를 읽는다. 없으면 빈 프레임 (컬럼 보장)."""
    if not path.exists():
        return pd.DataFrame(columns=HISTORY_COLUMNS)
    df = pd.read_csv(path, dtype={"date": str, "asset_id": str, "grade": str})
    missing = [c for c in HISTORY_COLUMNS if c not in df.columns]
    if missing:
        raise ValueError(f"history.csv 컬럼 누락: {missing}")
    return df


def upsert_history(path: Path, run_date: str, rows: list[dict]) -> pd.DataFrame:
    """run 결과를 당일 날짜로 upsert하고 정렬해 저장한다.

    rows 항목 키: asset_id, short, long, total, grade. 같은 (date, asset_id)는 새 값이 이긴다.
    """
    df = load_history(path)
    new = pd.DataFrame(
        [
            {
                "date": run_date,
                "asset_id": r["asset_id"],
                "short_score": r.get("short"),
                "long_score": r.get("long"),
                "total_score": r.get("total"),
                "grade": r["grade"],
            }
            for r in rows
        ],
        columns=HISTORY_COLUMNS,
    )
    keep = df[~((df["date"] == run_date) & (df["asset_id"].isin(new["asset_id"])))]
    out = pd.concat([keep, new], ignore_index=True)
    out = out.sort_values(["date", "asset_id"], kind="stable").reset_index(drop=True)
    path.parent.mkdir(parents=True, exist_ok=True)
    out.to_csv(path, index=False, float_format="%.2f", quoting=csv.QUOTE_MINIMAL)
    return out


def previous_totals(history: pd.DataFrame, run_date: str) -> dict[str, float]:
    """run_date 직전 기록의 자산별 최종 온도 (Δ전일 컬럼용). NaN은 제외한다."""
    past = history[history["date"] < run_date]
    out: dict[str, float] = {}
    for asset_id, grp in past.groupby("asset_id"):
        latest = grp.sort_values("date").iloc[-1]
        total = latest["total_score"]
        if pd.notna(total):
            out[str(asset_id)] = float(total)
    return out


def detect_changes(history: pd.DataFrame, run_date: str) -> list[GradeChange]:
    """run_date의 각 자산을 직전 기록과 비교해 등급 변화를 찾는다.

    직전 기록이 없는 자산(신규)과 '데이터 부족'이 낀 전이는 제외한다.
    """
    changes: list[GradeChange] = []
    today = history[history["date"] == run_date]
    past = history[history["date"] < run_date]
    for _, row in today.iterrows():
        prior = past[past["asset_id"] == row["asset_id"]]
        if prior.empty:
            continue
        prev = prior.sort_values("date").iloc[-1]
        prev_grade, new_grade = str(prev["grade"]), str(row["grade"])
        if GRADE_INSUFFICIENT in (prev_grade, new_grade):
            continue
        if prev_grade != new_grade:
            changes.append(
                GradeChange(
                    asset_id=str(row["asset_id"]),
                    prev_date=str(prev["date"]),
                    prev_grade=prev_grade,
                    new_grade=new_grade,
                )
            )
    return sorted(changes, key=lambda c: c.asset_id)
