"""Implant-location data model: options, extension round-trip, validation."""

import pytest

import implant_sites
from implant_sites import (
    IMPLANT_SITE_EXTENSION_URL,
    build_implant_extension,
    extract_implant,
    get_implant_options,
    upsert_implant_extension,
)


def test_options_for_cardiac_classes():
    for class_key in ("pacemaker", "icd", "crt_p", "crt_d", "leadless_pacemaker"):
        opts = get_implant_options(class_key)
        assert opts is not None, class_key
        assert opts["lead_configs"], class_key
        assert opts["default_lead_config"] in {c["code"] for c in opts["lead_configs"]}


def test_options_none_for_non_cardiac():
    assert get_implant_options("dbs") is None
    assert get_implant_options("insulin_pump") is None
    assert get_implant_options(None) is None


def test_pacemaker_default_is_dual_chamber():
    assert get_implant_options("pacemaker")["default_lead_config"] == "ra_rv"


def test_leadless_has_no_pocket():
    opts = get_implant_options("leadless_pacemaker")
    assert opts["has_pocket"] is False
    assert opts["lead_configs"][0]["no_pocket"] is True


def test_build_and_extract_round_trip():
    ext = build_implant_extension("pacemaker", "ra_rv", "left")
    device = {"resourceType": "Device"}
    upsert_implant_extension(device, ext)
    implant = extract_implant(device)
    assert implant == {
        "lead_config": "ra_rv",
        "pocket_side": "left",
        "sites": ["Right atrium", "Right ventricle"],
        "confirmed": True,
    }


def test_extension_carries_snomed_codings():
    ext = build_implant_extension("crt_d", "ra_rv_lv", "left")
    body_sites = [s for s in ext["extension"] if s["url"] == "bodySite"]
    assert len(body_sites) == 3
    coded = [s for s in body_sites
             if (s["valueCodeableConcept"].get("coding") or [{}])[0].get("system")
             == "http://snomed.info/sct"]
    assert len(coded) == 3  # RA, RV, coronary sinus all have candidate codes


def test_uncoded_site_emits_text_only_concept():
    ext = build_implant_extension("icd", "subcutaneous", None)
    body_sites = [s for s in ext["extension"] if s["url"] == "bodySite"]
    assert len(body_sites) == 1
    concept = body_sites[0]["valueCodeableConcept"]
    assert concept["text"]
    assert "coding" not in concept


def test_leadless_extension_omits_pocket():
    ext = build_implant_extension("leadless_pacemaker", "leadless_rv")
    urls = [s["url"] for s in ext["extension"]]
    assert "pocketSide" not in urls


def test_default_pocket_side_applied():
    ext = build_implant_extension("pacemaker", "rv_only")
    side = next(s for s in ext["extension"] if s["url"] == "pocketSide")
    assert side["valueCode"] == "left"


def test_invalid_lead_config_for_class_raises():
    with pytest.raises(ValueError):
        build_implant_extension("pacemaker", "ra_rv_lv")  # CRT config on a pacemaker
    with pytest.raises(ValueError):
        build_implant_extension("leadless_pacemaker", "ra_rv")
    with pytest.raises(ValueError):
        build_implant_extension("pacemaker", "ra_rv", "anterior")


def test_upsert_replaces_existing_extension():
    device = {"resourceType": "Device"}
    upsert_implant_extension(device, build_implant_extension("pacemaker", "ra_rv", "left"))
    upsert_implant_extension(device, build_implant_extension("pacemaker", "rv_only", "right"))
    matching = [e for e in device["extension"] if e["url"] == IMPLANT_SITE_EXTENSION_URL]
    assert len(matching) == 1
    assert extract_implant(device)["lead_config"] == "rv_only"


def test_upsert_preserves_other_extensions():
    device = {"resourceType": "Device", "extension": [{"url": "https://other.example", "valueString": "x"}]}
    upsert_implant_extension(device, build_implant_extension("icd", "rv_only", "left"))
    assert len(device["extension"]) == 2


def test_extract_none_when_absent():
    assert extract_implant({"resourceType": "Device"}) is None
    assert extract_implant({"extension": [{"url": "https://other.example"}]}) is None
