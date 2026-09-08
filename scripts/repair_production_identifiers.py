#!/usr/bin/env python3
"""
One-off data repair: strip bogus production identifiers from Device resources.

Background
----------
GUDID returns `lotBatch`, `serialNumber`, `expirationDate` and
`manufacturingDate` as BOOLEAN FLAGS — "does this device carry a lot number?" —
not as the identifiers themselves. The mapper read them as values, so every
Device documented through PeriopUDI was written with

    "serialNumber": "True",
    "lotNumber": "False"

Schema-valid, and therefore silently accepted by validation, but clinically
meaningless: those fields are meant to hold the actual production identifiers
read off the package.

The mapper is fixed (gudid_to_uscore_device.py now takes production identifiers
only from a scanned UDI). This script cleans up records written before the fix.

Usage
-----
    python scripts/repair_production_identifiers.py            # dry run
    python scripts/repair_production_identifiers.py --apply    # write changes

Back up first:  ./scripts/backup_hapi.sh
"""

from __future__ import annotations

import argparse
import os
import sys

import requests

FHIR_BASE = os.environ.get("FHIR_BASE_URL", "http://localhost:8080/fhir")
JSON = "application/fhir+json"
BOGUS = {"True", "False", "true", "false"}
FIELDS = ("serialNumber", "lotNumber", "expirationDate", "manufactureDate")


def find_affected(session: requests.Session) -> list[dict]:
    """Every Device whose production-identifier fields hold a boolean string."""
    affected, url = [], f"{FHIR_BASE}/Device?_count=200"
    while url:
        r = session.get(url, headers={"Accept": JSON}, timeout=60)
        r.raise_for_status()
        bundle = r.json()
        for entry in bundle.get("entry", []):
            d = entry.get("resource", {})
            if any(d.get(f) in BOGUS for f in FIELDS):
                affected.append(d)
        url = next(
            (l["url"] for l in bundle.get("link", []) if l.get("relation") == "next"),
            None,
        )
    return affected


def repair(device: dict) -> tuple[dict, list[str]]:
    """Return (cleaned resource, list of removed fields)."""
    removed = [f for f in FIELDS if device.get(f) in BOGUS]
    cleaned = {k: v for k, v in device.items() if k not in removed}
    return cleaned, removed


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--apply", action="store_true", help="write changes (default: dry run)")
    args = ap.parse_args()

    session = requests.Session()
    print(f"FHIR server: {FHIR_BASE}")

    try:
        affected = find_affected(session)
    except requests.RequestException as exc:
        print(f"Could not reach the FHIR server: {exc}", file=sys.stderr)
        return 1

    if not affected:
        print("No Device resources carry bogus production identifiers. Nothing to do.")
        return 0

    print(f"\n{len(affected)} Device resource(s) affected:\n")
    for d in affected:
        _, removed = repair(d)
        vals = ", ".join(f"{f}={d.get(f)!r}" for f in removed)
        name = (d.get("deviceName") or [{}])[0].get("name", "?")
        print(f"  Device/{d['id']:<8} {name[:38]:40} {vals}")

    if not args.apply:
        print("\nDry run. Re-run with --apply to write these changes.")
        return 0

    print()
    ok = failed = 0
    for d in affected:
        cleaned, removed = repair(d)
        try:
            r = session.put(
                f"{FHIR_BASE}/Device/{d['id']}",
                json=cleaned,
                headers={"Content-Type": JSON, "Accept": JSON},
                timeout=30,
            )
            if r.status_code < 300:
                ok += 1
                print(f"  Device/{d['id']}: removed {', '.join(removed)}")
            else:
                failed += 1
                print(f"  Device/{d['id']}: HTTP {r.status_code} {r.text[:120]}")
        except requests.RequestException as exc:
            failed += 1
            print(f"  Device/{d['id']}: {exc}")

    print(f"\nrepaired {ok}, failed {failed}")
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
