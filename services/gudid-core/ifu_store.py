"""
Persists IFU pipeline results into the protocol knowledge base.

Writes to two tables:
  ifu_records  — one row per (device, IFU URL), tracks fetch/extraction/verification history
  brand_facts  — one row per extracted clinical fact, with IFU provenance

All LLM-extracted brand_facts rows carry requires_verification=1 and source='llm'.
They won't be served without a VERIFY banner until a clinician sets verified_at.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Optional

import protocol_db


# Map from LLM extraction keys → brand_facts fact_key values
_FACT_KEY_MAP = {
    "magnet_rate_bpm":                "magnet_rate",
    "magnet_mode":                     "magnet_mode",
    "magnet_response_programmable_off": "magnet_programmable_off",
    "magnet_inhibits_tachy_therapy":   "magnet_inhibits_therapy",
    "mri_conditions_summary":          "mri_conditions",
    "support_phone_24hr":              "support_phone",
    "electrocautery_recommendation":   "electrocautery",
    "em_interference_notes":           "em_interference",
}


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def save_pipeline_result(
    *,
    di: Optional[str],
    manufacturer: str,
    brand: str,
    model: str,
    class_key: Optional[str],
    finder_result: dict,
    extraction_result: dict,
    validation_result: dict,
) -> dict:
    """
    Persist the full pipeline result.

    Args:
        di:                DI from GUDID (may be None for manual-entry runs)
        manufacturer:      e.g. "Medtronic"
        brand:             e.g. "Azure XT"
        model:             e.g. "DR MRI SureScan"
        class_key:         protocol class, e.g. "pacemaker" (may be None)
        finder_result:     output of ifu_finder.find_ifu()
        extraction_result: output of ifu_extractor.extract_from_url()
        validation_result: output of ifu_validator.validate()

    Returns:
        {"ifu_record_id": int, "brand_facts_written": int, "status": str}
    """
    now = _now_iso()
    ifu_url = finder_result.get("url") or extraction_result.get("url") or ""
    facts = extraction_result.get("facts") or {}
    conflicts = validation_result.get("conflicts") or []
    status = "conflict" if conflicts else ("extracted" if facts else "no_facts")

    ifu_record_fields = {
        "di":             di,
        "manufacturer":   manufacturer,
        "brand":          brand,
        "model":          model,
        "ifu_url":        ifu_url,
        "ifu_hash":       extraction_result.get("ifu_hash"),
        "last_fetched":   now,
        "finder_source":  finder_result.get("source"),
        "extraction_raw": json.dumps(facts) if facts else None,
        "extracted_by":   "llm",
        "extracted_at":   now if facts else None,
        "conflict_flags": json.dumps(conflicts) if conflicts else None,
        "status":         status,
    }

    record_id = protocol_db.upsert_ifu_record(ifu_record_fields)

    written = 0
    if facts and validation_result.get("valid", False):
        conn = protocol_db.get_conn()
        try:
            mfr_pat = manufacturer.lower() if manufacturer else None
            brand_pat = brand.lower() if brand else None

            for llm_key, fact_key in _FACT_KEY_MAP.items():
                raw_val = facts.get(llm_key)
                if raw_val is None:
                    continue
                if isinstance(raw_val, bool):
                    fact_value = "yes" if raw_val else "no"
                else:
                    fact_value = str(raw_val).strip()
                if not fact_value:
                    continue

                # Check for existing row from a previous run for this device+fact
                existing = conn.execute(
                    """SELECT id FROM brand_facts
                       WHERE manufacturer_pattern = ?
                         AND brand_pattern = ?
                         AND fact_key = ?
                         AND source = 'llm'""",
                    (mfr_pat, brand_pat, fact_key),
                ).fetchone()

                if existing:
                    conn.execute(
                        """UPDATE brand_facts
                           SET fact_value = ?, extracted_at = ?, ifu_record_id = ?,
                               source_url = ?, requires_verification = 1
                         WHERE id = ?""",
                        (fact_value, now, record_id, ifu_url, existing["id"]),
                    )
                else:
                    conn.execute(
                        """INSERT INTO brand_facts
                           (manufacturer_pattern, brand_pattern, class_key, fact_key,
                            fact_value, citation, requires_verification,
                            source, source_url, extracted_at, ifu_record_id)
                           VALUES (?, ?, ?, ?, ?, ?, 1, 'llm', ?, ?, ?)""",
                        (
                            mfr_pat, brand_pat, class_key, fact_key,
                            fact_value,
                            f"Extracted from IFU: {ifu_url}",
                            ifu_url, now, record_id,
                        ),
                    )
                written += 1
            conn.commit()
        finally:
            conn.close()

    return {
        "ifu_record_id": record_id,
        "brand_facts_written": written,
        "status": status,
    }


def mark_verified(ifu_record_id: int, verified_by: str) -> None:
    """
    Mark an IFU record (and all its brand_facts) as clinician-verified.
    Once verified, requires_verification is cleared so facts serve without VERIFY banner.
    """
    now = _now_iso()
    conn = protocol_db.get_conn()
    try:
        conn.execute(
            "UPDATE ifu_records SET verified_by = ?, verified_at = ?, status = 'verified' WHERE id = ?",
            (verified_by, now, ifu_record_id),
        )
        conn.execute(
            "UPDATE brand_facts SET requires_verification = 0 WHERE ifu_record_id = ?",
            (ifu_record_id,),
        )
        conn.commit()
    finally:
        conn.close()
