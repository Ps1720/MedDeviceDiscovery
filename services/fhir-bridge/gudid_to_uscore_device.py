"""
GUDID -> US Core v8.0.1 Implantable Device Profile mapper.

Converts the normalized GUDID device dict produced by
``gudid_service.extract_device_info()`` into a FHIR R4 ``Device`` resource that
conforms to the US Core Implantable Device Profile:

    http://hl7.org/fhir/us/core/StructureDefinition/us-core-implantable-device

GUDID is the authoritative source for device metadata (Build.md §2): this mapper
never invents device data, it only reshapes what GUDID returned into FHIR.
"""

from __future__ import annotations

import re
from typing import Any, Optional

US_CORE_IMPLANTABLE_DEVICE = (
    "http://hl7.org/fhir/us/core/StructureDefinition/us-core-implantable-device"
)

# Registered OID for the Global Medical Device Nomenclature code system.
GMDN_SYSTEM = "urn:oid:2.16.840.1.113883.6.257"

# Local code system used to tag Device.safety entries so the UI can render them
# (MRI status, latex, single-use, sterile come from GUDID safety attributes).
SAFETY_SYSTEM = "https://periop-udi.local/fhir/CodeSystem/device-safety"

# FHIR NamingSystem URIs for the common UDI issuing agencies.
_ISSUER_SYSTEMS = {
    "GS1": "http://hl7.org/fhir/NamingSystem/gs1",
    "HIBCC": "http://hl7.org/fhir/NamingSystem/hibcc",
    "ICCBBA": "http://hl7.org/fhir/NamingSystem/iccbba-other",
}

_DATE_RE = re.compile(r"^\d{4}(-\d{2}(-\d{2})?)?")


def _clean(value: Any) -> Optional[str]:
    """Return a non-empty trimmed string, or None."""
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _as_fhir_datetime(value: Any) -> Optional[str]:
    """
    Normalize a GUDID date into a FHIR date/dateTime literal.

    GUDID returns ``YYYY-MM-DD`` (sometimes with a trailing time). We keep the
    leading ``YYYY``/``YYYY-MM``/``YYYY-MM-DD`` portion, which is a valid FHIR
    dateTime; anything that doesn't start with a 4-digit year is dropped.
    """
    text = _clean(value)
    if not text:
        return None
    match = _DATE_RE.match(text)
    return match.group(0) if match else None


def _issuer_system(issuing_agency: Optional[str]) -> Optional[str]:
    if not issuing_agency:
        return None
    return _ISSUER_SYSTEMS.get(issuing_agency.strip().upper())


def map_to_device(
    gudid_record: dict,
    patient_id: Optional[str] = None,
    *,
    udi_hrf: Optional[str] = None,
    serial_number: Optional[str] = None,
    lot_number: Optional[str] = None,
    expiration_date: Optional[str] = None,
    manufacture_date: Optional[str] = None,
    issuing_agency: Optional[str] = None,
) -> dict:
    """
    Map a normalized GUDID record to a US Core Implantable Device resource.

    Args:
        gudid_record: Output of ``gudid_service.extract_device_info()``. Must
            contain at least ``id`` (the primary Device Identifier).
        patient_id: Logical id of the FHIR Patient the device belongs to. When
            provided, ``Device.patient`` references ``Patient/<patient_id>``.
        udi_hrf: Full human-readable UDI (DI + production identifiers) captured
            from a scan. Used for ``udiCarrier.carrierHRF``; falls back to the DI.
        serial_number / lot_number / expiration_date / manufacture_date:
            Production-identifier overrides parsed from a scanned UDI; when
            omitted the corresponding GUDID record values are used.
        issuing_agency: UDI issuing agency ("GS1", "HIBCC", "ICCBBA") for
            ``udiCarrier.issuer``.

    Returns:
        A FHIR R4 ``Device`` resource as a dict.

    Raises:
        ValueError: if the record has no Device Identifier.
    """
    device_id = _clean(gudid_record.get("id"))
    if not device_id:
        raise ValueError("GUDID record is missing a Device Identifier ('id')")

    device: dict = {
        "resourceType": "Device",
        "meta": {"profile": [US_CORE_IMPLANTABLE_DEVICE]},
        "status": "active",
    }

    # ---- UDI carrier (deviceIdentifier is Must Support / the anchor) ----
    udi_carrier: dict = {"deviceIdentifier": device_id}
    issuer = _issuer_system(issuing_agency)
    if issuer:
        udi_carrier["issuer"] = issuer
    carrier_hrf = _clean(udi_hrf) or device_id
    udi_carrier["carrierHRF"] = carrier_hrf
    device["udiCarrier"] = [udi_carrier]

    # ---- Production identifiers ----
    serial = _clean(serial_number) or _clean(gudid_record.get("serial_number"))
    if serial:
        device["serialNumber"] = serial

    lot = _clean(lot_number) or _clean(gudid_record.get("lot_batch"))
    if lot:
        device["lotNumber"] = lot

    expiry = _as_fhir_datetime(expiration_date) or _as_fhir_datetime(
        gudid_record.get("expiration_date")
    )
    if expiry:
        device["expirationDate"] = expiry

    mfg_date = _as_fhir_datetime(manufacture_date) or _as_fhir_datetime(
        gudid_record.get("manufacturing_date")
    )
    if mfg_date:
        device["manufactureDate"] = mfg_date

    # ---- Manufacturer / names / model ----
    manufacturer = _clean(gudid_record.get("manufacturer"))
    if manufacturer and manufacturer.lower() != "unknown":
        device["manufacturer"] = manufacturer

    device_names = []
    brand = _clean(gudid_record.get("brand_name"))
    if brand and brand.lower() != "unknown":
        device_names.append({"name": brand, "type": "user-friendly-name"})
    if device_names:
        device["deviceName"] = device_names

    model = _clean(gudid_record.get("model"))
    if model:
        device["modelNumber"] = model

    distinct = _clean(gudid_record.get("catalog_number"))
    if distinct:
        device["distinctIdentifier"] = distinct

    # ---- Device.type from GMDN (REQUIRED by US Core: min=1) ----
    device["type"] = _device_type(gudid_record)

    # ---- Device.safety (MRI status, latex, single-use, sterile) ----
    safety = _safety(gudid_record)
    if safety:
        device["safety"] = safety

    # ---- Patient linkage (Must Support; references US Core Patient) ----
    pid = _clean(patient_id)
    if pid:
        device["patient"] = {"reference": f"Patient/{pid}"}

    return device


# Fallback Device.type text when GUDID supplies no GMDN term or type string.
# US Core requires Device.type (min=1), so the mapper must always emit one.
_DEFAULT_TYPE_TEXT = "Implantable device"


def _device_type(gudid_record: dict) -> dict:
    """
    Build the (required) CodeableConcept for Device.type from the GUDID GMDN
    term, falling back to the record's type text and finally a generic default.
    """
    gmdn_list = gudid_record.get("gmdn") or []
    coding = None
    for term in gmdn_list:
        code = _clean(term.get("code"))
        name = _clean(term.get("name"))
        if code:
            coding = {"system": GMDN_SYSTEM, "code": code}
            if name:
                coding["display"] = name
            break

    text = _clean(gudid_record.get("type"))

    concept: dict = {}
    if coding:
        concept["coding"] = [coding]
    concept["text"] = text or (coding.get("display") if coding else None) or _DEFAULT_TYPE_TEXT
    return concept


def _safety_concept(code: str, display: str) -> dict:
    return {"coding": [{"system": SAFETY_SYSTEM, "code": code, "display": display}], "text": display}


def _safety(gudid_record: dict) -> list[dict]:
    """Build Device.safety CodeableConcepts from GUDID safety attributes."""
    out: list[dict] = []

    mri = _clean(gudid_record.get("mri_safety"))
    if mri and mri.lower() not in ("unknown", ""):
        out.append(_safety_concept("mri", f"MRI: {mri}"))

    # Latex: GUDID exposes both "contains" and "not made with" flags.
    if _is_true(gudid_record.get("contains_latex")):
        out.append(_safety_concept("latex", "Contains natural rubber latex"))
    elif _is_true(gudid_record.get("no_latex")):
        out.append(_safety_concept("no-latex", "Not made with natural rubber latex"))

    if _is_true(gudid_record.get("single_use")):
        out.append(_safety_concept("single-use", "Single use"))

    if _is_true(gudid_record.get("sterile")):
        out.append(_safety_concept("sterile", "Sterile"))

    return out


def _is_true(value: Any) -> bool:
    """GUDID booleans arrive as bools or 'true'/'false' strings."""
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() == "true"
