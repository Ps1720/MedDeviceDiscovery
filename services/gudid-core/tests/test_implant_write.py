"""set_implant_site: post-hoc location writes against a mocked HAPI client."""

import scan_to_chart
from implant_sites import IMPLANT_SITE_EXTENSION_URL

PACEMAKER_FHIR_DEVICE = {
    "resourceType": "Device",
    "id": "9001",
    "deviceName": [{"name": "Azure XT DR MRI SureScan", "type": "user-friendly-name"}],
    "type": {
        "coding": [{"code": "35105", "display": "Implantable cardiac pacemaker, dual-chamber"}],
        "text": "Implantable cardiac pacemaker, dual-chamber",
    },
    "manufacturer": "Medtronic, Inc.",
    "modelNumber": "W1DR01",
}

HIP_FHIR_DEVICE = {
    "resourceType": "Device",
    "id": "9002",
    "deviceName": [{"name": "Taperloc Complete", "type": "user-friendly-name"}],
    "type": {"coding": [{"code": "46763"}], "text": "Hip joint femoral stem prosthesis"},
    "manufacturer": "Zimmer Biomet",
}


class FakeClient:
    def __init__(self, device):
        self.device = device
        self.updated = None

    def get_device(self, device_id):
        return dict(self.device)

    def update_device(self, resource):
        self.updated = resource
        return resource


def test_set_implant_site_writes_extension(seeded_db, monkeypatch):
    fake = FakeClient(PACEMAKER_FHIR_DEVICE)
    monkeypatch.setattr(scan_to_chart, "_client", lambda: fake)
    result = scan_to_chart.set_implant_site("9001", "ra_rv", "left")
    assert result["success"] is True
    assert result["implant"]["lead_config"] == "ra_rv"
    assert result["implant"]["confirmed"] is True
    urls = [e["url"] for e in fake.updated["extension"]]
    assert IMPLANT_SITE_EXTENSION_URL in urls


def test_set_implant_site_rejects_non_cardiac(seeded_db, monkeypatch):
    fake = FakeClient(HIP_FHIR_DEVICE)
    monkeypatch.setattr(scan_to_chart, "_client", lambda: fake)
    result = scan_to_chart.set_implant_site("9002", "ra_rv", "left")
    assert result["success"] is False
    assert "not a covered" in result["error"]
    assert fake.updated is None


def test_set_implant_site_rejects_invalid_config(seeded_db, monkeypatch):
    fake = FakeClient(PACEMAKER_FHIR_DEVICE)
    monkeypatch.setattr(scan_to_chart, "_client", lambda: fake)
    result = scan_to_chart.set_implant_site("9001", "ra_rv_lv", "left")
    assert result["success"] is False
    assert "not valid" in result["error"]
    assert fake.updated is None


def test_simplify_device_extracts_implant(seeded_db):
    device = dict(PACEMAKER_FHIR_DEVICE)
    device["extension"] = [{
        "url": IMPLANT_SITE_EXTENSION_URL,
        "extension": [
            {"url": "leadConfig", "valueCode": "ra_rv"},
            {"url": "pocketSide", "valueCode": "left"},
            {"url": "bodySite", "valueCodeableConcept": {"text": "Right atrium"}},
        ],
    }]
    entry = scan_to_chart._simplify_device(device)
    assert entry["implant"]["lead_config"] == "ra_rv"
    assert entry["protocol_class"] == "pacemaker"
    assert entry["protocol_module"] == "cardiac_rhythm"


def test_simplify_device_implant_none_when_absent(seeded_db):
    entry = scan_to_chart._simplify_device(dict(PACEMAKER_FHIR_DEVICE))
    assert entry["implant"] is None
    assert entry["protocol_available"] is True
