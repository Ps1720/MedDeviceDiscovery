"""Institutional override matching, merge precedence, and resilience."""

import json

import overrides as overrides_mod
import protocol_service
from conftest import PACEMAKER_RECORD


def _write(tmp_path, monkeypatch, payload):
    p = tmp_path / "institution_overrides.json"
    p.write_text(json.dumps(payload) if isinstance(payload, dict) else payload)
    monkeypatch.setattr(overrides_mod, "OVERRIDES_PATH", p)
    overrides_mod._cache.update({"mtime": None, "data": None})
    return p


def test_udi_di_override_beats_class_override(tmp_path, monkeypatch, seeded_db):
    _write(tmp_path, monkeypatch, {
        "overrides": [
            {"id": "class-level", "match": {"device_class": "pacemaker"},
             "fields": {"mri": {"value": "class value"}}},
            {"id": "di-level", "match": {"udi_di": PACEMAKER_RECORD["id"]},
             "fields": {"mri": {"value": "di value"}}},
        ]
    })
    block = protocol_service.build_protocol_block(PACEMAKER_RECORD, "mri")
    assert block["facts"]["mri"]["value"] == "di value"
    assert block["facts"]["mri"]["source"] == "institution_override"
    assert block["facts"]["mri"]["override_id"] == "di-level"
    # Only the override that contributed fields is reported as applied.
    assert [o["id"] for o in block["overrides_applied"]] == ["di-level"]


def test_merge_precedence_override_brand_class_gudid(tmp_path, monkeypatch, seeded_db):
    _write(tmp_path, monkeypatch, {"overrides": []})
    block = protocol_service.build_protocol_block(PACEMAKER_RECORD, "surgery")
    # brand_fact (Medtronic CRM line) beats the GUDID contact phone.
    assert block["facts"]["support_phone"]["source"] == "brand_fact"
    # class_protocol provides magnet_behavior.
    assert block["facts"]["magnet_behavior"]["source"] == "class_protocol"
    # GUDID raw provides mri in surgery context (class mri fact is mri-context).
    assert block["facts"]["mri"]["source"] == "gudid"
    assert block["facts"]["mri"]["requires_verification"] is False


def test_every_fact_has_provenance(tmp_path, monkeypatch, seeded_db):
    _write(tmp_path, monkeypatch, {"overrides": []})
    block = protocol_service.build_protocol_block(PACEMAKER_RECORD, "surgery")
    for key, fact in block["facts"].items():
        assert fact.get("source") in {
            "institution_override", "brand_fact", "class_protocol", "gudid"
        }, key


def test_brand_match_is_substring_case_insensitive(tmp_path, monkeypatch, seeded_db):
    _write(tmp_path, monkeypatch, {
        "overrides": [
            {"id": "brand-ovr", "match": {"manufacturer": "medtronic", "brand": "azure"},
             "fields": {"electrocautery": {"value": "institution cautery note"}}},
        ]
    })
    block = protocol_service.build_protocol_block(PACEMAKER_RECORD, "surgery")
    assert block["facts"]["electrocautery"]["value"] == "institution cautery note"


def test_malformed_json_degrades_to_no_overrides(tmp_path, monkeypatch, seeded_db):
    _write(tmp_path, monkeypatch, "{not valid json")
    data = overrides_mod.load_overrides()
    assert data["overrides"] == []
    assert data["errors"]
    # And the protocol block still builds.
    block = protocol_service.build_protocol_block(PACEMAKER_RECORD, "surgery")
    assert block["overrides_applied"] == []


def test_invalid_override_entries_reported_not_fatal(tmp_path, monkeypatch, seeded_db):
    _write(tmp_path, monkeypatch, {
        "overrides": [
            {"id": "no-match"},  # invalid: no match criterion
            {"id": "no-fields", "match": {"device_class": "pacemaker"}},  # invalid
            {"id": "ok", "match": {"device_class": "pacemaker"},
             "fields": {"mri": {"value": "x"}}},
        ]
    })
    data = overrides_mod.load_overrides()
    assert len(data["overrides"]) == 1
    assert len(data["errors"]) == 2


def test_mtime_reload(tmp_path, monkeypatch, seeded_db):
    p = _write(tmp_path, monkeypatch, {"overrides": []})
    assert overrides_mod.list_overrides() == []
    p.write_text(json.dumps({
        "overrides": [{"id": "new", "match": {"device_class": "pacemaker"},
                       "fields": {"mri": {"value": "x"}}}]
    }))
    import os
    os.utime(p, (p.stat().st_atime, p.stat().st_mtime + 5))
    assert [o["id"] for o in overrides_mod.list_overrides()] == ["new"]


def test_missing_file_is_empty(tmp_path, monkeypatch, seeded_db):
    monkeypatch.setattr(overrides_mod, "OVERRIDES_PATH", tmp_path / "nope.json")
    overrides_mod._cache.update({"mtime": None, "data": None})
    assert overrides_mod.load_overrides()["overrides"] == []
