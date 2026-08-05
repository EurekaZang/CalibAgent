from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
PAPER = ROOT / "paper"


def test_ieeeconf_submission_artifact_is_compliant() -> None:
    required_commands = ("pdfinfo", "pdffonts", "pdfdetach")
    missing = [name for name in required_commands if shutil.which(name) is None]
    if missing:
        pytest.skip(f"PDF compliance tools are unavailable: {', '.join(missing)}")

    result = subprocess.run(
        [
            sys.executable,
            str(PAPER / "scripts/check_ieeeconf_compliance.py"),
            "--tex",
            str(PAPER / "main.tex"),
            "--pdf",
            str(PAPER / "main.pdf"),
            "--class",
            str(PAPER / "ieeeconf.cls"),
        ],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stdout + result.stderr
