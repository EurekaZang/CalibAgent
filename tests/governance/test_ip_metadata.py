from __future__ import annotations

import re
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]


def _read(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def _project_version() -> str:
    match = re.search(
        r'(?m)^version\s*=\s*"([^"]+)"\s*$',
        _read("pyproject.toml"),
    )
    assert match is not None
    return match.group(1)


def test_citation_cff_matches_the_software_release() -> None:
    citation = yaml.safe_load(_read("CITATION.cff"))

    assert citation["cff-version"] == "1.2.0"
    assert citation["title"].startswith("CalibAgent:")
    assert citation["type"] == "software"
    assert citation["version"] == _project_version()
    assert citation["repository-code"] == "https://github.com/EurekaZang/CalibAgent"
    assert citation["license"] == "MIT"
    assert citation["license-url"].endswith("/LICENSE_SCOPE.md")
    assert {"name": "EurekaZang"} in citation["authors"]


def test_license_scope_is_explicit_and_non_retroactive() -> None:
    scope = _read("LICENSE_SCOPE.md")

    for required in (
        "MIT",
        "CC BY-NC-ND 4.0",
        "CC BY 4.0",
        "does not revoke",
        "third-party",
        "Earlier commits",
        "CITATION.cff",
    ):
        assert required in scope

    license_text = _read("LICENSE")
    assert license_text.startswith("MIT License")
    assert "EurekaZang and CalibAgent contributors" in license_text


def test_rights_chain_and_third_party_boundaries_are_documented() -> None:
    contributing = _read("CONTRIBUTING.md")
    notice = _read("NOTICE")
    publication = _read("docs/intellectual_property_and_publication.md")

    assert "Developer Certificate of Origin 1.1" in contributing
    assert "git commit -s" in contributing
    assert "not a copyright transfer" in contributing
    assert "third-party and file-specific material" in notice
    assert "NVIDIA Isaac Sim" in notice
    assert "Unitree Go2" in notice
    assert "does not protect scientific facts" in publication
    assert "do not upload the IEEE Xplore version of record" in publication
    assert "AI-generated material" in publication


def test_bilingual_readmes_expose_citation_and_mixed_license() -> None:
    for readme_path in ("README.md", "README_zh-CN.md"):
        readme = _read(readme_path)
        for required in (
            "CITATION.cff",
            "LICENSE_SCOPE.md",
            "NOTICE",
            "CC BY-NC-ND 4.0",
            "CC BY 4.0",
        ):
            assert required in readme
