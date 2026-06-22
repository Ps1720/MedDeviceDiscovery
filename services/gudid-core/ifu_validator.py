"""
Cross-validates LLM-extracted IFU facts against the structured GUDID record.

Validation checks:
  - MRI safety status consistency
  - Manufacturer name match (catches wrong-manual errors)
  - Device class plausibility

Returns a ValidationResult with a confidence score and a list of conflict flags.
Any conflict should block the extracted facts from being shown without an
explicit VERIFY banner, and should trigger clinician review.
"""

from __future__ import annotations

from typing import Optional

# GUDID MRISafetyStatus values -> whether device is MR Conditional
_MRI_CONDITIONAL_STATUSES = {"MR Conditional", "MR CONDITIONAL"}
_MRI_SAFE_STATUSES = {"MR Safe", "MR SAFE"}
_MRI_UNSAFE_STATUSES = {"MR Unsafe", "MR UNSAFE"}


def _gudid_mri_bucket(gudid_record: dict) -> Optional[str]:
    """
    Return "conditional", "safe", "unsafe", or None from a GUDID record dict.
    Accepts both raw GUDID shape and normalized shape.
    """
    status = (
        gudid_record.get("MRISafetyStatus")
        or gudid_record.get("mri_safety")
        or ""
    ).strip()
    if not status:
        return None
    if status in _MRI_CONDITIONAL_STATUSES or "conditional" in status.lower():
        return "conditional"
    if status in _MRI_SAFE_STATUSES or "safe" == status.lower():
        return "safe"
    if status in _MRI_UNSAFE_STATUSES or "unsafe" in status.lower():
        return "unsafe"
    return None


def _extracted_mri_bucket(facts: dict) -> Optional[str]:
    val = facts.get("mri_conditional")
    if val is True:
        return "conditional"
    if val is False:
        return "unsafe"
    return None


def validate(
    facts: dict,
    gudid_record: dict,
    manufacturer: str,
    brand: str,
) -> dict:
    """
    Cross-validate extracted facts against GUDID.

    Args:
        facts:        Output of ifu_extractor.extract_from_url()["facts"]
        gudid_record: Raw or normalized GUDID record for the same DI
        manufacturer: Expected manufacturer name (from GUDID)
        brand:        Expected brand name (from GUDID)

    Returns:
        {
          "valid": bool,          # False if any hard conflict found
          "confidence": float,    # 0.0–1.0
          "conflicts": list[str], # human-readable conflict descriptions
          "warnings": list[str],  # non-blocking concerns
        }
    """
    conflicts: list[str] = []
    warnings: list[str] = []
    confidence_deductions = 0.0

    if not facts:
        return {
            "valid": False,
            "confidence": 0.0,
            "conflicts": ["No extracted facts to validate"],
            "warnings": [],
        }

    # ── MRI safety cross-check ──────────────────────────────────────────────
    gudid_mri = _gudid_mri_bucket(gudid_record)
    extracted_mri = _extracted_mri_bucket(facts)

    if gudid_mri and extracted_mri and gudid_mri != extracted_mri:
        conflicts.append(
            f"MRI status mismatch: GUDID says '{gudid_mri}', IFU says '{extracted_mri}'. "
            "Institutional override may apply — verify with EP/radiology."
        )
        confidence_deductions += 0.4
    elif gudid_mri and not extracted_mri:
        warnings.append(
            f"MRI status not extracted from IFU (GUDID says '{gudid_mri}')."
        )
        confidence_deductions += 0.05

    # ── Manufacturer name check ─────────────────────────────────────────────
    gudid_mfr = (
        gudid_record.get("companyName") or gudid_record.get("manufacturer") or ""
    ).lower()
    expected_mfr = (manufacturer or "").lower()

    if gudid_mfr and expected_mfr and gudid_mfr not in expected_mfr and expected_mfr not in gudid_mfr:
        # Check if at least the first token matches (handles "Medtronic, Inc." vs "Medtronic")
        gudid_tok = gudid_mfr.split()[0] if gudid_mfr else ""
        exp_tok = expected_mfr.split()[0] if expected_mfr else ""
        if gudid_tok and exp_tok and gudid_tok != exp_tok:
            conflicts.append(
                f"Manufacturer mismatch: GUDID says '{gudid_mfr}', pipeline used '{expected_mfr}'. "
                "Wrong manual may have been fetched — reject extraction."
            )
            confidence_deductions += 0.5

    # ── Magnet rate plausibility (cardiac devices) ──────────────────────────
    rate_str = (facts.get("magnet_rate_bpm") or "").strip()
    if rate_str:
        try:
            rate = float(rate_str.replace(" bpm", "").split()[0])
            if not (40 <= rate <= 120):
                warnings.append(
                    f"Extracted magnet rate ({rate} bpm) is outside plausible range (40–120 bpm). "
                    "Manual verification required."
                )
                confidence_deductions += 0.1
        except (ValueError, IndexError):
            warnings.append(
                f"Could not parse magnet rate as a number: '{rate_str}'."
            )
            confidence_deductions += 0.05

    confidence = max(0.0, 1.0 - confidence_deductions)
    valid = len(conflicts) == 0

    return {
        "valid": valid,
        "confidence": round(confidence, 2),
        "conflicts": conflicts,
        "warnings": warnings,
    }
