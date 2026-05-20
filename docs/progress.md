# PeriopUDI — Development Progress Log

A running record of each build phase as it is completed. See `Build.md` for the authoritative
plan and acceptance criteria. Newest entries at the bottom.

---

## Phase 0 — Scaffolding  *(2026-05-19, complete)*

**Goal:** Establish the Build.md §3 repo structure and relocate the existing STA 2026 Flask app
without changing its logic.

**What was done:**
- Relocated the Flask app (`app.py`, `config.py`, `database_setup.py`, `gudid_service.py`,
  `llm_service.py`, `qr_generator.py`, `requirements.txt`) plus `templates/`, `static/`, `data/`,
  `Dockerfile`, and `.dockerignore` into `services/gudid-core/` via `git mv` (history preserved).
  Templates/static/data moved with the app so Flask resolves its relative paths.
- Created the service/infra tree with purpose-describing README stubs (no empty `.py` placeholders):
  `services/{fhir-bridge,cds-hooks,smart-launcher,ui}`, `infrastructure/{hapi,synthea}`,
  `docs/`, `eval/`, `scripts/`.
- Pointed `docker-compose.yml` build context at `./services/gudid-core`; renamed services to
  `gudid-core` / `gudid-core-dev`. Copied `.dockerignore` into the new build context.
- Added `LICENSE` (Apache-2.0), `CITATION.cff`, `Makefile` (phase-stubbed `seed`/`test`/`validate`
  targets), and rewrote `.gitignore`.

**Verification:** `docker compose build gudid-core` succeeds; container boots under gunicorn;
`/health` returns HTTP 200; SQLite DB initializes cleanly.

**Deviations from Build.md §3:** UI templates/static were kept with `gudid-core` rather than split
into `services/ui/` — that extraction is deferred to Phases 3–4 so the app keeps running now.

---

## Phase 1 — Local FHIR Foundation  *(2026-05-19, complete)*

**Goal:** HAPI FHIR R4 running locally with US Core v8.0.1 loaded and validation enabled, seeded
with synthetic patients.

**What was done:**
- Added `hapi-db` (Postgres 16) and `hapi` (`hapiproject/hapi:latest`, FHIR R4) services to
  `docker-compose.yml`. HAPI listens on **8080**; the existing `gudid-core` app was moved to
  **5000** to free the port.
- `infrastructure/hapi/application.yaml`: FHIR R4, Postgres datasource, **US Core v8.0.1** IG
  installed at startup, request validation enabled, CORS open, and the HAPI Tester web UI enabled
  at `http://localhost:8080/`.
- `infrastructure/synthea/`: custom `modules/perioperative_surgery.json` (guarantees an inpatient
  surgical encounter + procedure per adult), a `Dockerfile` (Temurin 17 JRE + curl) and `seed.sh`
  that downloads Synthea, generates patients, and loads bundles into HAPI via `$transaction`
  (organizations/practitioners first, then patients).
- `make hapi` (bring up + wait healthy) and `make seed` (one-shot seeder) targets.

**Verification:**
- `/fhir/metadata` reports fhirVersion **4.0.1** (HAPI FHIR 8.8.0).
- US Core v8.0.1 ValueSets/profiles indexed at startup (confirmed in logs).
- **Validation works:** `POST /fhir/Device` with an invalid status → **HTTP 422** OperationOutcome.
- **Seeded successfully** (exit 0, all bundles HTTP 200 under active validation):
  Patient **65** (50 alive + 15 deceased), Encounter 4,550, Procedure 11,628, Condition 2,543,
  Observation 38,260, Organization 175, Practitioner 175.

**Notes / fixes during the phase:**
- The `hapiproject/hapi` image is **distroless (no shell)**, so a `CMD-SHELL` Docker healthcheck
  could never run and blocked the seeder's `depends_on: service_healthy`. Fixed by removing the
  in-container healthcheck and having `seed.sh` poll `/fhir/metadata` itself before loading.
- Pointing `SPRING_CONFIG_LOCATION` solely at our minimal `application.yaml` initially disabled the
  image's bundled Tester UI; re-enabled via the `hapi.fhir.tester` config block.
- Synthea is a one-shot CLI generator (no UI/port); it runs in the `synthea-seed` container and
  exits. Browse the seeded data through HAPI at `http://localhost:8080/`.
- Synthea also generated **396 plain-R4 `Device` resources** (IUDs, contraceptive implants, etc.).
  These are generic R4 devices, not US Core Implantable Device-conformant — Phase 2 adds the
  GUDID-validated, profile-conformant Device path.

---

## Phase 2 — GUDID → US Core Device Mapper  *(2026-05-19, complete)*

**Goal:** Convert a GUDID record into a US Core v8.0.1 Implantable Device Profile-conformant FHIR
`Device`, validate it, and write it to HAPI.

**What was done:**
- `services/fhir-bridge/gudid_to_uscore_device.py` — `map_to_device(gudid_record, patient_id, ...)`
  maps the normalized GUDID dict (from `gudid_service.extract_device_info()`) to a FHIR R4 `Device`
  stamped with `meta.profile = us-core-implantable-device`. Populates `udiCarrier`
  (deviceIdentifier/issuer/carrierHRF), serial/lot/expiration/manufacture, manufacturer,
  deviceName, modelNumber, distinctIdentifier, GMDN-coded `type`, and `patient`. Accepts scan-time
  production-identifier overrides.
- `services/fhir-bridge/hapi_client.py` — `HapiClient` with `create_device`, `link_to_procedure`
  (Procedure.focalDevice via JSON Patch), `get_patient_devices`, and `validate` ($validate).
- `services/fhir-bridge/tests/test_mapper.py` — 5 representative GUDID records (drug-eluting stent,
  pacemaker, hip implant, minimal/edge, neurostimulator); 12 pure unit tests + 5 live US Core
  validations via HAPI.
- `services/fhir-bridge/tests/validate_against_ig.py` — HL7 FHIR Validator CLI wrapper for the
  offline/CI path (Phase 7).
- `services/fhir-bridge/requirements.txt`.

**Verification:**
- **17/17 tests pass** (run in a container with `requests` on the compose network).
- **100% of mapped sample Devices validate against US Core v8.0.1 with 0 errors** (via HAPI
  `$validate?profile=us-core-implantable-device`).
- Round-trip confirmed: a mapped Device `POST`s to HAPI → **HTTP 201** and is retrievable by
  `Device?patient=Patient/<id>`.

**Constraint discovered:** US Core v8.0.1 makes **`Device.type` required (min=1)**. The mapper now
always emits a `Device.type` — GMDN coding when available, else the record's type text, else a
generic `"Implantable device"` text. (In production `extract_device_info()` always supplies a type,
but the mapper guarantees it regardless.)

**Note on terminology warnings (non-blocking):** GMDN's code system (`urn:oid:2.16.840.1.113883.6.257`)
isn't loaded into HAPI's terminology, so GMDN codings raise *warnings* ("code system unknown",
"not in FHIR Device Types value set"). Device.type's binding is extensible, so these are warnings,
not errors — conformance still passes.

---

## Phase 3 — Scan-to-Chart Workflow  *(2026-05-19, complete)*

**Goal:** The hero demo. UDI scan → GUDID lookup → US Core Device created → linked to a patient,
end-to-end in seconds, with the result visible on a patient timeline.

**What was done:**
- **Wired fhir-bridge into the app:** `gudid-core` is now built from the **repo root**
  (`docker-compose.yml` build `context: .`, `dockerfile: services/gudid-core/Dockerfile`) so the
  image bakes in `gudid_to_uscore_device.py` and `hapi_client.py`. Root `.dockerignore` trimmed to
  keep the context lean (excludes the Synthea jar, etc.). The dev service bind-mounts the two
  modules instead.
- `services/gudid-core/scan_to_chart.py` — orchestration: `document_device()` (parse UDI → GUDID
  lookup → `map_to_device` → `create_device` → optional `link_to_procedure` → CSV log),
  `list_patients()` (picker feed), `get_patient_timeline()` (simplified, newest-first devices).
- New Flask routes in `app.py`: `GET/POST /scan-to-chart`, `GET /api/patients`,
  `GET /patient/<id>/devices`, `GET /patient/<id>/timeline`.
- Templates: `scan_to_chart.html` (UDI input + live patient picker + result panel) and
  `timeline.html` (per-patient device cards, US Core / recall / status badges). Added a
  **"Document to Chart"** button to the home page header.
- Every operation is logged to `eval/usage_logs/scans.csv` (timestamp, user, udi,
  device_identifier, patient_id, device_id, time_to_complete_ms, success).

**Verification (against live FDA GUDID + running HAPI):**
- Documented a real Abbott **XIENCE ALPINE** drug-eluting stent (DI `08717648200274`) to patient
  1602 → US Core `Device/90152` created; round-trip **~0.7–1.4 s** (well under the 15 s target).
- `GET /patient/1602/devices` returns the new US-Core device **first** (newest), alongside the
  patient's pre-existing generic Synthea devices — the `us_core` badge distinguishes them.
- Not-found path is graceful: a DI GUDID 404s on → `{"success": false, "error": "Device … not
  found in FDA GUDID"}`.
- All pages return HTTP 200; FHIR links use a browser-reachable base (`PUBLIC_FHIR_BASE_URL`).

**Decisions / notes:**
- **Port:** `gudid-core` runs on host **8090** (macOS AirPlay Receiver holds 5000).
- **Display URLs:** the container reaches HAPI at `http://hapi:8080` (internal) but renders links
  with `PUBLIC_FHIR_BASE_URL=http://localhost:8080/fhir` so they work in the browser.
- The existing GUDID `/scan` + device-info flow is untouched; scan-to-chart is additive.
- `scans.csv` is gitignored (eval data populated at runtime).

---
