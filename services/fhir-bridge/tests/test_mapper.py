"""
Tests for the GUDID -> US Core Implantable Device mapper.

Two layers:
  * Pure mapping unit tests (stdlib only) — always run.
  * A live validation test that POSTs each mapped Device to HAPI's $validate
    against US Core v8.0.1 — skipped when `requests` or a running HAPI is absent.

Run from the service dir:   pytest services/fhir-bridge/tests
"""

import os
import sys

import pytest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from gudid_to_uscore_device import (  # noqa: E402
    US_CORE_IMPLANTABLE_DEVICE,
    GMDN_SYSTEM,
    map_to_device,
)

# ---- Five+ representative GUDID records (shape = extract_device_info output) ----
SAMPLE_RECORDS = {
    "drug_eluting_stent": {
        "id": "08717648200274",
        "manufacturer": "Abbott Vascular",
        "brand_name": "XIENCE Alpine",
        "model": "1148355-08",
        "catalog_number": "1148355-08",
        "type": "Coronary artery stent, drug-eluting",
        "gmdn": [{"code": "58513", "name": "Coronary artery stent, drug-eluting"}],
        "expiration_date": "2027-05-31",
        "manufacturing_date": "2024-06-01",
    },
    "pacemaker": {
        "id": "00643169001763",
        "manufacturer": "Medtronic, Inc.",
        "brand_name": "Azure XT DR MRI SureScan",
        "model": "W2DR01",
        "type": "Implantable cardiac pacemaker, dual-chamber",
        "gmdn": [{"code": "35105", "name": "Implantable cardiac pacemaker, dual-chamber"}],
        "serial_number": "PJN123456",
    },
    "hip_implant": {
        "id": "00763000123457",
        "manufacturer": "Zimmer Biomet",
        "brand_name": "Taperloc Complete",
        "model": "TLC-12",
        "type": "Hip joint femoral stem prosthesis, cementless",
        "gmdn": [{"code": "46763", "name": "Hip joint femoral stem prosthesis"}],
        "lot_batch": "LOT-HIP-77",
        "expiration_date": "2030-01",
    },
    "minimal_only_brand": {
        # Record with almost nothing but the DI + brand (no GMDN, no dates).
        "id": "00813132020644",
        "manufacturer": "Unknown",
        "brand_name": "Generic Implant",
        "gmdn": [],
    },
    "neurostimulator": {
        "id": "00763000999991",
        "manufacturer": "Boston Scientific",
        "brand_name": "Vercise Genus",
        "model": "DB-1140",
        "type": "Deep brain stimulation system implantable pulse generator",
        "gmdn": [{"code": "60751", "name": "DBS system implantable pulse generator"}],
        "serial_number": "BSC-77-001",
        "manufacturing_date": "2025-02-15T00:00:00Z",
    },
}


@pytest.mark.parametrize("key", list(SAMPLE_RECORDS))
def test_maps_core_fields(key):
    rec = SAMPLE_RECORDS[key]
    dev = map_to_device(rec, patient_id="1602")

    assert dev["resourceType"] == "Device"
    assert dev["meta"]["profile"] == [US_CORE_IMPLANTABLE_DEVICE]
    assert dev["status"] == "active"
    # udiCarrier.deviceIdentifier anchors on the GUDID DI.
    assert dev["udiCarrier"][0]["deviceIdentifier"] == rec["id"]
    assert dev["udiCarrier"][0]["carrierHRF"]  # always present
    # patient linkage when provided.
    assert dev["patient"] == {"reference": "Patient/1602"}


def test_gmdn_becomes_device_type_coding():
    dev = map_to_device(SAMPLE_RECORDS["drug_eluting_stent"])
    coding = dev["type"]["coding"][0]
    assert coding["system"] == GMDN_SYSTEM
    assert coding["code"] == "58513"


def test_production_identifiers_come_only_from_the_scan():
    """
    Production identifiers exist on the physical package, not in GUDID. A DI-only
    lookup must therefore omit them entirely; only a scanned UDI supplies them.
    """
    dev = map_to_device(SAMPLE_RECORDS["pacemaker"])
    assert "serialNumber" not in dev
    assert "lotNumber" not in dev

    dev2 = map_to_device(
        SAMPLE_RECORDS["pacemaker"], serial_number="OVERRIDE-9", lot_number="L9"
    )
    assert dev2["serialNumber"] == "OVERRIDE-9"
    assert dev2["lotNumber"] == "L9"


def test_gudid_boolean_flags_never_become_identifiers():
    """
    Regression: GUDID returns lotBatch / serialNumber / expirationDate /
    manufacturingDate as BOOLEAN FLAGS ("does this device carry one?"). Reading
    them as values wrote serialNumber="True", lotNumber="False" onto every
    mapped Device — schema-valid, clinically meaningless.
    """
    record = {
        **SAMPLE_RECORDS["pacemaker"],
        "serial_number": True,
        "lot_batch": False,
        "expiration_date": False,
        "manufacturing_date": False,
    }
    dev = map_to_device(record)
    for field in ("serialNumber", "lotNumber", "expirationDate", "manufactureDate"):
        assert dev.get(field) not in ("True", "False", True, False), (
            f"{field} picked up a GUDID boolean flag: {dev.get(field)!r}"
        )


def test_dates_normalized_to_fhir():
    # Dates, like other production identifiers, arrive from the scanned UDI.
    dev = map_to_device(
        SAMPLE_RECORDS["neurostimulator"], manufacture_date="2025-02-15T00:00:00Z"
    )
    # trailing time is trimmed to a valid FHIR date
    assert dev["manufactureDate"] == "2025-02-15"
    dev_partial = map_to_device(SAMPLE_RECORDS["hip_implant"], expiration_date="2030-01")
    assert dev_partial["expirationDate"] == "2030-01"


def test_unknown_manufacturer_and_brand_dropped():
    dev = map_to_device(SAMPLE_RECORDS["minimal_only_brand"])
    assert "manufacturer" not in dev  # "Unknown" is dropped
    # brand "Generic Implant" is kept (not literally "Unknown")
    assert dev["deviceName"][0]["name"] == "Generic Implant"


def test_device_type_always_present():
    # US Core requires Device.type; the mapper falls back to a generic text
    # when GUDID supplies neither a GMDN term nor a type string.
    dev = map_to_device(SAMPLE_RECORDS["minimal_only_brand"])
    assert dev["type"]["text"] == "Implantable device"
    assert "coding" not in dev["type"]


def test_missing_device_identifier_raises():
    with pytest.raises(ValueError):
        map_to_device({"brand_name": "No DI here"})


def test_patient_optional():
    dev = map_to_device(SAMPLE_RECORDS["pacemaker"])
    assert "patient" not in dev


# --------------------------------------------------------------------------
# Live US Core v8.0.1 validation against a running HAPI ($validate).
# --------------------------------------------------------------------------
FHIR_BASE_URL = os.environ.get("FHIR_BASE_URL", "http://localhost:8080/fhir")


def _hapi_reachable() -> bool:
    requests = pytest.importorskip("requests")
    try:
        r = requests.get(f"{FHIR_BASE_URL}/metadata", timeout=5)
        return r.status_code == 200
    except Exception:
        return False


@pytest.mark.parametrize("key", list(SAMPLE_RECORDS))
def test_mapped_device_passes_us_core_validation(key):
    pytest.importorskip("requests")
    if not _hapi_reachable():
        pytest.skip(f"HAPI not reachable at {FHIR_BASE_URL}")

    sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
    from hapi_client import HapiClient

    client = HapiClient(FHIR_BASE_URL)
    device = map_to_device(SAMPLE_RECORDS[key], patient_id="1602")
    outcome = client.validate(device, profile=US_CORE_IMPLANTABLE_DEVICE)
    errors = client.outcome_errors(outcome)
    assert not errors, f"{key} failed US Core validation: {errors}"
