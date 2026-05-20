# cds-hooks  *(Phase 5 — not yet implemented)*

CDS Hooks recall-surveillance service (spec: cds-hooks.hl7.org).

Planned modules:
- `discovery.py` — `GET /cds-services` service catalog (one service: `recall-check`).
- `recall_check_service.py` — `POST /cds-services/recall-check`, triggered on `patient-view`.
  Fetches the patient's Devices, cross-references `udiCarrier.deviceIdentifier` against the
  recall cache, returns warning Cards for matches.
- `recall_poller.py` — daily pull from openFDA `device/recall.json`.
- `recalls.db` — SQLite cache of recalls.
