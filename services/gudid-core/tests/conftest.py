"""Shared fixtures for the gudid-core protocol-layer tests."""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "fhir-bridge"))

import protocol_db  # noqa: E402
import protocol_seed  # noqa: E402
import device_class_resolver  # noqa: E402


@pytest.fixture
def seeded_db(tmp_path, monkeypatch):
    """A freshly seeded protocol DB, installed as the module default."""
    db_path = tmp_path / "protocols.db"
    monkeypatch.setattr(protocol_db, "DB_PATH", db_path)
    device_class_resolver.clear_cache()
    protocol_seed.seed_protocols(db_path)
    yield db_path
    device_class_resolver.clear_cache()


# Fixtures shaped like gudid_service.extract_device_info() output.

PACEMAKER_RECORD = {
    "id": "00643169634589",  # real GUDID DI: Medtronic Azure XT DR MRI SureScan
    "manufacturer": "Medtronic, Inc.",
    "brand_name": "Azure XT DR MRI SureScan",
    "model": "W1DR01",
    "description": "Dual chamber pacemaker",
    "type": "Implantable cardiac pacemaker, dual-chamber",
    "gmdn": [{"code": "35105", "name": "Implantable cardiac pacemaker, dual-chamber"}],
    "fda_product_codes": [{"code": "DXY", "name": "Pacemaker, pulse-generator, implantable"}],
    "mri_safety": "MR Conditional",
    "contacts": [{"phone": "+1-800-000-0000"}],
}

ICD_RECORD = {
    "manufacturer": "Boston Scientific",
    "brand_name": "Some Generator",
    "type": "Implantable cardioverter defibrillator",
    "gmdn": [{"code": "00000", "name": "Implantable cardioverter defibrillator"}],
    "fda_product_codes": [],
}

DBS_RECORD = {
    "manufacturer": "Boston Scientific",
    "brand_name": "Vercise Genus P16",
    "type": "Deep brain stimulation system implantable pulse generator",
    "gmdn": [{"code": "60751", "name": "Deep brain stimulation system implantable pulse generator"}],
}

TANDEM_RECORD = {
    "manufacturer": "Tandem Diabetes Care, Inc.",
    "brand_name": "t:slim X2 Insulin Pump with Control-IQ Technology",
    "type": "Insulin infusion pump, ambulatory",
    "gmdn": [{"code": "11111", "name": "Insulin infusion pump, ambulatory"}],
}

PLAIN_PUMP_RECORD = {
    "manufacturer": "SOOIL Development",
    "brand_name": "Dana Diabecare RS",
    "type": "Insulin infusion pump, ambulatory",
    "gmdn": [{"code": "11111", "name": "Insulin infusion pump, ambulatory"}],
}

HIP_RECORD = {
    "manufacturer": "Zimmer Biomet",
    "brand_name": "Taperloc Complete",
    "type": "Hip joint femoral stem prosthesis",
    "gmdn": [{"code": "46763", "name": "Hip joint femoral stem prosthesis"}],
}

# FHIR-lite shape from scan_to_chart._simplify_device (no fda_product_codes).
FHIR_LITE_PACEMAKER = {
    "name": "Azure XT DR MRI SureScan",
    "type": "Implantable cardiac pacemaker, dual-chamber",
    "gmdn_code": "35105",
    "manufacturer": "Medtronic, Inc.",
    "model": "W1DR01",
}
