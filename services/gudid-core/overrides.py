"""
Institutional override layer.

Institution-specific annotations sit on top of GUDID data and the protocol
knowledge base — most importantly for MRI compatibility, where internal EP
device lists can supersede manufacturer labeling. Overrides live in an
admin-editable JSON file (data/institution_overrides.json, volume-mounted so
it can be edited on the host without a rebuild); there is deliberately no
write UI.

A malformed or missing file degrades to "no overrides" — it must never break
the scan workflow. Parse errors are kept for display on the admin page.
"""

from __future__ import annotations

import json
import os
import threading
from pathlib import Path
from typing import Optional

OVERRIDES_PATH = Path(os.environ.get("OVERRIDES_PATH", "data/institution_overrides.json"))

# Match-type specificity: lower sorts first = more specific = wins per field.
_SPECIFICITY = {"udi_di": 0, "brand": 1, "gmdn_code": 2, "device_class": 3}

_lock = threading.Lock()
_cache: dict = {"mtime": None, "data": None, "errors": []}


def _validate(raw: dict) -> tuple[list[dict], list[str]]:
    errors: list[str] = []
    valid: list[dict] = []
    for i, ovr in enumerate(raw.get("overrides") or []):
        label = ovr.get("id") or f"overrides[{i}]"
        match = ovr.get("match") or {}
        if "udi_di" in match:
            match_type = "udi_di"
        elif "manufacturer" in match or "brand" in match:
            match_type = "brand"
        elif "gmdn_code" in match:
            match_type = "gmdn_code"
        elif "device_class" in match:
            match_type = "device_class"
        else:
            errors.append(f"{label}: no recognized match criterion "
                          f"(udi_di | manufacturer/brand | gmdn_code | device_class)")
            continue
        if not isinstance(ovr.get("fields"), dict) or not ovr["fields"]:
            errors.append(f"{label}: 'fields' must be a non-empty object")
            continue
        valid.append({**ovr, "_match_type": match_type})
    return valid, errors


def _load(path: Optional[Path] = None) -> dict:
    p = Path(path or OVERRIDES_PATH)
    try:
        mtime = p.stat().st_mtime
    except OSError:
        return {"institution": None, "overrides": [], "errors": []}

    with _lock:
        if _cache["mtime"] == (str(p), mtime) and _cache["data"] is not None:
            return _cache["data"]
        try:
            raw = json.loads(p.read_text())
            valid, errors = _validate(raw)
            data = {
                "institution": raw.get("institution"),
                "overrides": valid,
                "errors": errors,
            }
        except (json.JSONDecodeError, OSError) as exc:
            print(f"[overrides] failed to load {p}: {exc}")
            data = {"institution": None, "overrides": [],
                    "errors": [f"{p.name}: {exc}"]}
        _cache["mtime"] = (str(p), mtime)
        _cache["data"] = data
        return data


def load_overrides(path: Optional[Path] = None) -> dict:
    """{'institution', 'overrides', 'errors'} — never raises."""
    return _load(path)


def list_overrides(path: Optional[Path] = None) -> list[dict]:
    """All valid overrides, for the admin page."""
    return [
        {k: v for k, v in o.items() if not k.startswith("_")}
        for o in _load(path)["overrides"]
    ]


def find_overrides(
    record: dict, class_key: Optional[str], path: Optional[Path] = None
) -> list[dict]:
    """
    Overrides matching this device record, ordered most-specific-first
    (udi_di > manufacturer+brand > gmdn_code > device_class). The caller
    applies them per fact_key with the first (most specific) match winning.
    """
    di = (record.get("id") or record.get("device_identifier") or "").strip()
    manufacturer = (record.get("manufacturer") or "").lower()
    brand_blob = " ".join(
        str(record.get(k) or "") for k in ("brand_name", "name", "model", "description")
    ).lower()
    gmdn_codes = {str(g.get("code")) for g in record.get("gmdn") or [] if g.get("code")}
    if record.get("gmdn_code"):
        gmdn_codes.add(str(record["gmdn_code"]))

    matched = []
    for ovr in _load(path)["overrides"]:
        match = ovr["match"]
        mtype = ovr["_match_type"]
        if mtype == "udi_di":
            if str(match["udi_di"]).strip() != di:
                continue
        elif mtype == "brand":
            m = (match.get("manufacturer") or "").lower()
            b = (match.get("brand") or "").lower()
            mdl = (match.get("model") or "").lower()
            if m and m not in manufacturer:
                continue
            if b and b not in brand_blob:
                continue
            if mdl and mdl not in brand_blob:
                continue
        elif mtype == "gmdn_code":
            if str(match["gmdn_code"]) not in gmdn_codes:
                continue
        elif mtype == "device_class":
            if not class_key or match["device_class"] != class_key:
                continue
        matched.append(ovr)

    matched.sort(key=lambda o: _SPECIFICITY[o["_match_type"]])
    return matched
