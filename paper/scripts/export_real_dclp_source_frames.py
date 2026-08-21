#!/usr/bin/env python3
"""Export the unprocessed source frames selected for the real-Go2 figure."""

from __future__ import annotations

import hashlib
import json
import shutil
import struct
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
PAPER = ROOT / "paper"
OUTPUT_DIR = PAPER / "figures" / "real_dclp_source_frames"
TARGET_TIMESTAMPS_S = (0.8, 1.64, 2.48, 3.32, 4.16, 5.0, 5.84, 6.68, 7.52, 8.36, 9.2)

CONDITIONS = (
    {
        "id": "direct_command",
        "short_name": "direct",
        "label": "DRL-DCLP direct velocity commands",
        "video": PAPER / "figures" / "uncalib.mp4",
    },
    {
        "id": "gauge",
        "short_name": "gauge",
        "label": "DRL-DCLP followed by GAUGE command compensation",
        "video": PAPER / "figures" / "calib.mp4",
    },
)


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def run_json(command: list[str]) -> dict[str, object]:
    result = subprocess.run(command, check=True, capture_output=True, text=True)
    payload = json.loads(result.stdout)
    if not isinstance(payload, dict):
        raise TypeError("expected a JSON object")
    return payload


def probe_video(path: Path) -> dict[str, object]:
    ffprobe = shutil.which("ffprobe")
    if ffprobe is None:
        raise RuntimeError("ffprobe is required")
    payload = run_json(
        [
            ffprobe,
            "-v",
            "error",
            "-select_streams",
            "v:0",
            "-show_entries",
            "stream=width,height,pix_fmt,avg_frame_rate,nb_frames:format=duration",
            "-of",
            "json",
            str(path),
        ]
    )
    streams = payload.get("streams")
    formats = payload.get("format")
    if not isinstance(streams, list) or not streams or not isinstance(formats, dict):
        raise ValueError(f"invalid ffprobe output for {path}")
    stream = streams[0]
    if not isinstance(stream, dict):
        raise TypeError("invalid stream metadata")
    return {
        "width": int(stream["width"]),
        "height": int(stream["height"]),
        "pixel_format": str(stream["pix_fmt"]),
        "average_frame_rate": str(stream["avg_frame_rate"]),
        "container_duration_s": float(formats["duration"]),
    }


def frame_timestamps(path: Path) -> list[float]:
    ffprobe = shutil.which("ffprobe")
    if ffprobe is None:
        raise RuntimeError("ffprobe is required")
    payload = run_json(
        [
            ffprobe,
            "-v",
            "error",
            "-select_streams",
            "v:0",
            "-show_frames",
            "-show_entries",
            "frame=best_effort_timestamp_time",
            "-of",
            "json",
            str(path),
        ]
    )
    frames = payload.get("frames")
    if not isinstance(frames, list):
        raise ValueError(f"missing frame list for {path}")
    timestamps: list[float] = []
    for frame in frames:
        if not isinstance(frame, dict) or "best_effort_timestamp_time" not in frame:
            raise ValueError(f"missing frame timestamp for {path}")
        timestamps.append(float(frame["best_effort_timestamp_time"]))
    if not timestamps:
        raise ValueError(f"no decoded frames in {path}")
    return timestamps


def nearest_frame_index(timestamps: list[float], target_s: float) -> int:
    return min(range(len(timestamps)), key=lambda index: abs(timestamps[index] - target_s))


def timestamp_token(timestamp_s: float) -> str:
    return f"{timestamp_s:.6f}".replace(".", "p")


def extract_frame(video: Path, frame_index: int, output: Path) -> None:
    ffmpeg = shutil.which("ffmpeg")
    if ffmpeg is None:
        raise RuntimeError("ffmpeg is required")
    filter_expression = f"select=eq(n\\,{frame_index})"
    subprocess.run(
        [
            ffmpeg,
            "-hide_banner",
            "-loglevel",
            "error",
            "-y",
            "-i",
            str(video),
            "-vf",
            filter_expression,
            "-frames:v",
            "1",
            "-pix_fmt",
            "rgb48be",
            "-compression_level",
            "9",
            str(output),
        ],
        check=True,
    )


def inspect_png(path: Path) -> dict[str, int]:
    with path.open("rb") as handle:
        signature = handle.read(8)
        if signature != b"\x89PNG\r\n\x1a\n":
            raise ValueError(f"not a PNG: {path}")
        length = struct.unpack(">I", handle.read(4))[0]
        chunk_type = handle.read(4)
        if chunk_type != b"IHDR" or length != 13:
            raise ValueError(f"invalid PNG header: {path}")
        width, height, bit_depth, color_type, _, _, _ = struct.unpack(">IIBBBBB", handle.read(13))
    if color_type != 2:
        raise ValueError(f"expected truecolor RGB PNG: {path}")
    return {"width": width, "height": height, "bit_depth_per_channel": bit_depth}


def build_readme(records: list[dict[str, object]]) -> str:
    lines = [
        "# Real-Go2 DCLP source frames",
        "",
        "These PNG files are the unprocessed source frames selected for the paired",
        "long-exposure comparison. They are decoded at the native video dimensions",
        "as 16-bit RGB PNGs. No crop, resizing, masking, brightness adjustment,",
        "annotation, or foreground extraction has been applied.",
        "",
        "- `direct_*.png`: DRL-DCLP direct velocity commands (`uncalib.mp4`).",
        "- `gauge_*.png`: DRL-DCLP followed by GAUGE (`calib.mp4`).",
        "- The two conditions use the same 11 requested elapsed times.",
        "- Exact decoded timestamps and source-frame indices are in `manifest.json`.",
        "",
        "| Order | Requested time (s) | Direct frame | GAUGE frame |",
        "|---:|---:|---|---|",
    ]
    by_order: dict[int, dict[str, dict[str, object]]] = {}
    for record in records:
        order = int(record["order"])
        condition = str(record["condition"])
        by_order.setdefault(order, {})[condition] = record
    for order in sorted(by_order):
        pair = by_order[order]
        direct = pair["direct_command"]
        gauge = pair["gauge"]
        lines.append(
            f"| {order:02d} | {float(direct['requested_time_s']):.2f} | "
            f"`{direct['filename']}` | `{gauge['filename']}` |"
        )
    return "\n".join(lines) + "\n"


def main() -> None:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    for stale in OUTPUT_DIR.glob("*.png"):
        stale.unlink()

    records: list[dict[str, object]] = []
    sources: dict[str, dict[str, object]] = {}
    for condition in CONDITIONS:
        video = Path(condition["video"])
        if not video.is_file():
            raise FileNotFoundError(video)
        info = probe_video(video)
        timestamps = frame_timestamps(video)
        sources[str(condition["id"])] = {
            "path": str(video.relative_to(ROOT)),
            "sha256": sha256(video),
            "decoded_frame_count": len(timestamps),
            **info,
        }
        for order, requested_time_s in enumerate(TARGET_TIMESTAMPS_S, start=1):
            frame_index = nearest_frame_index(timestamps, requested_time_s)
            decoded_time_s = timestamps[frame_index]
            filename = (
                f"{condition['short_name']}_{order:02d}_"
                f"t{timestamp_token(decoded_time_s)}_f{frame_index:05d}.png"
            )
            output = OUTPUT_DIR / filename
            extract_frame(video, frame_index, output)
            png_info = inspect_png(output)
            records.append(
                {
                    "condition": condition["id"],
                    "condition_label": condition["label"],
                    "order": order,
                    "requested_time_s": requested_time_s,
                    "decoded_time_s": decoded_time_s,
                    "frame_index_zero_based": frame_index,
                    "filename": filename,
                    "sha256": sha256(output),
                    "bytes": output.stat().st_size,
                    **png_info,
                }
            )

    manifest = {
        "schema_version": 1,
        "generator": str(Path(__file__).resolve().relative_to(ROOT)),
        "purpose": "Unprocessed source frames for author-composed long exposure",
        "requested_timestamps_s": list(TARGET_TIMESTAMPS_S),
        "pixel_policy": (
            "Native dimensions; decoded to 16-bit RGB PNG; no crop, resize, mask, "
            "brightness change, annotation, or foreground extraction."
        ),
        "sources": sources,
        "frames": records,
    }
    (OUTPUT_DIR / "manifest.json").write_text(
        json.dumps(manifest, indent=2) + "\n",
        encoding="utf-8",
    )
    (OUTPUT_DIR / "README.md").write_text(build_readme(records), encoding="utf-8")
    print(f"Wrote {len(records)} source frames to {OUTPUT_DIR.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
