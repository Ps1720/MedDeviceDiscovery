# fhir-bridge  *(Phase 2 — not yet implemented)*

GUDID → FHIR mapping and HAPI client.

Planned modules:
- `gudid_to_uscore_device.py` — maps a GUDID record to a US Core v8.0.1 Implantable Device
  Profile-conformant FHIR `Device` resource. `map_to_device(gudid_record, patient_id) -> dict`.
- `bundle_builder.py` — assembles FHIR transaction bundles.
- `hapi_client.py` — `create_device`, `link_to_procedure`, `get_patient_devices` against HAPI.
- `profiles/us-core-8.0.1/` — cached US Core IG package.
- `tests/validate_against_ig.py` — runs the HL7 FHIR Validator CLI against generated resources.

Conformance rule (Build.md §10): all FHIR output must validate against US Core v8.0.1.
