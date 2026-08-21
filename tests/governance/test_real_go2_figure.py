from __future__ import annotations

import hashlib
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
PAPER = ROOT / "paper"
MANIFEST = (
    ROOT
    / "evidence"
    / "paper_figure_provenance"
    / "real_dclp_long_exposure.json"
)


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def test_real_go2_figure_has_auditable_matched_time_provenance() -> None:
    record = json.loads(MANIFEST.read_text(encoding="utf-8"))
    assert record["panel_order"] == ["direct_command", "gauge"]

    timestamps = [float(value) for value in record["exposure_timestamps_s"]]
    opacities = [float(value) for value in record["exposure_opacities"]]
    assert len(timestamps) == len(opacities) == 11
    assert timestamps == sorted(timestamps)
    assert opacities == sorted(opacities, reverse=True)
    assert opacities[0] == 1.0
    assert opacities[-1] == 0.5

    for source in record["sources"].values():
        source_path = ROOT / source["path"]
        assert source_path.is_file()
        assert sha256(source_path) == source["sha256"]

    output = ROOT / record["output"]["path"]
    assert output.is_file()
    assert sha256(output) == record["output"]["sha256"]
    assert record["postprocessing"]["scope"].startswith("Annotation only")


def test_real_go2_figure_is_used_and_described_as_qualitative() -> None:
    manuscript = (PAPER / "main.tex").read_text(encoding="utf-8")
    assert "figures/real_dclp_long_exposure.png" in manuscript
    assert "zhang2025drldclp" in manuscript
    assert "qualitative" in manuscript.lower()
    assert "one complete run per condition" in manuscript.lower()
    assert "does not estimate" in manuscript.lower()
