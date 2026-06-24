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
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

import requests

from gudid_service import parse_udi, get_device_from_gudid
from gudid_to_uscore_device import map_to_device, US_CORE_IMPLANTABLE_DEVICE
from hapi_client import HapiClient, FhirError
import implant_sites
import protocol_db
import protocol_service
import ifu_pipeline
from device_class_resolver import resolve_device_class

DEVICE_SAFETY_SYSTEM = "https://periop-udi.local/fhir/CodeSystem/device-safety"

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


def _ifu_already_attempted(manufacturer: str, brand: str) -> bool:
    """True if we already have a non-pending IFU record for this manufacturer+brand."""
    try:
        protocol_db.init_db()
        records = protocol_db.list_ifu_records()
        mfr = (manufacturer or "").lower()
        br = (brand or "").lower()
        done_statuses = {"extracted", "verified", "conflict", "no_facts"}
        for r in records:
            if (
                (r.get("manufacturer") or "").lower() == mfr
                and (r.get("brand") or "").lower() == br
                and r.get("status") in done_statuses
            ):
                return True
    except Exception as exc:
        print(f"[ifu-pipeline] could not check existing records: {exc}")
    return False


def _run_ifu_background(di: Optional[str], manufacturer: str, brand: str, model: str) -> None:
    """Target for the background IFU pipeline thread."""
    try:
        result = ifu_pipeline.run_pipeline(
            di=di,
            manufacturer=manufacturer,
            brand=brand,
            model=model,
            verbose=False,
        )
        print(f"[ifu-pipeline] {manufacturer} / {brand}: {result.get('summary', 'done')}")
    except Exception as exc:
        print(f"[ifu-pipeline] background run failed for {manufacturer}/{brand}: {exc}")


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
    lead_config: Optional[str] = None,
    pocket_side: Optional[str] = None,
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

        # Perioperative protocol enrichment is advisory — it must never block
        # documentation of the device.
        protocol = None
        protocol_error = None
        try:
            protocol = protocol_service.build_protocol_block(record)
        except Exception as exc:  # noqa: BLE001
            protocol_error = f"{type(exc).__name__}: {exc}"
            print(f"[scan-to-chart] protocol enrichment failed: {protocol_error}")

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
        _apply_institutional_mri_safety(device, protocol)

        # Clinician-specified implant location (cardiac rhythm devices only).
        # Advisory: a bad location must never block documentation.
        implant = None
        implant_site_warning = None
        if lead_config and protocol and protocol.get("module") == "cardiac_rhythm":
            try:
                ext = implant_sites.build_implant_extension(
                    protocol["device_class"], lead_config, pocket_side
                )
                implant_sites.upsert_implant_extension(device, ext)
                implant = implant_sites.extract_implant(device)
            except ValueError as exc:
                implant_site_warning = str(exc)
        elif lead_config:
            implant_site_warning = (
                "Implant location ignored: device is not a covered cardiac rhythm device"
            )

        client = _client()
        try:
            device_id = client.create_device(device)
        except FhirError:
            # If HAPI rejected the resource and we added the implant extension,
            # retry once without it so documentation still succeeds.
            if implant is None:
                raise
            remaining = [
                e for e in device.get("extension", [])
                if e.get("url") != implant_sites.IMPLANT_SITE_EXTENSION_URL
            ]
            if remaining:
                device["extension"] = remaining
            else:
                device.pop("extension", None)
            device_id = client.create_device(device)
            implant = None
            implant_site_warning = (
                "FHIR server rejected the implant-site extension; "
                "device documented without it"
            )

        if procedure_id:
            client.link_to_procedure(device_id, procedure_id)

        success = True

        # Kick off IFU pipeline in the background — finds the manual PDF via
        # GUDID labeling URLs or Google Custom Search, extracts magnet/MRI facts,
        # and stores them in brand_facts for the protocol layer to serve.
        # Only fires for protocol-covered device classes; skips if we already
        # have a completed record for this brand so we don't burn API quota.
        manufacturer = record.get("manufacturer") or ""
        brand_name = record.get("brand_name") or ""
        model_number = record.get("model") or record.get("version_model_number") or ""

        # Check for existing IFU record first so the UI can show current status
        existing_ifu_status = None
        try:
            mfr_l  = manufacturer.lower()
            brand_l = brand_name.lower()
            for r in protocol_db.list_ifu_records():
                if (r.get("manufacturer") or "").lower() == mfr_l and \
                   (r.get("brand") or "").lower() == brand_l:
                    existing_ifu_status = r.get("status")
                    break
        except Exception:
            pass

        if protocol and not _ifu_already_attempted(manufacturer, brand_name):
            t = threading.Thread(
                target=_run_ifu_background,
                args=(di, manufacturer, brand_name, model_number),
                daemon=True,
            )
            t.start()
            ifu_status = "started"
        elif existing_ifu_status:
            # Already have a record — surface its status so the UI shows the
            # right card (success/conflict/no_facts) instead of the manual form
            ifu_status = existing_ifu_status
        else:
            ifu_status = "skipped"

        result = {
            "success": True,
            "device_id": device_id,
            "device_identifier": di,
            "patient_id": str(patient_id).strip(),
            "fhir_url": f"{PUBLIC_FHIR_BASE_URL}/Device/{device_id}",
            "brand_name": brand_name,
            "manufacturer": manufacturer,
            "type": record.get("type"),
            "profile": US_CORE_IMPLANTABLE_DEVICE,
            "protocol": protocol,
            "implant": implant,
            "ifu_pipeline": ifu_status,
        }
        if protocol_error:
            result["protocol_error"] = protocol_error
        if implant_site_warning:
            result["implant_site_warning"] = implant_site_warning
        return result
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


def _apply_institutional_mri_safety(device: dict, protocol: Optional[dict]) -> None:
    """
    When an institutional MRI override applies, record it on the FHIR Device as
    an extra Device.safety coding (local code system). The fhir-bridge mapper
    stays GUDID-pure; this institutional annotation belongs to the orchestrator.
    """
    if not protocol:
        return
    mri = (protocol.get("facts") or {}).get("mri") or {}
    if mri.get("source") != "institution_override":
        return
    device.setdefault("safety", []).append({
        "coding": [{
            "system": DEVICE_SAFETY_SYSTEM,
            "code": "mri-institutional",
            "display": "MRI: institutional EP list — see PeriopUDI protocol",
        }],
        "text": "MRI: institutional EP list — see PeriopUDI protocol",
    })


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
    """Return patient demographics for the picker table, sorted by name."""
    resp = requests.get(
        f"{FHIR_BASE_URL}/Patient",
        params={"_count": limit, "_elements": "name,gender,birthDate,identifier"},
        headers={"Accept": "application/fhir+json"},
        timeout=20,
    )
    resp.raise_for_status()
    bundle = resp.json()
    patients = [_summarize_patient(e.get("resource", {})) for e in bundle.get("entry", [])]
    patients.sort(key=lambda p: p["name"].lower())
    return patients


def _summarize_patient(p: dict) -> dict:
    """Build {id, name, gender, birth_date, age, mrn} from a Patient resource."""
    mrn = None
    ids = p.get("identifier", []) or []
    for idf in ids:
        coding = ((idf.get("type") or {}).get("coding") or [{}])[0]
        if coding.get("code") == "MR" and idf.get("value"):
            mrn = idf["value"]
            break
    if mrn is None and ids:
        mrn = ids[0].get("value")
    return {
        "id": p.get("id"),
        "name": _human_name(p),
        "gender": p.get("gender"),
        "birth_date": p.get("birthDate"),
        "age": _age_from(p.get("birthDate")),
        "mrn": mrn,
    }


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

    return _summarize_patient(p)


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


def set_implant_site(
    device_id: str, lead_config: str, pocket_side: Optional[str] = None
) -> dict:
    """
    Set or update the clinician-confirmed implant location on an already
    documented Device (for devices documented before location capture, or
    Synthea-seeded charts). Validates the location against the device's
    resolved protocol class before writing.
    """
    try:
        client = _client()
        device = client.get_device(device_id)

        resolved = resolve_device_class(_fhir_lite(device))
        if not resolved or resolved.module != "cardiac_rhythm":
            return {
                "success": False,
                "error": "Device is not a covered cardiac rhythm device",
            }

        ext = implant_sites.build_implant_extension(
            resolved.class_key, lead_config, pocket_side
        )
        implant_sites.upsert_implant_extension(device, ext)
        updated = client.update_device(device)
        return {"success": True, "implant": implant_sites.extract_implant(updated)}
    except ValueError as exc:
        return {"success": False, "error": str(exc)}
    except FhirError as exc:
        return {"success": False, "error": str(exc)}
    except Exception as exc:  # noqa: BLE001 - surface any failure to the UI
        return {"success": False, "error": f"{type(exc).__name__}: {exc}"}


def _fhir_lite(device: dict) -> dict:
    """FHIR Device -> minimal dict for the device-class resolver."""
    names = device.get("deviceName") or []
    name = names[0].get("name") if names else None
    dtype = device.get("type", {}) if isinstance(device.get("type"), dict) else {}
    gmdn_code = None
    for c in dtype.get("coding") or []:
        if c.get("code"):
            gmdn_code = c["code"]
            break
    return {
        "name": name,
        "type": dtype.get("text"),
        "gmdn_code": gmdn_code,
        "manufacturer": device.get("manufacturer"),
        "model": device.get("modelNumber"),
    }


def delete_device(device_id: str) -> bool:
    """Delete a Device from HAPI. Returns True on success."""
    try:
        resp = requests.delete(
            f"{FHIR_BASE_URL}/Device/{device_id}",
            headers={"Accept": "application/fhir+json"},
            timeout=15,
        )
        return resp.status_code < 300
    except Exception as exc:  # noqa: BLE001
        print(f"[scan-to-chart] delete failed for Device/{device_id}: {exc}")
        return False


def get_recent_devices(limit: int = 8) -> list[dict]:
    """Recently documented US Core devices across all patients, newest first."""
    resp = requests.get(
        f"{FHIR_BASE_URL}/Device",
        params={"_count": 40, "_sort": "-_lastUpdated"},
        headers={"Accept": "application/fhir+json"},
        timeout=15,
    )
    resp.raise_for_status()
    bundle = resp.json()
    out = []
    for entry in bundle.get("entry", []):
        device = entry.get("resource", {})
        profiles = (device.get("meta") or {}).get("profile") or []
        if US_CORE_IMPLANTABLE_DEVICE not in profiles:
            continue  # surface the devices documented through PeriopUDI
        entry_data = _simplify_device(device)
        ref = (device.get("patient") or {}).get("reference") or ""
        entry_data["patient_id"] = ref.split("/")[-1] if ref else None
        out.append(entry_data)
        if len(out) >= limit:
            break
    return out


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


_CATEGORY_RULES = [
    ("cardiac", ("stent", "coronary", "cardiac", "valve", "pacemaker", "defibrillator",
                 "icd", "heart", "aortic", "mitral")),
    ("diabetes", ("insulin", "glucose", "cgm")),
    ("neuro", ("neuro", "deep brain", "spinal cord stim", "stimulator", "pulse generator",
               "shunt")),
    ("ortho", ("hip", "knee", "joint", "femoral", "spine", "spinal", "bone", "ortho",
               "prosthesis", "screw", "plate")),
    ("vascular", ("graft", "catheter", "vascular", "filter", "balloon")),
    ("ophthalmic", ("lens", "intraocular", "ophthalmic", "retinal")),
]


def _categorize(*texts: Optional[str]) -> str:
    blob = " ".join(t for t in texts if t).lower()
    for category, keywords in _CATEGORY_RULES:
        if any(k in blob for k in keywords):
            return category
    return "general"


def _simplify_device(device: dict) -> dict:
    names = device.get("deviceName") or []
    name = names[0].get("name") if names else None
    dtype = device.get("type", {}) if isinstance(device.get("type"), dict) else {}
    type_text = dtype.get("text")
    gmdn_code = None
    for c in dtype.get("coding") or []:
        if c.get("code"):
            gmdn_code = c["code"]
            break
    udi = (device.get("udiCarrier") or [{}])[0]
    profiles = (device.get("meta") or {}).get("profile") or []
    safety = [
        {"code": (c.get("coding") or [{}])[0].get("code"), "display": c.get("text") or
         ((c.get("coding") or [{}])[0].get("display"))}
        for c in (device.get("safety") or [])
    ]
    # Protocol-coverage hint from FHIR-derived fields only (no GUDID call) —
    # the full protocol block lazy-loads via /api/protocol/by-di/ on expand.
    protocol_class = None
    protocol_module = None
    try:
        resolved = resolve_device_class(_fhir_lite(device))
        if resolved:
            protocol_class = resolved.class_key
            protocol_module = resolved.module
    except Exception as exc:  # noqa: BLE001 - advisory only
        print(f"[scan-to-chart] protocol class hint failed: {exc}")
    return {
        "id": device.get("id"),
        "name": name or type_text or "Device",
        "type": type_text,
        "gmdn_code": gmdn_code,
        "category": _categorize(name, type_text),
        "protocol_class": protocol_class,
        "protocol_module": protocol_module,
        "protocol_available": protocol_class is not None,
        "implant": implant_sites.extract_implant(device),
        "manufacturer": device.get("manufacturer"),
        "model": device.get("modelNumber"),
        "device_identifier": udi.get("deviceIdentifier"),
        "expiration_date": device.get("expirationDate"),
        "manufacture_date": device.get("manufactureDate"),
        "status": device.get("status"),
        "safety": safety,
        "last_updated": (device.get("meta") or {}).get("lastUpdated"),
        "us_core": US_CORE_IMPLANTABLE_DEVICE in profiles,
        "recall_flag": False,  # set True by get_patient_chart when a recall matches
        "recall": None,
        "fhir_url": f"{PUBLIC_FHIR_BASE_URL}/Device/{device.get('id')}",
    }
