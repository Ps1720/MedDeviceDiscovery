"""
Implant-location data model for cardiac rhythm devices.

The implant location is real patient data: the clinician specifies it at
scan time (or later from the chart) and it is stored on the FHIR Device as a
complex extension with SNOMED-coded body sites. Presence of the extension
means clinician-confirmed; absence means the UI renders the TYPICAL placement
for the device type with an explicit "not confirmed" badge. Code must never
write a "typical" extension implicitly.

All SNOMED codes below are candidates flagged VERIFY — confirm against the
SNOMED CT browser before pilot use. Sites without a verified code emit
text-only CodeableConcepts, which is still valid FHIR.

Pure module: no Flask, no network — fully unit-testable.
"""

from __future__ import annotations

from typing import Optional

IMPLANT_SITE_EXTENSION_URL = "https://periop-udi.local/fhir/StructureDefinition/implant-site"
SNOMED = "http://snomed.info/sct"

# SNOMED CT body-site codes — ALL VERIFY before pilot use.
BODY_SITES = {
    "right_atrium": {"code": "73829009", "display": "Right atrial structure",
                     "text": "Right atrium"},  # VERIFY
    "right_ventricle": {"code": "53085002", "display": "Right ventricular structure",
                        "text": "Right ventricle"},  # VERIFY
    "coronary_sinus": {"code": "90219004", "display": "Coronary sinus structure",
                       "text": "Coronary sinus (LV lead)"},  # VERIFY
    "left_ventricle": {"code": "87878005", "display": "Left ventricular structure",
                       "text": "Left ventricle"},  # VERIFY
    "parasternal_subq": {"code": None, "display": None,
                         "text": "Parasternal subcutaneous tissue"},  # VERIFY: find SNOMED code
}

LEAD_CONFIGS = {
    "pacemaker": [
        {"code": "ra_rv", "label": "Dual chamber (RA + RV)", "default": True,
         "sites": ["right_atrium", "right_ventricle"]},
        {"code": "rv_only", "label": "Single chamber (RV)", "default": False,
         "sites": ["right_ventricle"]},
        {"code": "ra_only", "label": "Single chamber (RA)", "default": False,
         "sites": ["right_atrium"]},
    ],
    "crt_p": [
        {"code": "ra_rv_lv", "label": "Biventricular (RA + RV + LV via coronary sinus)",
         "default": True, "sites": ["right_atrium", "right_ventricle", "coronary_sinus"]},
    ],
    "crt_d": [
        {"code": "ra_rv_lv", "label": "Biventricular (RA + RV + LV via coronary sinus)",
         "default": True, "sites": ["right_atrium", "right_ventricle", "coronary_sinus"]},
    ],
    "icd": [
        {"code": "rv_only", "label": "Single chamber (RV coil)", "default": True,
         "sites": ["right_ventricle"]},
        {"code": "ra_rv", "label": "Dual chamber (RA + RV)", "default": False,
         "sites": ["right_atrium", "right_ventricle"]},
        {"code": "subcutaneous", "label": "Subcutaneous (S-ICD)", "default": False,
         "sites": ["parasternal_subq"]},
    ],
    "leadless_pacemaker": [
        {"code": "leadless_rv", "label": "Leadless capsule (RV)", "default": True,
         "sites": ["right_ventricle"], "no_pocket": True},
    ],
}

POCKET_SIDES = [
    {"code": "left", "label": "Left pectoral", "default": True},
    {"code": "right", "label": "Right pectoral", "default": False},
]


def get_implant_options(class_key: Optional[str]) -> Optional[dict]:
    """Selector options for a device class; None for non-cardiac classes."""
    configs = LEAD_CONFIGS.get(class_key or "")
    if not configs:
        return None
    default = next((c["code"] for c in configs if c.get("default")), configs[0]["code"])
    has_pocket = not all(c.get("no_pocket") for c in configs)
    return {
        "lead_configs": [
            {"code": c["code"], "label": c["label"], "default": bool(c.get("default")),
             "no_pocket": bool(c.get("no_pocket"))}
            for c in configs
        ],
        "pocket_sides": POCKET_SIDES,
        "default_lead_config": default,
        "has_pocket": has_pocket,
    }


def _find_config(class_key: str, lead_config: str) -> dict:
    for c in LEAD_CONFIGS.get(class_key, []):
        if c["code"] == lead_config:
            return c
    raise ValueError(
        f"lead_config '{lead_config}' is not valid for device class '{class_key}'"
    )


def _body_site_concept(site_key: str) -> dict:
    site = BODY_SITES[site_key]
    concept: dict = {"text": site["text"]}
    if site.get("code"):
        concept["coding"] = [{
            "system": SNOMED,
            "code": site["code"],
            "display": site["display"],
        }]
    return concept


def build_implant_extension(
    class_key: str, lead_config: str, pocket_side: Optional[str] = None
) -> dict:
    """
    Build the complex implant-site extension for a FHIR Device.
    Raises ValueError for a lead_config/pocket_side invalid for the class.
    """
    config = _find_config(class_key, lead_config)

    sub: list[dict] = [{"url": "leadConfig", "valueCode": lead_config}]
    if not config.get("no_pocket"):
        side = pocket_side or next(p["code"] for p in POCKET_SIDES if p["default"])
        if side not in {p["code"] for p in POCKET_SIDES}:
            raise ValueError(f"pocket_side '{pocket_side}' is not valid")
        sub.append({"url": "pocketSide", "valueCode": side})
    for site_key in config["sites"]:
        sub.append({"url": "bodySite", "valueCodeableConcept": _body_site_concept(site_key)})

    return {"url": IMPLANT_SITE_EXTENSION_URL, "extension": sub}


def upsert_implant_extension(device: dict, extension: dict) -> None:
    """Replace any existing implant-site extension on the Device, else append."""
    extensions = device.setdefault("extension", [])
    for i, ext in enumerate(extensions):
        if ext.get("url") == IMPLANT_SITE_EXTENSION_URL:
            extensions[i] = extension
            return
    extensions.append(extension)


def extract_implant(device: dict) -> Optional[dict]:
    """
    Read the implant-site extension from a FHIR Device resource.
    Returns {lead_config, pocket_side, sites, confirmed: True} or None.
    """
    for ext in device.get("extension") or []:
        if ext.get("url") != IMPLANT_SITE_EXTENSION_URL:
            continue
        lead_config = None
        pocket_side = None
        sites: list[str] = []
        for sub in ext.get("extension") or []:
            if sub.get("url") == "leadConfig":
                lead_config = sub.get("valueCode")
            elif sub.get("url") == "pocketSide":
                pocket_side = sub.get("valueCode")
            elif sub.get("url") == "bodySite":
                concept = sub.get("valueCodeableConcept") or {}
                if concept.get("text"):
                    sites.append(concept["text"])
        if not lead_config:
            return None
        return {
            "lead_config": lead_config,
            "pocket_side": pocket_side,
            "sites": sites,
            "confirmed": True,
        }
    return None
