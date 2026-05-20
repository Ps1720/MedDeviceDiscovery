"""
CDS Hooks recall-surveillance service.

Implements the CDS Hooks 2.0 discovery + service endpoints (cds-hooks.hl7.org):
  GET  /cds-services                 -> service catalog (one service: recall-check)
  POST /cds-services/recall-check    -> patient-view hook; returns warning Cards
                                        for any of the patient's devices that are
                                        under recall.

On startup it seeds the curated demo recalls so the workflow always has data.
"""

from __future__ import annotations

import os

import requests
from flask import Flask, jsonify, request

import recalls
import recall_poller

DEFAULT_FHIR = os.environ.get("FHIR_BASE_URL", "http://localhost:8080/fhir")
RECALL_SOURCE_URL = "https://api.fda.gov/device/recall.json"

app = Flask(__name__)

# Ensure the cache exists and the demo recalls are present on boot.
recalls.init_db()
recall_poller.seed_demo_recalls()


@app.route("/health")
def health():
    return jsonify({"status": "ok", "recalls_cached": recalls.count()})


@app.route("/cds-services")
def discovery():
    """CDS Hooks discovery — the service catalog."""
    return jsonify(
        {
            "services": [
                {
                    "hook": "patient-view",
                    "id": "recall-check",
                    "title": "FDA Device Recall Check",
                    "description": "Flags the patient's implanted/in-use devices that "
                    "are under an FDA recall, matched by UDI Device Identifier.",
                    "prefetch": {
                        "patient": "Patient/{{context.patientId}}"
                    },
                }
            ]
        }
    )


@app.route("/cds-services/recall-check", methods=["POST"])
def recall_check():
    """Execute the recall-check service for a patient-view hook."""
    body = request.get_json(silent=True) or {}
    context = body.get("context", {}) or {}
    patient_id = context.get("patientId")
    fhir_base = (body.get("fhirServer") or DEFAULT_FHIR).rstrip("/")

    if not patient_id:
        return jsonify({"cards": []})

    try:
        devices = _patient_devices(fhir_base, patient_id)
    except Exception as exc:  # noqa: BLE001
        return jsonify({"cards": [], "error": f"Could not read devices: {exc}"}), 200

    cards = []
    for device in devices:
        di = _device_identifier(device)
        for rec in recalls.recalls_for_di(di):
            cards.append(_recall_card(device, di, rec))

    return jsonify({"cards": cards})


def _patient_devices(fhir_base: str, patient_id: str) -> list[dict]:
    resp = requests.get(
        f"{fhir_base}/Device",
        params={"patient": f"Patient/{patient_id}"},
        headers={"Accept": "application/fhir+json"},
        timeout=20,
    )
    resp.raise_for_status()
    bundle = resp.json()
    return [e["resource"] for e in bundle.get("entry", []) if "resource" in e]


def _device_identifier(device: dict) -> str:
    carriers = device.get("udiCarrier") or []
    if carriers:
        return carriers[0].get("deviceIdentifier") or ""
    return ""


def _device_label(device: dict) -> str:
    names = device.get("deviceName") or []
    if names:
        return names[0].get("name") or "Device"
    dtype = device.get("type") or {}
    return dtype.get("text") or "Device"


def _recall_card(device: dict, di: str, rec: dict) -> dict:
    label = _device_label(device)
    cls = rec.get("classification") or "Recall"
    indicator = "critical" if (cls or "").strip().lower() in ("class i", "class 1") else "warning"
    detail = (
        f"**{cls}** — {rec.get('reason') or 'No reason provided.'}\n\n"
        f"- **Recall #:** {rec.get('recall_number') or '—'}\n"
        f"- **Firm:** {rec.get('firm') or '—'}\n"
        f"- **Initiated:** {rec.get('recall_initiation_date') or '—'}\n"
        f"- **Status:** {rec.get('status') or '—'}\n"
        f"- **Device:** {label} (UDI-DI {di})"
    )
    return {
        "summary": f"FDA recall: {label} — {cls}",
        "indicator": indicator,
        "detail": detail,
        "source": {
            "label": "FDA Device Recalls (openFDA / curated)",
            "url": RECALL_SOURCE_URL,
        },
        # Non-standard helper fields for our own UI (ignored by EHRs):
        "deviceIdentifier": di,
        "deviceId": device.get("id"),
        "classification": cls,
        "reason": rec.get("reason"),
        "recallNumber": rec.get("recall_number"),
    }


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5001)))
