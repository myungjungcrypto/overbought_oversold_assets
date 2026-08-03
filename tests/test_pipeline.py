"""파이프라인 테스트 (P1) — 픽스처 디렉토리를 OO_SCAN_DATA_DIR로 주입, 네트워크 없음."""

from pathlib import Path

import pandas as pd
import pytest

from oo_scan.cli import main
from oo_scan.config import load_config
from oo_scan.pipeline import exit_code_for, render_table, run_scan

FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture()
def fixture_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """픽스처 CSV를 데이터 디렉토리로 사용."""
    monkeypatch.setenv("OO_SCAN_DATA_DIR", str(FIXTURES))


def test_offline_scan_over_fixtures(fixture_env: None) -> None:
    """픽스처 6종은 산출, 나머지 22종은 skip, 실패 0."""
    cfg = load_config()
    results, failures, skipped = run_scan(cfg, offline=True, now=pd.Timestamp("2026-08-03"))
    ids = {r.asset.id for r in results}
    assert ids == {"BTC", "ETH", "SPX", "KOSPI", "US10Y", "HYPE"}
    assert not failures
    assert len(skipped) == 22
    for r in results:
        assert -100 <= r.total <= 100 or pd.isna(r.total)
        assert r.grade in {"광기", "과열", "중립", "소외", "깊은 소외", "데이터 부족"}


def test_hype_short_history_still_graded(fixture_env: None) -> None:
    """HYPE(220봉)는 60봉 이상이므로 등급이 산정된다 (§2.3)."""
    cfg = load_config()
    results, _, _ = run_scan(cfg, offline=True, ids=["HYPE"], now=pd.Timestamp("2026-08-03"))
    (hype,) = results
    assert hype.bars == 220
    assert hype.grade != "데이터 부족"


def test_us10y_no_volume_excludes_mfi(fixture_env: None) -> None:
    """US10Y(volume=0)는 MFI 제외, BTC는 포함."""
    cfg = load_config()
    results, _, _ = run_scan(cfg, offline=True, ids=["US10Y", "BTC"], now=pd.Timestamp("2026-08-03"))
    by_id = {r.asset.id: r for r in results}
    assert "mfi" not in by_id["US10Y"].short_subs
    assert "mfi" in by_id["BTC"].short_subs
    # display_scale: ^TNX 원값의 1/10이 표시 종가
    assert by_id["US10Y"].display_close == pytest.approx(by_id["US10Y"].close * 0.1)


def test_stale_flag(fixture_env: None) -> None:
    """마지막 봉이 5일(달력일) 초과 과거면 STALE."""
    cfg = load_config()
    fresh, _, _ = run_scan(cfg, offline=True, ids=["BTC"], now=pd.Timestamp("2026-08-03"))
    old, _, _ = run_scan(cfg, offline=True, ids=["BTC"], now=pd.Timestamp("2026-08-20"))
    assert fresh[0].stale is False  # 8/1 봉, 2일 경과
    assert old[0].stale is True  # 19일 경과


def test_failure_isolated(fixture_env: None, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """깨진 CSV 자산은 실패로 격리되고 나머지는 산출된다."""
    data = tmp_path / "data"
    data.mkdir()
    (data / "BTC_1d.csv").write_text(
        (FIXTURES / "BTC_1d.csv").read_text(encoding="utf-8"), encoding="utf-8"
    )
    (data / "ETH_1d.csv").write_text("date,open\nbroken", encoding="utf-8")
    monkeypatch.setenv("OO_SCAN_DATA_DIR", str(data))
    cfg = load_config()
    results, failures, _ = run_scan(
        cfg, offline=True, ids=["BTC", "ETH"], now=pd.Timestamp("2026-08-03")
    )
    assert [r.asset.id for r in results] == ["BTC"]
    assert len(failures) == 1 and failures[0].asset.id == "ETH"


def test_exit_code_policy() -> None:
    """§2.4 exit 정책: 오프라인 1개+, 라이브 70%."""
    assert exit_code_for(produced=1, attempted=6, offline=True) == 0
    assert exit_code_for(produced=0, attempted=6, offline=True) == 1
    assert exit_code_for(produced=20, attempted=28, offline=False) == 0  # 71%
    assert exit_code_for(produced=19, attempted=28, offline=False) == 1  # 68%
    assert exit_code_for(produced=0, attempted=0, offline=False) == 1


def test_cli_run_offline_no_write(fixture_env: None, capsys: pytest.CaptureFixture[str]) -> None:
    """CLI 통합: 표에 자산 5개 이상 + 등급 문자열이 나오고 exit 0."""
    rc = main(["run", "--offline", "--no-write"])
    out = capsys.readouterr().out
    assert rc == 0
    assert out.count("\n") >= 6
    assert any(g in out for g in ["광기", "과열", "중립", "소외", "깊은 소외"])
    assert "BTC" in out and "US10Y" in out


def test_write_outputs_creates_files_and_delta(fixture_env: None, tmp_path: Path) -> None:
    """R3: 산출물 5종+히스토리 생성, 이튿날 재실행 시 Δ전일 컬럼이 채워진다."""
    from oo_scan.pipeline import write_outputs

    cfg = load_config()
    reports, docs = tmp_path / "reports", tmp_path / "docs"
    results, failures, skipped = run_scan(cfg, offline=True, now=pd.Timestamp("2026-08-02"))
    write_outputs(results, failures, skipped, now=pd.Timestamp("2026-08-02 07:30"),
                  reports_dir=reports, docs_dir=docs)
    for name in ["2026-08-02.md", "2026-08-02.html", "latest.md", "latest.html", "history.csv"]:
        assert (reports / name).exists() or name == "history.csv" and (reports / name).exists()
    assert (docs / "index.html").exists()
    # 첫날은 직전 기록이 없어 Δ가 전부 '-'
    day1 = (reports / "latest.md").read_text(encoding="utf-8")
    assert "Δ전일" in day1
    # 이튿날 실행 → Δ 숫자(+/−/+0) 등장
    results2, f2, s2 = run_scan(cfg, offline=True, now=pd.Timestamp("2026-08-03"))
    write_outputs(results2, f2, s2, now=pd.Timestamp("2026-08-03 07:30"),
                  reports_dir=reports, docs_dir=docs)
    day2 = (reports / "latest.md").read_text(encoding="utf-8")
    import re

    assert re.search(r"\| [+-]\d+ \|", day2), "Δ전일 컬럼에 부호 있는 값이 있어야 한다"
    hist = (reports / "history.csv").read_text(encoding="utf-8")
    assert hist.count("2026-08-02") >= 6 and hist.count("2026-08-03") >= 6


def test_cli_run_offline_writes_files(
    fixture_env: None, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """CLI 통합: --no-write 없이 실행하면 reports/·docs/가 cwd에 생성된다."""
    monkeypatch.chdir(tmp_path)
    rc = main(["run", "--offline"])
    assert rc == 0
    assert (tmp_path / "reports" / "latest.md").exists()
    assert (tmp_path / "reports" / "history.csv").exists()
    assert (tmp_path / "docs" / "index.html").exists()
    assert "기록:" in capsys.readouterr().out


def test_render_table_sorted_desc(fixture_env: None) -> None:
    """표는 최종 온도 내림차순."""
    cfg = load_config()
    results, _, _ = run_scan(cfg, offline=True, now=pd.Timestamp("2026-08-03"))
    table = render_table(results)
    lines = [ln for ln in table.splitlines()[1:] if ln.strip()]
    totals = []
    for r in sorted(results, key=lambda r: -r.total):
        totals.append(r.asset.id)
    assert [ln.split()[0] for ln in lines][: len(totals)] == totals
