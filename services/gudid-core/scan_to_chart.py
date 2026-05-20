"""
Scan-to-chart orchestration (Phase 3).

Ties together the existing GUDID client, the fhir-bridge mapper, and HAPI:

    UDI scan -> parse -> GUDID lookup -> US Core Device -> write to HAPI
             -> (optional) link to a Procedure -> log the operation

Also provides the patient-picker feed and the per-patient device timeline.
"""

from __future__ import annotations

import csv
import os
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

import requests

from gudid_service import parse_udi, get_device_from_gudid
from gudid_to_uscore_device import map_to_device, US_CORE_IMPLANTABLE_DEVICE
from hapi_client import HapiClient, FhirError

FHIR_BASE_URL = os.environ.get("FHIR_BASE_URL", "http://localhost:8080/fhir")
# Browser-reachable base for display links (the container talks to HAPI via the
# internal "hapi" hostname, but the user's browser needs localhost).
PUBLIC_FHIR_BASE_URL = os.environ.get("PUBLIC_FHIR_BASE_URL", "http://localhost:8080/fhir")
SCAN_LOG = Path(os.environ.get("SCAN_LOG_PATH", "eval/usage_logs/scans.csv"))
_SCAN_LOG_FIELDS = [
    "timestamp",
    "user",
    "udi",
    "device_identifier",
    "patient_id",
    "device_id",
    "time_to_complete_ms",
    "success",
]


def _client() -> HapiClient:
    return HapiClient(FHIR_BASE_URL)


def _resolve_di(udi: str) -> tuple[str, Optional[str], Optional[str]]:
    """
    Return (device_identifier, issuing_agency, udi_hrf) for a scanned string.

    A pure-numeric string is treated as a Device Identifier (DI). Anything else
    is parsed via GUDID to extract the DI and issuing agency.
    """
    udi = udi.strip()
    if udi.isdigit():
        return udi, None, udi
    parsed = parse_udi(udi)
    if parsed and parsed.get("di"):
        return parsed["di"], parsed.get("issuing_agency"), udi
    # Fall back to using the raw string as the DI.
    return udi, None, udi


def document_device(
    udi: str,
    patient_id: str,
    procedure_id: Optional[str] = None,
    user: str = "demo",
) -> dict:
    """
    Execute the scan-to-chart workflow and log it. Returns a result dict
    suitable for JSON serialization.
    """
    started = time.perf_counter()
    device_id = None
    di = None
    success = False
    try:
        if not udi or not udi.strip():
            return {"success": False, "error": "No UDI provided"}
        if not patient_id or not str(patient_id).strip():
            return {"success": False, "error": "No patient selected"}

        di, issuing_agency, udi_hrf = _resolve_di(udi)

        record = get_device_from_gudid(di)
        if not record:
            return {
                "success": False,
                "error": f"Device {di} not found in FDA GUDID",
                "device_identifier": di,
            }

        device = map_to_device(
            record,
            patient_id=str(patient_id).strip(),
            udi_hrf=udi_hrf,
            issuing_agency=issuing_agency,
        )

        client = _client()
        device_id = client.create_device(device)

        if procedure_id:
            client.link_to_procedure(device_id, procedure_id)

        success = True
        return {
            "success": True,
            "device_id": device_id,
            "device_identifier": di,
            "patient_id": str(patient_id).strip(),
            "fhir_url": f"{PUBLIC_FHIR_BASE_URL}/Device/{device_id}",
            "brand_name": record.get("brand_name"),
            "manufacturer": record.get("manufacturer"),
            "type": record.get("type"),
            "profile": US_CORE_IMPLANTABLE_DEVICE,
        }
    except FhirError as exc:
        return {"success": False, "error": str(exc), "device_identifier": di}
    except Exception as exc:  # noqa: BLE001 - surface any failure to the UI
        return {"success": False, "error": f"{type(exc).__name__}: {exc}", "device_identifier": di}
    finally:
        elapsed_ms = int((time.perf_counter() - started) * 1000)
        _log_scan(
            {
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "user": user,
                "udi": udi,
                "device_identifier": di or "",
                "patient_id": patient_id,
                "device_id": device_id or "",
                "time_to_complete_ms": elapsed_ms,
                "success": success,
            }
        )


def _log_scan(row: dict) -> None:
    try:
        SCAN_LOG.parent.mkdir(parents=True, exist_ok=True)
        new_file = not SCAN_LOG.exists()
        with SCAN_LOG.open("a", newline="") as fh:
            writer = csv.DictWriter(fh, fieldnames=_SCAN_LOG_FIELDS)
            if new_file:
                writer.writeheader()
            writer.writerow(row)
    except Exception as exc:  # logging must never break the workflow
        print(f"[scan-to-chart] failed to log scan: {exc}")


def list_patients(limit: int = 50) -> list[dict]:
    """Return [{id, name}] for the patient picker, sorted by name."""
    resp = requests.get(
        f"{FHIR_BASE_URL}/Patient",
        params={"_count": limit, "_elements": "name"},
        headers={"Accept": "application/fhir+json"},
        timeout=15,
    )
    resp.raise_for_status()
    bundle = resp.json()
    patients = []
    for entry in bundle.get("entry", []):
        res = entry.get("resource", {})
        patients.append({"id": res.get("id"), "name": _human_name(res)})
    patients.sort(key=lambda p: p["name"].lower())
    return patients


def _human_name(patient: dict) -> str:
    names = patient.get("name") or []
    if not names:
        return f"(unnamed {patient.get('id', '?')})"
    n = names[0]
    if n.get("text"):
        return n["text"]
    given = " ".join(n.get("given", []) or [])
    family = n.get("family", "")
    full = f"{given} {family}".strip()
    return full or f"(unnamed {patient.get('id', '?')})"


def get_patient_timeline(patient_id: str) -> list[dict]:
    """Return simplified Device entries for a patient, newest first."""
    devices = _client().get_patient_devices(patient_id)
    entries = [_simplify_device(d) for d in devices]
    entries.sort(key=lambda e: e["last_updated"] or "", reverse=True)
    return entries


def _simplify_device(device: dict) -> dict:
    names = device.get("deviceName") or []
    name = names[0].get("name") if names else None
    dtype = device.get("type", {})
    type_text = dtype.get("text") if isinstance(dtype, dict) else None
    udi = (device.get("udiCarrier") or [{}])[0]
    profiles = (device.get("meta") or {}).get("profile") or []
    return {
        "id": device.get("id"),
        "name": name or type_text or "Device",
        "type": type_text,
        "manufacturer": device.get("manufacturer"),
        "model": device.get("modelNumber"),
        "device_identifier": udi.get("deviceIdentifier"),
        "expiration_date": device.get("expirationDate"),
        "status": device.get("status"),
        "last_updated": (device.get("meta") or {}).get("lastUpdated"),
        "us_core": US_CORE_IMPLANTABLE_DEVICE in profiles,
        "recall_flag": False,  # placeholder until Phase 5 (CDS Hooks recall surveillance)
        "fhir_url": f"{PUBLIC_FHIR_BASE_URL}/Device/{device.get('id')}",
    }
