"""
Resolve a device record to a perioperative protocol device class.

Works on the normalized GUDID dict from gudid_service.extract_device_info()
AND on a "FHIR-lite" dict built from a stored Device resource (which has no
fda_product_codes) — every input key is optional.

Resolution precedence (first hit wins):
    1. brand_model_rules     — manufacturer/brand substring match (the only way
                               to detect closed-loop AID systems)
    2. fda_product_code      — exact FDA product code match
    3. gmdn_code             — exact GMDN PT code match
    4. gmdn_name_keyword     — substring match on GMDN PT name / type text
    5. type_keyword /
       brand_keyword         — substring fallback on the full text blob

If steps 2-5 resolve to insulin_pump or cgm, the brand/model layer runs once
more to upgrade the result to closed_loop (e.g. a Tandem pump whose GMDN says
"insulin infusion pump" but whose brand says Control-IQ).
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

import protocol_db

_CONFIDENCE = {
    "brand_model": "high",
    "fda_product_code": "high",
    "gmdn_code": "high",
    "gmdn_name_keyword": "medium",
    "type_keyword": "low",
    "brand_keyword": "low",
}


@dataclass
class ResolvedClass:
    class_key: str
    display_name: str
    module: str
    method: str
    matched: str
    confidence: str


# Rules are static between seed versions; cache per DB path.
_cache: dict[str, dict] = {}


def _rules(db_path: Optional[Path] = None) -> dict:
    key = str(db_path or protocol_db.DB_PATH)
    if key not in _cache:
        conn = protocol_db.get_conn(db_path)
        try:
            _cache[key] = {
                "classes": protocol_db.get_device_classes(conn),
                "resolution": protocol_db.get_resolution_rules(conn),
                "brand_model": protocol_db.get_brand_model_rules(conn),
            }
        finally:
            conn.close()
    return _cache[key]


def clear_cache() -> None:
    _cache.clear()


def _text_blob(record: dict) -> str:
    parts = [
        record.get("brand_name"),
        record.get("name"),
        record.get("model"),
        record.get("description"),
        record.get("type"),
    ]
    for g in record.get("gmdn") or []:
        parts.append(g.get("name"))
    return " ".join(p for p in parts if p).lower()


def _match_brand_model(record: dict, rules: list[dict]) -> Optional[dict]:
    manufacturer = (record.get("manufacturer") or "").lower()
    blob = _text_blob(record)
    for rule in rules:
        mfr_pat = (rule.get("manufacturer_pattern") or "").lower()
        brand_pat = (rule.get("brand_pattern") or "").lower()
        if mfr_pat and mfr_pat not in manufacturer:
            continue
        if brand_pat and brand_pat not in blob:
            continue
        if not mfr_pat and not brand_pat:
            continue
        return rule
    return None


def resolve_device_class(
    record: dict, db_path: Optional[Path] = None
) -> Optional[ResolvedClass]:
    """Return the protocol class for a device record, or None if uncovered."""
    if not record:
        return None
    try:
        rules = _rules(db_path)
    except sqlite3.Error:
        return None
    classes = rules["classes"]
    if not classes:
        return None

    def build(class_key: str, method: str, matched: str) -> Optional[ResolvedClass]:
        cls = classes.get(class_key)
        if not cls:
            return None
        return ResolvedClass(
            class_key=class_key,
            display_name=cls["display_name"],
            module=cls["module"],
            method=method,
            matched=matched,
            confidence=_CONFIDENCE.get(method, "low"),
        )

    # 1. Brand/model rules.
    bm = _match_brand_model(record, rules["brand_model"])
    if bm:
        hit = build(bm["resolves_class"], "brand_model", bm.get("brand_pattern") or
                    bm.get("manufacturer_pattern") or "")
        if hit:
            return hit

    by_type: dict[str, list[dict]] = {}
    for r in rules["resolution"]:
        by_type.setdefault(r["rule_type"], []).append(r)

    # 2. FDA product codes (absent in the FHIR-lite path).
    codes = {
        (c.get("code") or "").upper()
        for c in record.get("fda_product_codes") or []
        if c.get("code")
    }
    for rule in by_type.get("fda_product_code", []):
        if rule["value"].upper() in codes:
            hit = build(rule["class_key"], "fda_product_code", rule["value"])
            if hit:
                return hit

    # 3. GMDN PT codes.
    gmdn_codes = {str(g.get("code")) for g in record.get("gmdn") or [] if g.get("code")}
    if record.get("gmdn_code"):
        gmdn_codes.add(str(record["gmdn_code"]))
    for rule in by_type.get("gmdn_code", []):
        if str(rule["value"]) in gmdn_codes:
            hit = build(rule["class_key"], "gmdn_code", rule["value"])
            if hit:
                return hit

    # 4. GMDN-name / type keywords.
    type_blob = " ".join(
        [record.get("type") or ""] + [g.get("name") or "" for g in record.get("gmdn") or []]
    ).lower()
    for rule in by_type.get("gmdn_name_keyword", []):
        if rule["value"].lower() in type_blob:
            hit = _refine(build(rule["class_key"], "gmdn_name_keyword", rule["value"]),
                          record, rules, build)
            if hit:
                return hit

    # 5. Keyword fallback on everything.
    blob = _text_blob(record)
    for rule_type in ("type_keyword", "brand_keyword"):
        for rule in by_type.get(rule_type, []):
            if rule["value"].lower() in blob:
                hit = _refine(build(rule["class_key"], rule_type, rule["value"]),
                              record, rules, build)
                if hit:
                    return hit

    return None


def _refine(hit, record: dict, rules: dict, build) -> Optional[ResolvedClass]:
    """Upgrade pump/CGM keyword hits to closed_loop when a brand rule matches."""
    if hit and hit.class_key in ("insulin_pump", "cgm"):
        bm = _match_brand_model(record, rules["brand_model"])
        if bm and bm["resolves_class"] == "closed_loop":
            upgraded = build("closed_loop", "brand_model",
                             bm.get("brand_pattern") or bm.get("manufacturer_pattern") or "")
            if upgraded:
                return upgraded
    return hit
