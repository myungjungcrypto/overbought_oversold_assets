"""CLI 정의 — run / fetch / backtest 서브커맨드.

서브커맨드 본체는 각 모듈(pipeline, backtest)이 구현하며,
여기서는 인자 파싱과 디스패치만 담당한다.
"""

from __future__ import annotations

import argparse


def build_parser() -> argparse.ArgumentParser:
    """공용 argparse 파서를 구성한다."""
    parser = argparse.ArgumentParser(
        prog="oo_scan",
        description="크로스에셋 광기-소외 온도계 (자산배분 관점의 과매수/과매도 스캐너)",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    def add_common(p: argparse.ArgumentParser) -> None:
        p.add_argument("--offline", action="store_true", help="네트워크 금지, 로컬 데이터만 사용")
        p.add_argument("--assets", type=str, default=None, help="쉼표 구분 자산 ID 필터")

    p_run = sub.add_parser("run", help="전 자산 스캔 후 리포트 생성")
    add_common(p_run)
    p_run.add_argument("--no-write", action="store_true", help="파일 미기록, stdout 표만 출력")
    p_run.add_argument("--no-cache", action="store_true", help="캐시 무시하고 새로 페치")

    p_fetch = sub.add_parser("fetch", help="데이터만 받아 캐시에 저장")
    add_common(p_fetch)

    p_bt = sub.add_parser("backtest", help="소외 매수 가설 백테스트 리포트 생성")
    add_common(p_bt)

    return parser


def main(argv: list[str] | None = None) -> int:
    """CLI 진입점. exit code를 반환한다."""
    args = build_parser().parse_args(argv)
    if args.command == "run":
        from oo_scan.pipeline import cmd_run

        return cmd_run(args)
    if args.command == "fetch":
        from oo_scan.pipeline import cmd_fetch

        return cmd_fetch(args)
    if args.command == "backtest":
        from oo_scan.backtest import cmd_backtest

        return cmd_backtest(args)
    return 2  # 도달 불가 (required=True)
