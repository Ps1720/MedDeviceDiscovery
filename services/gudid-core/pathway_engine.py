"""
Perioperative pathway resolution for cardiac implantable electronic devices.

Turns three case parameters — surgical site, cautery modality, pacing dependence
— into one pathway plus the actions that follow from it, and reports which
inputs drove the decision.

Two rules govern the behaviour:

  Unknown is not "No". A missing or unknown answer resolves to the conservative
  branch, and the result says so. A rule engine that silently reads absent input
  as low-risk is worse than no rule engine.

  Every result is auditable. `because` states the inputs that selected the
  pathway, so a clinician can see immediately which answer to correct if the
  recommendation looks wrong.

Rules live in data/pathway_rules.json, not here, so clinicians can review and
diff them without reading Python.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Optional

_RULES_PATH = Path(__file__).parent / "data" / "pathway_rules.json"
_rules_cache: Optional[dict] = None


def load_rules() -> dict:
    global _rules_cache
    if _rules_cache is None:
        try:
            _rules_cache = json.loads(_RULES_PATH.read_text())
        except Exception as exc:  # noqa: BLE001
            print(f"[pathway_engine] rules load error: {exc}")
            _rules_cache = {"inputs": [], "pathways": {}, "matrix": [],
                            "escalated_actions": [], "applies_to_classes": []}
    return _rules_cache


def applies_to(class_key: Optional[str]) -> bool:
    """Whether pathway resolution is defined for this device class."""
    return bool(class_key) and class_key in load_rules().get("applies_to_classes", [])


def inputs_spec() -> list[dict]:
    """The questions to ask, for the UI to render."""
    return load_rules().get("inputs", [])


def _resolve_input(spec: dict, raw: Optional[str]) -> tuple[str, bool]:
    """
    Return (effective_value, was_assumed).

    An unrecognised or unknown answer falls back to the conservative value, and
    is reported as assumed so the caller can surface it.
    """
    valid = {o["value"] for o in spec["options"]}
    if raw in valid and raw not in (spec.get("default"), None):
        return raw, False
    if raw in valid and raw != spec.get("default"):
        return raw, False
    return spec.get("conservative_value", spec.get("default")), True


def resolve(class_key: str, answers: dict[str, str]) -> dict[str, Any]:
    """
    Resolve the perioperative pathway for a device class and a set of answers.

    Returns:
        {
          "applicable":  bool,
          "pathway":     {"key","label","severity","summary"},
          "because":     str,          # why this pathway fired
          "assumptions": [str],        # conservative fallbacks that were applied
          "actions":     [ {...} ],    # ordered, class- and answer-filtered
          "answers":     {...},        # effective values used
          "requires_verification": True
        }
    """
    rules = load_rules()
    if not applies_to(class_key):
        return {"applicable": False, "pathway": None, "because": "",
                "assumptions": [], "actions": [], "answers": {},
                "requires_verification": True}

    effective: dict[str, str] = {}
    assumptions: list[str] = []
    for spec in rules["inputs"]:
        value, assumed = _resolve_input(spec, (answers or {}).get(spec["key"]))
        effective[spec["key"]] = value
        if assumed and spec.get("unknown_note"):
            assumptions.append(spec["unknown_note"])

    site = effective.get("surgical_site")
    cautery = effective.get("cautery")

    pathway_key = "escalated"          # fail conservative if no cell matches
    for cell in rules["matrix"]:
        if cell["site"] == site and cell["cautery"] == cautery:
            pathway_key = cell["pathway"]
            break
    pathway = dict(rules["pathways"].get(pathway_key, {}), key=pathway_key)

    site_txt = "above the umbilicus" if site == "above" else "below the umbilicus"
    cautery_txt = "monopolar cautery is expected" if cautery == "monopolar" \
        else "bipolar cautery only is planned"
    because = f"{pathway.get('label', pathway_key)} pathway because the surgical " \
              f"field is {site_txt} and {cautery_txt}."

    actions: list[dict] = []
    if pathway_key == "escalated":
        for action in rules.get("escalated_actions", []):
            if class_key not in action.get("applies_to_classes", []):
                continue
            when = action.get("when") or {}
            if any(effective.get(k) not in allowed for k, allowed in when.items()):
                continue
            actions.append({k: v for k, v in action.items()
                            if k not in ("applies_to_classes", "when")})

    return {
        "applicable": True,
        "pathway": pathway,
        "because": because,
        "assumptions": assumptions,
        "actions": actions,
        "answers": effective,
        "requires_verification": True,
    }
