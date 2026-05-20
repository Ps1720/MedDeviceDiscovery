# ui  *(Phases 3–4 — not yet implemented)*

Scan-to-chart frontend. The hero workflow: UDI scan → GUDID lookup → FHIR Device created →
linked to patient → implant timeline.

Planned:
- `templates/scan.html` — UDI input (text + `html5-qrcode` camera), patient picker, result panel.
- `templates/timeline.html` — patient implant timeline, color-coded by device type, recall flags.
- `templates/patient_picker.html` — live patient list from HAPI.
- `routes.py` — Flask routes for the workflow.

Note: in Phase 0 the existing UI still lives with `gudid-core` (templates/, static/) so the app
keeps running. UI extraction into this service happens as Phases 3–4 build the new workflow.
