"""파이프라인 스텁 — P1 노드에서 실제 구현으로 대체된다."""

from __future__ import annotations

import argparse


def cmd_run(args: argparse.Namespace) -> int:
    """run 서브커맨드 스텁."""
    print("run: 아직 구현되지 않음 (P1 노드에서 구현 예정)")
    return 0


def cmd_fetch(args: argparse.Namespace) -> int:
    """fetch 서브커맨드 스텁."""
    print("fetch: 아직 구현되지 않음 (P1 노드에서 구현 예정)")
    return 0
