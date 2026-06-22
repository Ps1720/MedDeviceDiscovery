"""Device-class resolution: precedence, closed-loop upgrade, FHIR-lite path."""

from conftest import (
    DBS_RECORD,
    FHIR_LITE_PACEMAKER,
    HIP_RECORD,
    ICD_RECORD,
    PACEMAKER_RECORD,
    PLAIN_PUMP_RECORD,
    TANDEM_RECORD,
)
from device_class_resolver import resolve_device_class


def test_pacemaker_resolves_high_confidence(seeded_db):
    r = resolve_device_class(PACEMAKER_RECORD)
    assert r is not None
    assert r.class_key == "pacemaker"
    assert r.confidence == "high"  # brand rule ("azure") or product code (DXY)
    assert r.module == "cardiac_rhythm"


def test_pacemaker_via_product_code_without_brand(seeded_db):
    record = {**PACEMAKER_RECORD, "brand_name": "Generic PPM", "manufacturer": "Acme"}
    r = resolve_device_class(record)
    assert r.class_key == "pacemaker"
    assert r.method == "fda_product_code"
    assert r.matched == "DXY"


def test_icd_via_gmdn_name_keyword(seeded_db):
    r = resolve_device_class(ICD_RECORD)
    assert r.class_key == "icd"
    assert r.method == "gmdn_name_keyword"
    assert r.confidence == "medium"


def test_dbs_via_brand_rule(seeded_db):
    r = resolve_device_class(DBS_RECORD)
    assert r.class_key == "dbs"


def test_tandem_control_iq_upgrades_to_closed_loop(seeded_db):
    r = resolve_device_class(TANDEM_RECORD)
    assert r.class_key == "closed_loop"
    assert r.method == "brand_model"


def test_plain_insulin_pump_stays_insulin_pump(seeded_db):
    r = resolve_device_class(PLAIN_PUMP_RECORD)
    assert r.class_key == "insulin_pump"


def test_uncovered_device_returns_none(seeded_db):
    assert resolve_device_class(HIP_RECORD) is None


def test_empty_record_returns_none(seeded_db):
    assert resolve_device_class({}) is None
    assert resolve_device_class(None) is None


def test_fhir_lite_record_resolves_via_gmdn(seeded_db):
    """The timeline path has no fda_product_codes — gmdn_code must suffice."""
    r = resolve_device_class(FHIR_LITE_PACEMAKER)
    assert r is not None
    assert r.class_key == "pacemaker"


def test_crt_keyword_beats_generic_defibrillator(seeded_db):
    record = {
        "manufacturer": "Acme",
        "brand_name": "Generic CRT",
        "type": "Cardiac resynchronization therapy implantable defibrillator",
        "gmdn": [{"code": "9", "name": "Cardiac resynchronization therapy implantable defibrillator"}],
    }
    r = resolve_device_class(record)
    assert r.class_key == "crt_d"
