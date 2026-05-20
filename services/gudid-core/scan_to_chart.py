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
# CDS Hooks recall-surveillance service (Phase 5).
CDS_HOOKS_URL = os.environ.get("CDS_HOOKS_URL")
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


def _resolve_di(udi: str) -> tuple[str, Optional[str], Optional[str], dict]:
    """
    Return (device_identifier, issuing_agency, udi_hrf, production_ids) for a
    scanned string.

    A pure-numeric string is treated as a bare Device Identifier (DI) with no
    production identifiers. Anything else is parsed via GUDID, which also yields
    the expiration date, lot, serial, and manufacture date from the UDI's
    production-identifier segments.
    """
    udi = udi.strip()
    if udi.isdigit():
        return udi, None, udi, {}
    parsed = parse_udi(udi)
    if parsed and parsed.get("di"):
        raw = parsed.get("raw") or {}
        pis = {
            "expiration_date": raw.get("expirationDate"),
            "lot_number": raw.get("lotNumber"),
            "serial_number": raw.get("serialNumber"),
            "manufacture_date": raw.get("manufactureDate") or raw.get("manufacturingDate"),
        }
        return parsed["di"], parsed.get("issuing_agency"), udi, pis
    # Fall back to using the raw string as the DI.
    return udi, None, udi, {}


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

        di, issuing_agency, udi_hrf, production_ids = _resolve_di(udi)

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
            serial_number=production_ids.get("serial_number"),
            lot_number=production_ids.get("lot_number"),
            expiration_date=production_ids.get("expiration_date"),
            manufacture_date=production_ids.get("manufacture_date"),
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


def get_patient_summary(patient_id: str) -> dict:
    """Fetch lightweight demographics for the patient header (name, sex, age, DOB, MRN)."""
    summary = {"id": patient_id, "name": f"Patient {patient_id}", "gender": None,
               "birth_date": None, "age": None, "mrn": None}
    try:
        resp = requests.get(
            f"{FHIR_BASE_URL}/Patient/{patient_id}",
            headers={"Accept": "application/fhir+json"},
            timeout=15,
        )
        resp.raise_for_status()
        p = resp.json()
    except Exception as exc:  # noqa: BLE001
        print(f"[scan-to-chart] patient summary unavailable: {exc}")
        return summary

    summary["name"] = _human_name(p)
    summary["gender"] = p.get("gender")
    summary["birth_date"] = p.get("birthDate")
    summary["age"] = _age_from(p.get("birthDate"))
    for idf in p.get("identifier", []) or []:
        coding = ((idf.get("type") or {}).get("coding") or [{}])[0]
        if coding.get("code") == "MR" and idf.get("value"):
            summary["mrn"] = idf["value"]
            break
    else:
        ids = p.get("identifier") or []
        if ids:
            summary["mrn"] = ids[0].get("value")
    return summary


def _age_from(birth_date: Optional[str]) -> Optional[int]:
    if not birth_date:
        return None
    try:
        y, m, d = (birth_date.split("T")[0].split("-") + ["1", "1"])[:3]
        from datetime import date
        b = date(int(y), int(m), int(d))
        today = date.today()
        return today.year - b.year - ((today.month, today.day) < (b.month, b.day))
    except Exception:  # noqa: BLE001
        return None


def get_patient_chart(patient_id: str) -> dict:
    """
    Return the patient's demographics, device timeline, and recall cards from the
    CDS Hooks recall-check service. Each device is annotated with any matching recall.
    """
    patient = get_patient_summary(patient_id)
    devices = _client().get_patient_devices(patient_id)
    cards = get_patient_recall_cards(patient_id)

    # Index recalls by the device's logical id and by UDI-DI for annotation.
    by_device_id: dict[str, dict] = {}
    by_di: dict[str, dict] = {}
    for card in cards:
        if card.get("deviceId"):
            by_device_id[str(card["deviceId"])] = card
        if card.get("deviceIdentifier"):
            by_di[card["deviceIdentifier"]] = card

    entries = []
    for d in devices:
        entry = _simplify_device(d)
        card = by_device_id.get(str(entry["id"])) or by_di.get(entry["device_identifier"])
        if card:
            entry["recall_flag"] = True
            entry["recall"] = {
                "classification": card.get("classification"),
                "reason": card.get("reason"),
                "recall_number": card.get("recallNumber"),
                "indicator": card.get("indicator"),
                "summary": card.get("summary"),
            }
        entries.append(entry)

    entries.sort(key=lambda e: e["last_updated"] or "", reverse=True)
    return {"patient": patient, "devices": entries, "recalls": cards}


def get_patient_timeline(patient_id: str) -> list[dict]:
    """Backward-compatible: just the annotated device entries, newest first."""
    return get_patient_chart(patient_id)["devices"]


def get_patient_recall_cards(patient_id: str) -> list[dict]:
    """Query the CDS Hooks recall-check service for this patient's recall cards."""
    if not CDS_HOOKS_URL:
        return []
    try:
        resp = requests.post(
            f"{CDS_HOOKS_URL}/cds-services/recall-check",
            json={
                "hook": "patient-view",
                "hookInstance": "periopudi-timeline",
                "context": {"patientId": patient_id},
                "fhirServer": FHIR_BASE_URL,
            },
            timeout=15,
        )
        resp.raise_for_status()
        return resp.json().get("cards", [])
    except Exception as exc:  # recall surveillance is advisory; never break the chart
        print(f"[scan-to-chart] recall-check unavailable: {exc}")
        return []


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
        "recall_flag": False,  # set True by get_patient_chart when a recall matches
        "recall": None,
        "fhir_url": f"{PUBLIC_FHIR_BASE_URL}/Device/{device.get('id')}",
    }
