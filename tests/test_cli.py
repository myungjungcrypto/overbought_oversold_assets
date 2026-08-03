"""CLI 뼈대 테스트 (B2)."""

import pytest

from oo_scan.cli import build_parser, main


def test_help_exits_zero(capsys: pytest.CaptureFixture[str]) -> None:
    """--help는 exit 0으로 종료하고 서브커맨드 목록을 보여준다."""
    with pytest.raises(SystemExit) as exc:
        build_parser().parse_args(["--help"])
    assert exc.value.code == 0
    out = capsys.readouterr().out
    for cmd in ("run", "fetch", "backtest"):
        assert cmd in out


def test_run_stub_returns_zero(capsys: pytest.CaptureFixture[str]) -> None:
    """run 스텁은 exit 0."""
    assert main(["run", "--no-write"]) == 0
    assert "run" in capsys.readouterr().out


def test_backtest_stub_returns_zero() -> None:
    """backtest 스텁은 exit 0."""
    assert main(["backtest", "--offline"]) == 0
