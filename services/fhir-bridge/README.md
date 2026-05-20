# fhir-bridge  *(Phase 2 — implemented)*

GUDID → FHIR mapping and HAPI client.

Modules:
- `gudid_to_uscore_device.py` — `map_to_device(gudid_record, patient_id, ...)` converts the
  normalized GUDID dict (from `gudid_service.extract_device_info()`) into a FHIR R4 `Device`
  conformant to the **US Core v8.0.1 Implantable Device Profile**. Maps `udiCarrier`
  (deviceIdentifier, issuer, carrierHRF), production identifiers (serial/lot/expiry/manufacture),
  manufacturer, deviceName, modelNumber, GMDN-coded `type` (always present — US Core requires it),
  and the `patient` reference.
- `hapi_client.py` — `HapiClient` with `create_device`, `link_to_procedure` (Procedure.focalDevice),
  `get_patient_devices`, and `validate` (server `$validate` against the loaded US Core IG).
- `tests/test_mapper.py` — 5 representative GUDID records; pure mapping unit tests plus live
  US Core validation against a running HAPI (skipped if `requests`/HAPI absent).
- `tests/validate_against_ig.py` — offline validation via the HL7 FHIR Validator CLI (Phase 7 / CI).

Conformance rule (Build.md §10): all FHIR output must validate against US Core v8.0.1.
**Status:** 17/17 tests pass; all sample Devices validate with 0 errors against US Core v8.0.1.

Run tests (needs a running HAPI + `requests` for the live checks):

```bash
pip install -r services/fhir-bridge/requirements.txt
FHIR_BASE_URL=http://localhost:8080/fhir pytest services/fhir-bridge/tests -q
```
