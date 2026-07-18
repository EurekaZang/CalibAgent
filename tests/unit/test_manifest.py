from __future__ import annotations

import json

from calibagent.data.manifest import build_manifest, canonical_config_hash


def test_config_hash_is_order_independent() -> None:
    assert canonical_config_hash({"a": 1, "b": [2, 3]}) == canonical_config_hash(
        {"b": [2, 3], "a": 1}
    )
    assert canonical_config_hash({"a": 1}) != canonical_config_hash({"a": 2})


def test_manifest_is_serializable(tmp_path) -> None:
    manifest = build_manifest({"x": 1}, {"global": 4}, "replay", "M1", "lhs")
    path = tmp_path / "manifest.json"
    manifest.save_json(path)
    payload = json.loads(path.read_text())
    assert payload["random_seeds"] == {"global": 4}
    assert payload["schema_version"] == "1.0"
