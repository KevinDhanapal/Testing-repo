"""Command line interface for the multi-language code review agent."""
from __future__ import annotations

import argparse
import sys
from typing import List, Optional

from cragent.engine.config import Config, ConfigError
from cragent.engine.reporting import write_report
from cragent.engine.runner import scan


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="code-review-agent",
        description="Multi-language static code review across 13 quality dimensions "
                    "(Java, JavaScript, Python).",
    )
    parser.add_argument("--path", "-p", default=".", help="File or directory to scan")
    parser.add_argument("--config", "-c", help="Path to config.yaml / config.json")
    parser.add_argument("--out", "-o", action="append", default=None,
                        help="Output report path; repeatable. .json writes JSON, otherwise Markdown")
    parser.add_argument("--log-file", help="Override the log file path from the configuration")
    parser.add_argument("--workers", type=int, help="Override the number of parallel file workers")
    parser.add_argument("--max-files", type=int, help="Override the maximum number of files to scan")
    parser.add_argument("--verbose", "-v", action="store_true", help="Log progress to the console")
    parser.add_argument("--fail-on-gate", action="store_true",
                        help="Exit with status 1 when the quality gate fails")
    return parser


def main(argv: Optional[List[str]] = None) -> int:
    args = build_parser().parse_args(argv)
    overrides = {"limits": {}}
    if args.workers:
        overrides["limits"]["max_workers"] = args.workers
    if args.max_files:
        overrides["limits"]["max_files"] = args.max_files

    try:
        config = Config.load(args.config, overrides=overrides)
    except ConfigError as exc:
        print(f"Configuration error: {exc}", file=sys.stderr)
        return 2

    def progress(done: int, total: int, current: str) -> None:
        print(f"[{done}/{total}] {current}", file=sys.stderr)

    report = scan(
        path=args.path,
        config=config,
        verbose=args.verbose,
        progress=progress if args.verbose else None,
        log_file=args.log_file,
    )

    outputs = args.out or ["findings.md"]
    for out_path in outputs:
        write_report(report, out_path)

    score = report["overall_score"]
    print(
        f"Wrote {', '.join(outputs)}: score "
        f"{'N/A' if score is None else score}/100, gate {report['quality_gate']}, "
        f"{report['dimensions_passed']}/{report['dimensions_evaluated']} dimensions passed, "
        f"{report['files_scanned']} files scanned, {report['total_findings']} findings, "
        f"{len(report['errors'])} errors"
    )
    if args.fail_on_gate and report["quality_gate"] != "PASS":
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
