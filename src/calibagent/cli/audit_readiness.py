"""Print the machine-verifiable P0-P3 publication-readiness verdict."""

from __future__ import annotations

import argparse
from pathlib import Path

from calibagent.eval.readiness import audit_publication_readiness


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--workspace", type=Path, default=Path.cwd())
    parser.add_argument("--require-ready", action="store_true")
    arguments = parser.parse_args()
    report = audit_publication_readiness(arguments.workspace)
    print(report.to_json())
    if arguments.require_ready and not report.ready:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
