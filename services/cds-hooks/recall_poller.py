"""
Populate the recall cache.

Two sources:
  1. demo recalls — curated, UDI-DI-keyed entries so the demo reliably lights up
     (Build.md Phase 5: "Pre-load at least 1 known recalled UDI for demo purposes").
  2. openFDA device/recall feed — real recall records. NOTE: openFDA's device
     recall endpoint is keyed by product code / firm and does NOT carry the
     UDI-DI, so these rows are stored for coverage/reference but generally won't
     match a specific scanned device. Production would integrate a UDI-DI-indexed
     recall source.

Run:  python recall_poller.py            # seed demo + best-effort openFDA pull
      python recall_poller.py --demo     # seed demo recalls only
"""

from __future__ import annotations

import sys

import requests

import recalls

OPENFDA_URL = "https://api.fda.gov/device/recall.json"

# Curated demo recalls keyed by real GUDID Device Identifiers used in testing.
# Clearly marked source="demo" — these are illustrative, not actual FDA recalls.
DEMO_RECALLS = [
    {
        "device_identifier": "08717648200274",  # Abbott XIENCE ALPINE stent
        "recall_number": "DEMO-Z-1234-2026",
        "classification": "Class II",
        "reason": "Demonstration recall: potential for delivery-system balloon "
        "non-deflation during deployment.",
        "recall_initiation_date": "2026-02-10",
        "status": "Open, Classified",
        "firm": "ABBOTT VASCULAR INC.",
        "source": "demo",
    },
    {
        "device_identifier": "00643169001763",  # Medtronic MOSAIC bioprosthesis
        "recall_number": "DEMO-Z-5678-2026",
        "classification": "Class I",
        "reason": "Demonstration recall: risk of premature structural valve "
        "deterioration in a specific lot range.",
        "recall_initiation_date": "2026-03-22",
        "status": "Open, Classified",
        "firm": "MEDTRONIC, INC.",
        "source": "demo",
    },
]


def seed_demo_recalls() -> int:
    recalls.init_db()
    for row in DEMO_RECALLS:
        recalls.upsert_recall(row)
    return len(DEMO_RECALLS)


def pull_openfda(limit: int = 100) -> int:
    """Best-effort pull of recent device recalls from openFDA. Returns row count."""
    recalls.init_db()
    try:
        resp = requests.get(OPENFDA_URL, params={"limit": limit}, timeout=30)
        resp.raise_for_status()
        results = resp.json().get("results", [])
    except Exception as exc:  # noqa: BLE001 - never let the poller crash startup
        print(f"[recall-poller] openFDA pull failed (continuing): {exc}")
        return 0

    stored = 0
    for r in results:
        ofda = r.get("openfda", {}) or {}
        # openFDA device recalls are not UDI-DI keyed; store the product code as a
        # surrogate identifier so the feed integration is demonstrable.
        di = (ofda.get("udi") or [None])[0] if isinstance(ofda.get("udi"), list) else None
        recalls.upsert_recall(
            {
                "device_identifier": di or "",
                "recall_number": r.get("product_res_number") or r.get("recall_number") or r.get("res_event_number") or "",
                "classification": r.get("classification") or r.get("product_classification"),
                "reason": r.get("reason_for_recall"),
                "recall_initiation_date": r.get("event_date_initiated"),
                "status": r.get("recall_status") or r.get("status"),
                "firm": r.get("recalling_firm"),
                "source": "openfda",
            }
        )
        stored += 1
    return stored


def main(argv: list[str]) -> int:
    demo = seed_demo_recalls()
    print(f"[recall-poller] seeded {demo} demo recalls")
    if "--demo" not in argv:
        n = pull_openfda()
        print(f"[recall-poller] stored {n} openFDA recall records")
    print(f"[recall-poller] total recalls in cache: {recalls.count()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
