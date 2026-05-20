# cds-hooks  *(Phase 5 — implemented)*

CDS Hooks recall-surveillance service (spec: cds-hooks.hl7.org).

Endpoints:
- `GET /cds-services` — discovery; advertises one service `recall-check` on the
  `patient-view` hook.
- `POST /cds-services/recall-check` — fetches the patient's `Device` resources from the
  supplied `fhirServer`, matches each `udiCarrier.deviceIdentifier` against the recall cache,
  and returns CDS Hooks **Cards** (one per recalled device). `Class I` recalls use
  `indicator: critical`, others `warning`. Cards carry non-standard `deviceIdentifier`/`deviceId`
  helper fields so the PeriopUDI timeline can attach per-device badges.
- `GET /health` — status + cached recall count.

Modules:
- `recalls.py` — SQLite cache (`recalls` table keyed by UDI-DI) + lookup.
- `recall_poller.py` — seeds curated **demo** recalls (real GUDID DIs, clearly marked
  `source=demo`) and does a best-effort pull of the openFDA `device/recall` feed.

**openFDA caveat:** openFDA's device-recall feed is keyed by product code / recalling firm and
does **not** carry the UDI-DI, so those rows generally won't match a specific scanned device.
DI-level matching therefore relies on curated entries for the demo; a production deployment would
integrate a UDI-DI-indexed recall source. The demo recalls guarantee the workflow lights up.

Refresh the cache: `make recalls` (seeds demo + pulls openFDA).

**Status:** discovery valid; recalled-device patients return warning/critical Cards; clean patients
return an empty `cards` array; recall badges + banner render on the patient timeline.
