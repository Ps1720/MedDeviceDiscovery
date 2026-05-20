#!/usr/bin/env python3
"""
Validate FHIR resources against US Core v8.0.1 using the official HL7 FHIR
Validator CLI.

This is the offline/CI validation path (Build.md Phase 7). For fast local checks
during development, HAPI's $validate operation (see hapi_client.HapiClient.validate)
validates against the same IG already loaded into the running server.

Usage:
    python validate_against_ig.py <device.json> [<device2.json> ...]

On first run it downloads `validator_cli.jar` (cached next to this file) and the
US Core package. Requires Java 11+.

Exit code 0 if every file validates with no errors/fatals, 1 otherwise.
"""

from __future__ import annotations

import subprocess
import sys
import urllib.request
from pathlib import Path

VALIDATOR_URL = (
    "https://github.com/hapifhir/org.hl7.fhir.core/releases/latest/"
    "download/validator_cli.jar"
)
US_CORE_IG = "hl7.fhir.us.core#8.0.1"
HERE = Path(__file__).resolve().parent
JAR = HERE / "validator_cli.jar"


def ensure_validator() -> Path:
    if not JAR.exists():
        print(f"Downloading HL7 FHIR Validator CLI -> {JAR} ...", flush=True)
        urllib.request.urlretrieve(VALIDATOR_URL, JAR)
    return JAR


def validate(files: list[str]) -> int:
    if not files:
        print("usage: validate_against_ig.py <file.json> [...]", file=sys.stderr)
        return 2
    ensure_validator()
    cmd = [
        "java", "-jar", str(JAR),
        *files,
        "-version", "4.0.1",
        "-ig", US_CORE_IG,
    ]
    print("Running:", " ".join(cmd), flush=True)
    result = subprocess.run(cmd)
    return result.returncode


if __name__ == "__main__":
    raise SystemExit(validate(sys.argv[1:]))
