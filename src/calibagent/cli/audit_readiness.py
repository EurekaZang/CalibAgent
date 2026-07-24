"""Print the machine-verifiable P0-P7 publication-readiness verdict."""

from __future__ import annotations

import argparse
from pathlib import Path

from calibagent.eval.readiness import audit_publication_readiness


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--workspace", type=Path, default=Path.cwd())
    parser.add_argument("--output", type=Path)
    parser.add_argument("--require-ready", action="store_true")
    arguments = parser.parse_args()
    report = audit_publication_readiness(arguments.workspace)
    serialized = report.to_json()
    print(serialized)
    if arguments.output is not None:
        arguments.output.parent.mkdir(parents=True, exist_ok=True)
        arguments.output.write_text(serialized + "\n", encoding="utf-8")
    if arguments.require_ready and not report.ready:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
