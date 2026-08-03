"""CLI 테스트 (B2에서 시작, P1에서 오프라인 경로로 갱신).

주의: run은 P1부터 실구현이므로 테스트는 반드시 --offline + 픽스처 주입으로만 호출한다
(네트워크 금지 원칙).
"""

from pathlib import Path

import pytest

from oo_scan.cli import build_parser, main

FIXTURES = Path(__file__).parent / "fixtures"


def test_help_exits_zero(capsys: pytest.CaptureFixture[str]) -> None:
    """--help는 exit 0으로 종료하고 서브커맨드 목록을 보여준다."""
    with pytest.raises(SystemExit) as exc:
        build_parser().parse_args(["--help"])
    assert exc.value.code == 0
    out = capsys.readouterr().out
    for cmd in ("run", "fetch", "backtest"):
        assert cmd in out


def test_run_offline_returns_zero(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """오프라인 run은 픽스처만으로 exit 0."""
    monkeypatch.setenv("OO_SCAN_DATA_DIR", str(FIXTURES))
    assert main(["run", "--offline", "--no-write"]) == 0
    assert "BTC" in capsys.readouterr().out


def test_run_offline_empty_dir_returns_one(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """오프라인인데 로컬 데이터가 하나도 없으면 exit 1 (§2.4)."""
    monkeypatch.setenv("OO_SCAN_DATA_DIR", str(tmp_path))
    assert main(["run", "--offline", "--no-write"]) == 1


def test_backtest_offline_writes_reports(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """오프라인 backtest는 픽스처 자산으로 리포트 3종을 기록하고 exit 0 (K2)."""
    monkeypatch.setenv("OO_SCAN_DATA_DIR", str(FIXTURES))
    monkeypatch.chdir(tmp_path)
    assert main(["backtest", "--offline", "--assets", "BTC,HYPE"]) == 0
    assert (tmp_path / "reports" / "backtest.md").exists()
    assert (tmp_path / "reports" / "backtest.html").exists()
    assert (tmp_path / "docs" / "backtest.html").exists()
    md = (tmp_path / "reports" / "backtest.md").read_text(encoding="utf-8")
    assert "소외 진입" in md and "베이스라인" in md


def test_backtest_offline_empty_returns_one(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """데이터가 하나도 없으면 exit 1."""
    monkeypatch.setenv("OO_SCAN_DATA_DIR", str(tmp_path / "empty"))
    monkeypatch.chdir(tmp_path)
    assert main(["backtest", "--offline"]) == 1
