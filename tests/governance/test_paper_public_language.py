from __future__ import annotations

import re
import shutil
import subprocess
from pathlib import Path

import pytest

WORKSPACE = Path(__file__).resolve().parents[2]
PAPER = WORKSPACE / "paper"

FORBIDDEN_PATTERNS = {
    "repository identifiers": re.compile(
        r"\b(?:hash|commit|checksum|sha[- ]?256|repository revision|planner configuration hash)\b",
        re.IGNORECASE,
    ),
    "long hexadecimal identifiers": re.compile(
        r"(?<![A-Za-z0-9])[0-9a-f]{12,}(?![A-Za-z0-9])",
        re.IGNORECASE,
    ),
    "internal phase codes": re.compile(r"\bP\d+\b"),
    "internal model codes": re.compile(r"\b(?:M|B)\d+\b"),
    "internal distortion-family names": re.compile(
        r"\b(?:affine_high|affine_low|mixed_low|tier_[a-z0-9_]+)\b",
        re.IGNORECASE,
    ),
    "development-facing method names": re.compile(
        r"\b(?:full-method|display seed|probe [0-9]+)\b",
        re.IGNORECASE,
    ),
}


def assert_public_language(text: str, source: Path) -> None:
    violations: list[str] = []
    for label, pattern in FORBIDDEN_PATTERNS.items():
        matches = sorted({match.group(0) for match in pattern.finditer(text)})
        if matches:
            violations.append(f"{label}: {matches}")
    assert not violations, f"reader-facing internal language in {source}: " + "; ".join(violations)


def test_manuscript_sources_use_public_language() -> None:
    for source in [PAPER / "main.tex", PAPER / "figures/calibagent_pipeline.tex"]:
        assert_public_language(source.read_text(encoding="utf-8"), source)


def test_rendered_manuscript_uses_public_language() -> None:
    executable = shutil.which("pdftotext")
    if executable is None:
        pytest.skip("pdftotext is required for the rendered-manuscript language audit")
    result = subprocess.run(
        [executable, "-layout", str(PAPER / "main.pdf"), "-"],
        check=True,
        capture_output=True,
        text=True,
    )
    assert_public_language(result.stdout, PAPER / "main.pdf")


def test_public_figure_filenames_do_not_encode_experiment_phases() -> None:
    names = [path.name for path in (PAPER / "figures").iterdir() if path.is_file()]
    coded = sorted(name for name in names if re.match(r"^[pP]\d+", name))
    assert not coded, f"phase-coded reader-facing figure filenames: {coded}"
