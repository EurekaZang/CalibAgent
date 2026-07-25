"""Print the machine-verifiable strong P6/P7 readiness verdict."""

from __future__ import annotations

import argparse
from pathlib import Path

from calibagent.eval.strong_readiness import audit_strong_readiness


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--workspace", type=Path, default=Path.cwd())
    parser.add_argument("--output", type=Path)
    parser.add_argument(
        "--raw",
        action="store_true",
        help="scan and hash the full local output trees instead of compact evidence",
    )
    parser.add_argument("--require-ready", action="store_true")
    arguments = parser.parse_args()
    report = audit_strong_readiness(arguments.workspace, raw=arguments.raw)
    serialized = report.to_json()
    print(serialized)
    if arguments.output is not None:
        arguments.output.parent.mkdir(parents=True, exist_ok=True)
        arguments.output.write_text(serialized + "\n", encoding="utf-8")
    if arguments.require_ready and not report.ready:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
