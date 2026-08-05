from __future__ import annotations

import hashlib
import json
from collections import defaultdict
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
PAPER = ROOT / "paper"
MANIFEST = ROOT / "evidence" / "paper_figure_provenance" / "real_go2_navigation.json"


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def test_real_go2_figure_has_auditable_matched_time_provenance() -> None:
    record = json.loads(MANIFEST.read_text(encoding="utf-8"))
    source = ROOT / record["source_video"]
    assert source.is_file()
    assert sha256(source) == record["source_video_sha256"]

    frames = record["frames"]
    assert len(frames) == 12
    timestamps = [float(frame["video_timestamp_s"]) for frame in frames]
    assert len(timestamps) == len(set(timestamps))

    elapsed_by_scene: dict[str, dict[str, list[float]]] = defaultdict(lambda: defaultdict(list))
    for frame in frames:
        elapsed_by_scene[frame["scene"]][frame["condition"]].append(float(frame["elapsed_s"]))
    assert set(elapsed_by_scene) == {"Static I", "Static II", "Moving person"}
    for conditions in elapsed_by_scene.values():
        assert set(conditions) == {"direct_command", "gauge"}
        assert sorted(conditions["direct_command"]) == sorted(conditions["gauge"])

    for relative_path, expected_hash in record["outputs"].items():
        output = ROOT / relative_path
        assert output.is_file()
        assert sha256(output) == expected_hash


def test_real_go2_figure_is_used_and_described_as_qualitative() -> None:
    manuscript = (PAPER / "main.tex").read_text(encoding="utf-8")
    assert "figures/real_go2_navigation.pdf" in manuscript
    assert "zhang2025drldclp" in manuscript
    assert "five repetitions" in manuscript
    assert "qualitative" in manuscript
