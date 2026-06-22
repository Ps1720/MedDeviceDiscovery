#!/usr/bin/env python3
"""
End-to-end verification of the perioperative protocol layer against a RUNNING
PeriopUDI stack (read-only: uses /api/lookup/udi, never writes to a chart).

Usage:
    python3 scripts/verify_protocols.py [--base http://localhost:8090]

Checks, per known device identifier:
  1. /api/lookup/udi returns the expected protocol device class
  2. /api/protocol/by-di/<di>?context=mri switches context
  3. /api/admin/overrides lists the shipped demo overrides

The DIs below were harvested from openFDA's UDI feed and confirmed against
live AccessGUDID lookups on 2026-06-10.
"""

from __future__ import annotations

import argparse
import json
import sys
import urllib.request

# (device identifier, expected protocol class, label)
KNOWN_DEVICES = [
    ("00643169634589", "pacemaker", "Medtronic Azure XT DR MRI SureScan"),
    ("00763000519216", "dbs", "Medtronic Percept PC BrainSense"),
    ("05425025750405", "vns", "LivaNova VNS Therapy SenTiva Model 1000"),
    ("00389152000107", "closed_loop", "Tandem t:slim X2 with Control-IQ"),
    ("00199150047048", "closed_loop", "Medtronic MiniMed 780G"),
    ("00386270003584", "cgm", "Dexcom G7"),
    ("00643169001763", None, "Medtronic MOSAIC valve (expected: uncovered)"),
]

EXPECTED_OVERRIDE_IDS = {"ovr-mri-demo-pacemaker-001", "ovr-cgm-electrocautery-001"}


def call(base: str, path: str, payload: dict | None = None) -> dict:
    url = base.rstrip("/") + path
    if payload is None:
        req = urllib.request.Request(url)
    else:
        req = urllib.request.Request(
            url, data=json.dumps(payload).encode(),
            headers={"Content-Type": "application/json"},
        )
    with urllib.request.urlopen(req, timeout=60) as resp:
        return json.loads(resp.read())


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default="http://localhost:8090")
    args = ap.parse_args()

    failures = 0

    print(f"== Protocol class resolution via POST {args.base}/api/lookup/udi ==")
    for di, expected, label in KNOWN_DEVICES:
        try:
            data = call(args.base, "/api/lookup/udi", {"udi": di})
        except Exception as exc:  # noqa: BLE001
            print(f"  FAIL  {label}: request error: {exc}")
            failures += 1
            continue
        if not data.get("found"):
            print(f"  FAIL  {label}: not found in GUDID")
            failures += 1
            continue
        protocol = data.get("protocol")
        got = protocol.get("device_class") if protocol else None
        if got == expected:
            extra = ""
            if protocol:
                extra = (f" ({protocol['resolution']['confidence']} confidence, "
                         f"{len(protocol['facts'])} facts, "
                         f"{len(protocol['checklist'])} checklist items)")
            print(f"  ok    {label}: {got}{extra}")
        else:
            print(f"  FAIL  {label}: expected {expected}, got {got}")
            failures += 1

    print(f"\n== Context switching via GET /api/protocol/by-di/<di>?context=mri ==")
    di, _, label = KNOWN_DEVICES[0]
    try:
        data = call(args.base, f"/api/protocol/by-di/{di}?context=mri")
        ctx = (data.get("protocol") or {}).get("context")
        if data.get("found") and ctx == "mri":
            print(f"  ok    {label}: context switched to mri")
        else:
            print(f"  FAIL  {label}: found={data.get('found')} context={ctx}")
            failures += 1
    except Exception as exc:  # noqa: BLE001
        print(f"  FAIL  context switch: {exc}")
        failures += 1

    print(f"\n== Institutional overrides via GET /api/admin/overrides ==")
    try:
        data = call(args.base, "/api/admin/overrides")
        ids = {o.get("id") for o in data.get("overrides", [])}
        missing = EXPECTED_OVERRIDE_IDS - ids
        if not missing:
            print(f"  ok    {len(ids)} override(s) active, demo overrides present")
        else:
            print(f"  FAIL  missing demo overrides: {missing}")
            failures += 1
        if data.get("errors"):
            print(f"  WARN  override parse errors: {data['errors']}")
    except Exception as exc:  # noqa: BLE001
        print(f"  FAIL  admin overrides: {exc}")
        failures += 1

    print(f"\n{'ALL CHECKS PASSED' if not failures else f'{failures} CHECK(S) FAILED'}")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
