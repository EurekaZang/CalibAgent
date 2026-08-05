#!/usr/bin/env python3
"""Fail-fast audit for the anonymous ICRA ieeeconf submission artifact."""

from __future__ import annotations

import argparse
import hashlib
import re
import shutil
import subprocess
import sys
from pathlib import Path

OFFICIAL_IEEE_CONF_SHA256 = "4befef671c2a996889d325f5170d3387bf42aac9a37dcaa93724ad49816e4ec2"
MAX_UPLOAD_BYTES = 2_000_000


def require_command(name: str) -> str:
    executable = shutil.which(name)
    if executable is None:
        raise RuntimeError(f"required audit command is unavailable: {name}")
    return executable


def run_text(*command: str) -> str:
    return subprocess.run(
        command,
        check=True,
        capture_output=True,
        text=True,
    ).stdout


def parse_pdfinfo(pdf: Path) -> dict[str, str]:
    output = run_text(require_command("pdfinfo"), str(pdf))
    fields: dict[str, str] = {}
    for line in output.splitlines():
        if ":" in line:
            key, value = line.split(":", 1)
            fields[key.strip()] = value.strip()
    return fields


def audit_source(tex: Path, class_file: Path) -> list[str]:
    failures: list[str] = []
    source = tex.read_text(encoding="utf-8")
    class_digest = hashlib.sha256(class_file.read_bytes()).hexdigest()

    if class_digest != OFFICIAL_IEEE_CONF_SHA256:
        failures.append("ieeeconf.cls differs from the official PaperPlaza package")

    if not re.search(
        r"\\documentclass\[\s*letterpaper\s*,\s*10pt\s*,\s*conference\s*\]"
        r"\{ieeeconf\}",
        source,
    ):
        failures.append("document class must be ieeeconf in US-Letter 10-pt conference mode")

    required = {
        "printer-margin command": r"\\overrideIEEEmargins\b",
        "empty first-page style": r"\\thispagestyle\{empty\}",
        "empty running-page style": r"\\pagestyle\{empty\}",
        "anonymous author line": r"\\author\{Anonymous Authors\}",
        "IEEE bibliography style": r"\\bibliographystyle\{IEEEtran\}",
    }
    for label, pattern in required.items():
        if re.search(pattern, source) is None:
            failures.append(f"missing {label}")

    if r"\IEEEoverridecommandlockouts" in source and r"\thanks" not in source:
        failures.append("IEEE command lockouts are overridden although no \\thanks is used")

    forbidden = {
        "page-geometry package": r"\\usepackage(?:\[[^]]*\])?\{(?:geometry|fullpage|typearea)\}",
        "line-spacing package": r"\\usepackage(?:\[[^]]*\])?\{setspace\}",
        "manual page-layout mutation": (
            r"\\(?:setlength|addtolength)\s*\{\\(?:textwidth|textheight|columnsep|"
            r"topmargin|oddsidemargin|evensidemargin|headheight|headsep|footskip|"
            r"textfloatsep|floatsep|intextsep|abovecaptionskip|belowcaptionskip)\}"
        ),
        "manual line-spacing mutation": r"\\(?:linespread|setstretch|renewcommand\{\\baselinestretch\})",
        "manual pagination compression": r"\\(?:enlargethispage|newgeometry|restoregeometry)\b",
        "manual vertical-space compression": r"\\vspace\*?\s*\{\s*-",
    }
    for label, pattern in forbidden.items():
        if re.search(pattern, source, flags=re.IGNORECASE):
            failures.append(f"forbidden {label}")

    return failures


def audit_pdf(pdf: Path) -> list[str]:
    failures: list[str] = []
    info = parse_pdfinfo(pdf)

    try:
        pages = int(info.get("Pages", "0"))
    except ValueError:
        pages = 0
    if not 1 <= pages <= 8:
        failures.append(f"page count is {pages}; ICRA permits at most 8 pages")
    if "612 x 792 pts (letter)" not in info.get("Page size", ""):
        failures.append(f"page size is not US Letter: {info.get('Page size', 'unknown')}")
    if info.get("PDF version") != "1.4":
        failures.append(f"PDF version is {info.get('PDF version', 'unknown')}, not 1.4")
    if info.get("Optimized") != "yes":
        failures.append("PDF is not optimized for fast web viewing")
    if info.get("Encrypted") != "no":
        failures.append("PDF security/encryption must be disabled")
    if pdf.stat().st_size > MAX_UPLOAD_BYTES:
        failures.append(f"PDF is {pdf.stat().st_size} bytes; PaperPlaza upload limit is 2,000,000")

    fonts = run_text(require_command("pdffonts"), str(pdf))
    if re.search(r"\bType\s+3\b", fonts):
        failures.append("PDF contains a prohibited Type 3 font")
    for line in fonts.splitlines()[2:]:
        columns = re.search(
            r"\s+(yes|no)\s+(yes|no)\s+(yes|no)\s+\d+\s+\d+\s*$",
            line,
        )
        if columns and columns.group(1) != "yes":
            failures.append(f"PDF contains an unembedded font: {line.split()[0]}")

    attachments = run_text(require_command("pdfdetach"), "-list", str(pdf))
    if not attachments.lstrip().startswith("0 embedded files"):
        failures.append("submission PDF contains embedded file attachments")

    destinations = run_text(require_command("pdfinfo"), "-dests", str(pdf))
    if len(destinations.splitlines()) > 1:
        failures.append("submission PDF contains named destinations or bookmarks")
    urls = run_text(require_command("pdfinfo"), "-url", str(pdf))
    if len(urls.splitlines()) > 1:
        failures.append("submission PDF contains active URL links")

    return failures


def audit_log(log: Path) -> list[str]:
    if not log.exists():
        return [f"LaTeX build log is missing: {log}"]
    contents = log.read_text(encoding="utf-8", errors="replace")
    forbidden = {
        "overfull box": r"Overfull \\[hv]box",
        "undefined control sequence": r"Undefined control sequence",
        "undefined reference or citation": (
            r"LaTeX Warning: (?:Reference|Citation).*undefined|"
            r"There were undefined references"
        ),
        "LaTeX error": r"^! ",
    }
    return [
        label for label, pattern in forbidden.items() if re.search(pattern, contents, re.MULTILINE)
    ]


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--tex", type=Path, required=True)
    parser.add_argument("--pdf", type=Path, required=True)
    parser.add_argument("--class", dest="class_file", type=Path, required=True)
    parser.add_argument("--log", type=Path)
    args = parser.parse_args()

    failures = [
        *audit_source(args.tex, args.class_file),
        *audit_pdf(args.pdf),
        *(audit_log(args.log) if args.log is not None else []),
    ]
    if failures:
        for failure in failures:
            print(f"FAIL: {failure}", file=sys.stderr)
        return 1

    info = parse_pdfinfo(args.pdf)
    print(
        "PASS: official ieeeconf class; US Letter/10-pt/conference; "
        f"anonymous; {info['Pages']} pages; PDF {info['PDF version']}; "
        f"optimized; {args.pdf.stat().st_size} bytes; all fonts embedded; no Type 3 fonts"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
