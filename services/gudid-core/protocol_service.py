"""
Protocol orchestration: device record -> `protocol` JSON block.

Resolves the device class, gathers class/context facts and checklist items
from the knowledge base, layers in brand/manufacturer-specific facts, applies
institutional overrides, and tags every merged field with its provenance:

    institution_override > brand_fact > class_protocol > gudid

The output block is embedded in scan results (/scan-to-chart, /api/lookup/udi)
and served standalone for the timeline expander (/api/protocol/by-di/<di>).
Failures here must never block device documentation — callers wrap
build_protocol_block in try/except.
"""

from __future__ import annotations

import time
from typing import Optional

import implant_sites
import overrides as overrides_mod
import protocol_db
from device_class_resolver import resolve_device_class

DISCLAIMER = (
    "Decision support only. Verify against the device interrogation, "
    "institutional policy, and the manufacturer representative before acting."
)

DEFAULT_CONTEXT = "surgery"

# Facts whose values can also come straight from the GUDID record.
_GUDID_TIER = {
    "mri": lambda r: r.get("mri_safety") if r.get("mri_safety") not in (None, "", "Unknown") else None,
    "support_phone": lambda r: next(
        (c.get("phone") for c in r.get("contacts") or [] if c.get("phone")), None
    ),
}

# 15-minute TTL cache for GUDID lookups made by the timeline endpoint.
_GUDID_TTL_SECONDS = 15 * 60
_gudid_cache: dict[str, tuple[float, Optional[dict]]] = {}


def get_gudid_record_cached(di: str) -> Optional[dict]:
    """GUDID lookup with a small in-process TTL cache (timeline expander path)."""
    from gudid_service import get_device_from_gudid

    now = time.monotonic()
    hit = _gudid_cache.get(di)
    if hit and now - hit[0] < _GUDID_TTL_SECONDS:
        return hit[1]
    record = get_device_from_gudid(di)
    if record or hit is None:
        _gudid_cache[di] = (now, record)
    return record


def _fact_entry(row: dict, source: str, override_id: Optional[str] = None) -> dict:
    entry = {
        "value": row.get("fact_value") or row.get("value"),
        "detail": row.get("detail"),
        "severity": row.get("severity"),
        "source": source,
        "citation": row.get("citation"),
        "guideline_source": row.get("guideline_source"),
        "requires_verification": bool(row.get("requires_verification", source != "gudid")),
    }
    if override_id:
        entry["override_id"] = override_id
    return entry


def build_protocol_block(record: dict, context: str = DEFAULT_CONTEXT) -> Optional[dict]:
    """
    Build the protocol block for a normalized GUDID record (or FHIR-lite dict).
    Returns None when the device class is not covered by the knowledge base.
    """
    if context not in protocol_db.CONTEXTS:
        context = DEFAULT_CONTEXT

    resolved = resolve_device_class(record)
    if not resolved:
        return None

    class_key = resolved.class_key
    facts: dict[str, dict] = {}

    # Tier 4 (lowest): raw GUDID fields.
    for fact_key, getter in _GUDID_TIER.items():
        value = getter(record)
        if value:
            facts[fact_key] = _fact_entry(
                {"fact_value": str(value), "requires_verification": False}, "gudid"
            )

    # Tier 3: class protocol facts (context-specific shadows 'all').
    class_facts = protocol_db.get_facts(class_key, context)
    headline_actions: list[dict] = []
    for fact_key, row in class_facts.items():
        entry = _fact_entry(row, "class_protocol")
        if fact_key == "headline":
            headline_actions.append(entry)
        else:
            facts[fact_key] = entry

    # Tier 2: brand/manufacturer-specific facts.
    brand_blob = " ".join(
        str(record.get(k) or "")
        for k in ("brand_name", "name", "model", "description", "type")
    )
    brand_facts = protocol_db.get_brand_facts(
        record.get("manufacturer") or "", brand_blob, class_key
    )
    for fact_key, row in brand_facts.items():
        facts[fact_key] = _fact_entry(row, "brand_fact")

    # Tier 1 (highest): institutional overrides, most specific first.
    applied: list[dict] = []
    overridden_keys: set[str] = set()
    for ovr in overrides_mod.find_overrides(record, class_key):
        used = False
        for fact_key, field in ovr["fields"].items():
            if fact_key in overridden_keys:
                continue  # a more specific override already claimed this field
            facts[fact_key] = _fact_entry(
                {**field, "requires_verification": False},
                "institution_override",
                override_id=ovr.get("id"),
            )
            overridden_keys.add(fact_key)
            used = True
        if used:
            applied.append({
                "id": ovr.get("id"),
                "annotation": ovr.get("annotation"),
                "author": ovr.get("author"),
                "effective_date": ovr.get("effective_date"),
                "supersedes_manufacturer_labeling":
                    bool(ovr.get("supersedes_manufacturer_labeling")),
            })

    checklist = [
        {
            "position": item["position"],
            "text": item["item_text"],
            "rationale": item.get("rationale"),
            "guideline_source": item.get("guideline_source"),
            "citation": item.get("citation"),
            "requires_verification": bool(item.get("requires_verification", 1)),
        }
        for item in protocol_db.get_checklist(class_key, context)
    ]

    block = {
        "device_class": class_key,
        "class_display": resolved.display_name,
        "module": resolved.module,
        "resolution": {
            "method": resolved.method,
            "matched": resolved.matched,
            "confidence": resolved.confidence,
        },
        "context": context,
        "available_contexts": protocol_db.get_available_contexts(class_key),
        "headline_actions": headline_actions,
        "facts": facts,
        "checklist": checklist,
        "overrides_applied": applied,
        "disclaimer": DISCLAIMER,
    }
    if resolved.module == "cardiac_rhythm":
        block["implant_options"] = implant_sites.get_implant_options(class_key)
    return block


def build_protocol_for_di(di: str, context: str = DEFAULT_CONTEXT) -> Optional[dict]:
    """Timeline-expander path: GUDID lookup (TTL-cached) -> protocol block."""
    record = get_gudid_record_cached(di)
    if not record:
        return None
    return build_protocol_block(record, context)
