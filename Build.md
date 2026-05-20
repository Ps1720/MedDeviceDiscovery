# PeriopUDI — Build Plan & Action Document

> **For Claude Code**: This is the authoritative build plan. Read it at the start of every session. Update the checklist as work completes. When in doubt, follow the phase order. Do not skip phases.

---

## 0. Project Context

**What we're building**: PeriopUDI — a SMART-on-FHIR perioperative device documentation application that uses the FDA GUDID database to capture, validate, and document implantable medical devices at the point of care.

**Why we're building it**: Submission to the **AMIA/HL7 2026 FHIR App Competition** (AMIA 2026 Annual Symposium, November 7–11, Dallas TX). Submission window opens July 2026, closes ~early August 2026.

**Track**: Non-student / academic. Real-world use claim will be backed by a clinical pilot with UAB Department of Anesthesiology assistant professors.

**Starting point**: An existing Flask web application built and presented at STA 2026 (Society for Technology in Anesthesia, Tampa, January 2026) that:
- Queries the FDA GUDID API by UDI/DI
- Returns device metadata (manufacturer, brand name, GMDN, regulatory status)
- Generates QR codes encoding device identifiers
- Tech stack: Flask (Python), FDA AccessGUDID API integration

**What's new in PeriopUDI vs. the STA tool**:
- FHIR R4 server integration (local HAPI)
- GUDID → US Core v8.0.1 Implantable Device Profile mapping
- Patient/Procedure linkage
- CDS Hooks recall surveillance
- SMART App Launch v2 conformance
- Pilot deployment with clinical collaborators

---

## 1. North Star Pitch (memorize this)

> *PeriopUDI is a SMART-on-FHIR application that closes the perioperative device-documentation gap by turning a 30-second scan into a USCDI-conformant, GUDID-validated, recall-aware implantable device record — at the point of care, in the OR.*

This sentence frames every design decision. If a feature doesn't serve this thesis, defer it.

---

## 2. Architectural Principles

1. **Three services, not a monolith**: GUDID core (existing Flask), FHIR bridge (new), CDS Hooks service (new). Each runs in its own container.
2. **HAPI is the source of truth for patient/device state.** All reads and writes go through it.
3. **GUDID is the authoritative source for device metadata.** Never hardcode device data.
4. **Conformance is verified, not claimed.** US Core v8.0.1 validation runs in CI.
5. **Build vertically, not horizontally.** One end-to-end workflow working > five half-built features.
6. **Demo-first design.** Every feature must show up in the 8-minute presentation. If it can't, defer it.

---

## 3. Repository Layout

```
periop-udi/
│
├── README.md                          # Top-level overview, demo GIF, AMIA pitch
├── BUILD.md                           # THIS FILE — keep updated
├── LICENSE                            # Apache-2.0
├── CITATION.cff                       # For reviewers to cite the work
├── docker-compose.yml                 # One-command stack: HAPI + Postgres + app services
├── Makefile                           # make demo, make seed, make test, make validate
├── .env.example
├── .gitignore
│
├── docs/
│   ├── architecture.md                # System diagram + data flow
│   ├── fhir-conformance.md            # Profiles, capability statement notes
│   ├── capability-statement.json      # Generated, valid FHIR CapabilityStatement
│   ├── demo-script.md                 # Timed 8-minute walkthrough
│   ├── pilot-protocol.md              # Clinical pilot scope + procedure
│   └── amia-submission/
│       ├── abstract.md                # 1,000 chars
│       ├── rationale.md               # 3,500 chars
│       ├── design.md                  # 7,000 chars
│       ├── evaluation.md              # 3,500 chars
│       └── twitter-summary.txt        # 140 chars
│
├── services/
│   │
│   ├── gudid-core/                    # Existing Flask app, relocated
│   │   ├── app.py
│   │   ├── fda_gudid_client.py        # AccessGUDID API
│   │   ├── udi_parser.py              # UDI string parsing
│   │   ├── qr_generator.py
│   │   ├── requirements.txt
│   │   └── tests/
│   │
│   ├── fhir-bridge/                   # NEW: GUDID → FHIR + HAPI client
│   │   ├── gudid_to_uscore_device.py  # Core mapper
│   │   ├── bundle_builder.py          # Transaction bundles
│   │   ├── hapi_client.py             # POST/GET against HAPI
│   │   ├── profiles/
│   │   │   └── us-core-8.0.1/         # Cached IG package
│   │   ├── requirements.txt
│   │   └── tests/
│   │       ├── test_mapper.py
│   │       └── validate_against_ig.py # HL7 Validator CLI integration
│   │
│   ├── cds-hooks/                     # NEW: recall surveillance service
│   │   ├── discovery.py               # GET /cds-services
│   │   ├── recall_check_service.py    # POST /cds-services/recall-check
│   │   ├── recall_poller.py           # Cron: pulls openFDA daily
│   │   ├── recalls.db                 # SQLite cache
│   │   ├── requirements.txt
│   │   └── tests/
│   │
│   ├── smart-launcher/                # NEW: SMART App Launch v2
│   │   ├── oauth_callback.py
│   │   ├── smart_config.py            # /.well-known/smart-configuration
│   │   ├── scopes.py
│   │   └── tests/
│   │
│   └── ui/                            # Scan-to-chart frontend
│       ├── templates/
│       │   ├── scan.html
│       │   ├── timeline.html
│       │   └── patient_picker.html
│       ├── static/
│       └── routes.py
│
├── infrastructure/
│   │
│   ├── hapi/                          # Local FHIR R4 server
│   │   ├── application.yaml           # US Core IG loaded, validation on
│   │   └── Dockerfile
│   │
│   └── synthea/                       # Synthetic patient substrate
│       ├── modules/
│       │   └── perioperative_surgery.json  # Custom surgical module
│       ├── config/
│       └── seed.sh                    # Loads N patients into HAPI
│
├── eval/                              # Evidence for evaluation section
│   ├── usability_study/
│   │   ├── protocol.md
│   │   ├── sus_questionnaire.md
│   │   ├── results.csv                # Populated during pilot
│   │   └── analysis.ipynb
│   ├── time_to_documentation.md
│   ├── conformance_report.md          # IG Publisher output
│   ├── recall_detection_validation.md
│   └── usage_logs/
│
└── scripts/
    ├── demo_reset.sh                  # Reset state between demo runs
    ├── load_test_devices.sh           # Pre-load known UDIs
    └── generate_capability_statement.py
```

---

## 4. Build Phases

> Build phases linearly. Each phase has acceptance criteria. Do not proceed until criteria are met.

### ✅ Phase 0 — Scaffolding (Day 1)

**Goal**: Repo structure exists, existing Flask app relocated, no logic changed.

**Tasks**:
- [x] Create the repo layout in section 3 above
- [x] Move existing Flask app into `services/gudid-core/` without modification (templates/, static/, data/ moved with it so Flask resolves paths)
- [x] Create stub READMEs in each new service folder (dirs + README stubs; no empty .py placeholders)
- [x] Initialize `.gitignore`, `LICENSE` (Apache-2.0), `CITATION.cff`, `Makefile`
- [ ] Commit: "Phase 0: repo scaffolding"  *(pending user go-ahead)*

**Acceptance**: ✅ Relocated app builds and boots from `services/gudid-core/` (docker compose build + `/health` → HTTP 200). `docker-compose.yml`/`Dockerfile`/`.dockerignore` updated for the new build context.

---

### Phase 1 — Local FHIR Foundation (Days 2–3)

**Goal**: HAPI FHIR R4 running locally with US Core v8.0.1 loaded, validation enabled, seeded with synthetic patients.

**Tasks**:
- [ ] Write `docker-compose.yml` bringing up:
  - HAPI FHIR R4 server (hapiproject/hapi:latest) on port 8080
  - Postgres for HAPI persistence
  - A Synthea seeder container (one-shot)
- [ ] Configure `infrastructure/hapi/application.yaml`:
  - FHIR version: R4
  - US Core v8.0.1 IG package loaded at startup
  - Validation enabled for write operations
  - CORS open for local development
- [ ] Write `infrastructure/synthea/seed.sh`:
  - Generates 50 synthetic patients
  - Includes a custom `perioperative_surgery.json` module adding surgical encounters
  - Loads bundles via HAPI's `$transaction` endpoint
- [ ] Add `make seed` target to root Makefile
- [ ] Verify: `curl http://localhost:8080/fhir/Patient?_count=5` returns 5 patients

**Acceptance**:
- `docker-compose up` brings everything online
- `make seed` populates 50 patients
- HAPI rejects a deliberately invalid Device resource (validation working)

**Hand to Claude Code prompt**:
> *"Implement Phase 1 per BUILD.md. Set up docker-compose with HAPI FHIR R4 + Postgres, configure HAPI to load the US Core v8.0.1 Implementation Guide with validation enabled, and write a Synthea seed script that creates 50 patients with surgical histories."*

---

### Phase 2 — GUDID → US Core Device Mapper (Days 4–6)

**Goal**: Convert a GUDID record into a US Core v8.0.1 Implantable Device Profile-conformant FHIR Device resource, validate it, write it to HAPI.

**Tasks**:
- [ ] Implement `services/fhir-bridge/gudid_to_uscore_device.py`:
  - Function signature: `map_to_device(gudid_record: dict, patient_id: str) -> dict`
  - Returns a FHIR Device resource as a Python dict
  - Populates: `meta.profile` (US Core Implantable Device), `udiCarrier` (deviceIdentifier, issuer, jurisdiction, carrierHRF), `manufacturer`, `deviceName`, `type` (with GMDN coding), `status`, `patient` reference
- [ ] Implement `services/fhir-bridge/hapi_client.py`:
  - `create_device(device_resource) -> str` returns the Device's logical ID
  - `link_to_procedure(device_id, procedure_id)` updates Procedure.focalDevice
  - `get_patient_devices(patient_id) -> list`
- [ ] Implement `services/fhir-bridge/tests/validate_against_ig.py`:
  - Downloads HL7 FHIR Validator CLI on first run
  - Validates a generated Device against US Core v8.0.1
  - Used by CI and as a standalone CLI: `python validate_against_ig.py <file>`
- [ ] Write `tests/test_mapper.py` with 5+ sample GUDID records → expected Device output
- [ ] Acceptance test: 100% of mapped resources pass US Core validation

**Acceptance**:
- `pytest services/fhir-bridge/tests` all green
- Generated Devices validate clean against US Core v8.0.1
- A Device created via the mapper appears in HAPI and is retrievable

**Hand to Claude Code prompt**:
> *"Implement Phase 2. Build the GUDID-to-US-Core-Device mapper per BUILD.md section 4 Phase 2. Use the FHIR R4 spec and US Core v8.0.1 Implantable Device Profile. Validate output using the HL7 FHIR Validator CLI. Write tests with at least 5 sample GUDID records."*

---

### Phase 3 — Scan-to-Chart Workflow (Days 7–9)

**Goal**: The hero demo. UDI scan → GUDID lookup → FHIR Device created → linked to patient. End-to-end in under 15 seconds.

**Tasks**:
- [ ] New Flask endpoint `POST /scan-to-chart`:
  - Inputs: UDI string, patient_id, optional procedure_id
  - Flow: parse UDI → call existing GUDID client → map to Device → POST to HAPI → return Device URL + success metadata
- [ ] UI page `templates/scan.html`:
  - Text input for UDI (or scan via webcam using `html5-qrcode` library)
  - Patient picker dropdown (live from HAPI `GET /Patient?_count=50`)
  - "Document Device" button
  - Result panel showing the created Device with its FHIR URL
- [ ] UI page `templates/timeline.html`:
  - Given a patient_id, displays all Devices in reverse chronological order
  - Shows: device name, manufacturer, implant date, status, recall flag (placeholder for now)
- [ ] Log every scan to `eval/usage_logs/scans.csv`:
  - timestamp, user, UDI, patient_id, time_to_complete_ms, success

**Acceptance**:
- Scanning a real UDI from a known device package completes end-to-end in <15s
- The created Device is visible at `http://localhost:8080/fhir/Device/<id>`
- The patient's timeline view shows the new entry

**Hand to Claude Code prompt**:
> *"Implement Phase 3. Build the scan-to-chart Flask endpoint and minimal UI per BUILD.md. Use html5-qrcode for camera-based scanning, with a text fallback. Log every operation to eval/usage_logs/scans.csv."*

---

### Phase 4 — Implant Timeline View (Days 10–11)

**Goal**: A clinically useful view that anesthesiologists actually want for pre-op planning.

**Tasks**:
- [ ] Endpoint `GET /patient/<id>/devices` → JSON of all Devices for that patient
- [ ] Endpoint `GET /patient/<id>/timeline` → rendered HTML timeline
- [ ] Visual design: vertical timeline, color-coded by device type (cardiac, neurostim, ortho, etc.)
- [ ] Each entry shows: device name, manufacturer, GMDN term, implant date, status badge
- [ ] Empty state: helpful message if no devices

**Acceptance**:
- A pre-loaded patient with 3 devices renders cleanly in timeline view
- The timeline updates within 2 seconds of a new scan

---

### Phase 5 — FDA Recall Feed + CDS Hooks Service (Days 12–15)

**Goal**: The innovation moment. Real-time recall surveillance via CDS Hooks.

**Tasks**:
- [ ] Implement `services/cds-hooks/recall_poller.py`:
  - Cron-style: runs daily (or on demand for demo)
  - Pulls device recalls from openFDA: `https://api.fda.gov/device/recall.json`
  - Stores in SQLite: `recalls.db` with table `recalls(device_identifier, recall_number, classification, reason, recall_initiation_date, status)`
- [ ] Implement CDS Hooks discovery endpoint: `GET /cds-services`
  - Returns the service catalog with one service: `recall-check`
  - Triggered on `patient-view`
- [ ] Implement CDS Hooks execution endpoint: `POST /cds-services/recall-check`
  - Accepts the CDS Hooks request payload (hook, hookInstance, context, fhirServer)
  - Fetches all Devices for the patient from the supplied fhirServer
  - Cross-references each Device's `udiCarrier.deviceIdentifier` against the recalls table
  - Returns Cards for any matches, with summary, indicator ("warning"), and source
- [ ] Integrate Card display into the timeline UI
- [ ] Pre-load at least 1 known recalled UDI for demo purposes

**Acceptance**:
- CDS Hooks discovery returns a valid response
- A patient with a recalled device triggers a warning Card
- A patient without any recalled devices returns an empty cards array
- Card display in the UI is unmissable

**Hand to Claude Code prompt**:
> *"Implement Phase 5. Build a CDS Hooks service per the spec at cds-hooks.hl7.org with one service `recall-check` triggered on `patient-view`. Include a daily openFDA recall poller and SQLite cache. Integrate Card display into the timeline UI."*

---

### Phase 6 — SMART App Launch v2 (Days 16–17)

**Goal**: The app is launchable from any SMART-conformant EHR with proper OAuth2 and patient context.

**Tasks**:
- [ ] Add `fhirclient` to requirements
- [ ] Implement `/.well-known/smart-configuration` endpoint
- [ ] Implement `/launch` endpoint accepting `iss` and `launch` parameters
- [ ] Implement OAuth2 callback handler
- [ ] Define scopes: `launch openid fhirUser patient/Patient.read patient/Device.read patient/Device.write patient/Procedure.read`
- [ ] Register PeriopUDI as a SMART app in HAPI
- [ ] Test against:
  - HAPI's built-in SMART authorization server, AND
  - The public SMART Health IT launcher (https://launch.smarthealthit.org)
- [ ] Document the client_id, redirect_uri, and scopes in `docs/fhir-conformance.md`

**Acceptance**:
- Launching from the SMART Health IT launcher loads PeriopUDI with patient context pre-set
- The scan-to-chart workflow uses the launched patient automatically (no manual picker)
- Scopes are minimum-necessary, not wildcard

**Hand to Claude Code prompt**:
> *"Implement Phase 6. Add SMART App Launch v2 to PeriopUDI using the fhirclient Python library. Test against HAPI's SMART auth server and the SMART Health IT public launcher. Scopes per BUILD.md."*

---

### Phase 7 — US Core Validation in CI (Day 18)

**Goal**: Every Device resource the app produces is automatically validated against US Core v8.0.1 in CI.

**Tasks**:
- [ ] Write `tests/conformance/test_all_mapped_devices.py` that runs the HL7 FHIR Validator against every Device the mapper has ever produced (from a fixture set)
- [ ] Add GitHub Actions workflow `.github/workflows/validate.yml`:
  - Runs on every PR
  - Spins up the validator, runs conformance tests, fails if any errors
- [ ] Add badge to README: "US Core v8.0.1 ✅"
- [ ] Generate `docs/capability-statement.json` programmatically and validate it

**Acceptance**:
- CI passes
- README badge is live
- Capability Statement is valid FHIR

---

### Phase 8 — Evaluation Harness (Days 19–21)

**Goal**: Generate the quantitative data for the AMIA Evaluation section.

**Tasks**:
- [ ] Ensure `eval/usage_logs/scans.csv` captures everything needed (already done in Phase 3)
- [ ] Build the SUS questionnaire as a Google Form (template URL in `docs/pilot-protocol.md`)
- [ ] Write `eval/analysis.ipynb`:
  - Loads scans.csv
  - Computes: total scans, unique patients, unique users, mean/median time-to-completion, success rate
  - Loads SUS results, computes the standard SUS score
  - Generates summary table for the submission
- [ ] Write `make evaluation-report` target that runs the notebook and outputs markdown

**Acceptance**:
- Notebook runs cleanly against test data
- Output report has the numbers the submission needs

---

### Phase 9 — Clinical Pilot (Weeks 5–7)

**Goal**: Defensible "real-world use" claim backed by ≥2 UAB assistant professors using the tool over 6–8 weeks.

**Pre-pilot checklist**:
- [ ] Two assistant professor collaborators verbally committed
- [ ] Pilot protocol drafted in `docs/pilot-protocol.md`:
  - Scope: pre-op assessment / OR setting
  - Synthetic patients only (no PHI) — this is the legal/regulatory safety net
  - Real device packages from the OR (empty implant boxes)
  - 4–6 sessions per clinician, ~20 minutes each
  - Pre/post SUS questionnaire
- [ ] IRB **non-human-subjects-research** determination obtained in writing
- [ ] Onboarding deck created (5–10 slides explaining the tool)

**During pilot**:
- [ ] 4–6 sessions per clinician scheduled
- [ ] Each session: 3–5 device package scans, full workflow exercised, real-time observations captured
- [ ] Scan logs accumulating in `scans.csv`
- [ ] Weekly review with clinicians, iterate on UX feedback

**Post-pilot data**:
- [ ] SUS scores collected
- [ ] Time-to-documentation measured
- [ ] Qualitative feedback synthesized
- [ ] Clinical quote captured from each collaborator for the submission

**Acceptance**:
- ≥2 clinicians, ≥6 weeks deployment window, ≥30 documented device scans, SUS data collected

---

### Phase 10 — Submission Polish + Materials (Weeks 7–8)

**Goal**: AMIA submission is ready by mid-July 2026. Buffer time for revisions.

**Tasks**:
- [ ] Record demo video (3 minutes, screen recording with voiceover) showing:
  1. SMART launch into PeriopUDI (5s)
  2. Scan a UDI → Device documented → timeline updates (15s)
  3. Open a patient with a recalled device → CDS Hooks Card fires (10s)
  4. Open the bulk timeline view → multiple devices visible (10s)
  5. Architecture diagram + closing message (rest)
- [ ] Write submission sections per `docs/amia-submission/`:
  - Abstract (1,000 chars) — see template below
  - Rationale (3,500 chars)
  - Design and Implementation (7,000 chars)
  - Evaluation and Sustainability (3,500 chars)
  - Twitter summary (140 chars)
- [ ] Generate final Capability Statement
- [ ] Create SMART App Gallery listing (draft, publish post-submission)
- [ ] Author list finalized (you + clinical collaborators)
- [ ] All links live: GitHub repo, demo video, capability statement, screenshots

**Acceptance**: Submission ready 1 week before deadline.

---

## 5. FHIR Technology Stack — What We Claim

Listed in `docs/fhir-conformance.md` and the AMIA submission:

| Technology | Status | Use case |
|---|---|---|
| **SMART App Launch v2** | Implemented | EHR-launchable, OAuth2 patient context |
| **CDS Hooks** (`patient-view`) | Implemented | Real-time FDA recall surveillance |
| **US Core v8.0.1** (Implantable Device Profile) | Validated in CI | Conformant Device resources |
| **FHIR R4 REST** | Implemented | Device, Patient, Procedure read/write |
| **FHIR Bulk Data** | Future work | Institution-wide registry analytics |
| **CQL** | Not used | (Honest omission — not applicable) |

**Rule**: Never claim a technology the demo doesn't touch.

---

## 6. FHIR Resources Used

- `Device` (US Core Implantable Device Profile) — primary
- `Patient` — context
- `Procedure` (with `focalDevice`) — surgical linkage
- `Encounter` — perioperative context
- `DetectedIssue` — recall flags
- `AuditEvent` — operation logging
- `CapabilityStatement` — server declaration

---

## 7. Anti-patterns — What Not to Build

- ❌ Don't add a database other than HAPI's Postgres + the recalls SQLite. No Redis, no MongoDB.
- ❌ Don't build microservice infrastructure. The 3 services are enough.
- ❌ Don't add user authentication beyond SMART. Single-tenant pilot.
- ❌ Don't build for production scale. This is a demo + pilot, not a SaaS.
- ❌ Don't claim FHIR features that aren't demonstrable in 8 minutes.
- ❌ Don't generate synthetic device data — always use real GUDID.
- ❌ Don't touch real PHI under any circumstances. Synthea only.
- ❌ Don't skip the FHIR Validator step. Conformance is the credibility floor.

---

## 8. Timeline Summary

| Week | Phase | Deliverable |
|---|---|---|
| 1 | 0 + 1 | Repo scaffolded, HAPI running, 50 patients seeded |
| 1 | 2 | GUDID-to-FHIR mapper, validated against US Core |
| 2 | 3 | Scan-to-chart workflow working end-to-end |
| 2 | 4 | Implant timeline view |
| 3 | 5 | CDS Hooks recall service live |
| 3 | 6 | SMART App Launch working |
| 3 | 7 + 8 | CI conformance, evaluation harness |
| 4–7 | 9 | Clinical pilot with 2+ UAB assistant professors |
| 7–8 | 10 | Submission writing + polish |
| End of week 8 | — | Submitted to AMIA |

---

## 9. Submission Field Cheatsheet

When filling out the AMIA submission form, the answers are:

- **Category**: Academic
- **Project title**: PeriopUDI: SMART-on-FHIR Perioperative Device Documentation with Real-Time FDA Recall Surveillance
- **How is FHIR being used**: "Machine-to-machine and end user-facing. Patient-context launched via SMART on FHIR; Device resources written to a FHIR R4 server with US Core v8.0.1 conformance; CDS Hooks service provides point-of-care recall alerts."
- **FHIR release**: R4
- **FHIR resources used**: Device, Patient, Procedure, Encounter, DetectedIssue, AuditEvent, CapabilityStatement
- **Data source**: FDA GUDID for device metadata; openFDA recall feed for surveillance; SMART-on-FHIR launched against HAPI FHIR R4 (pilot) or any SMART-conformant EHR (deployment).
- **Implementation guides**: US Core v8.0.1 (Implantable Device Profile primary)
- **FHIR technologies**: SMART App Launch v2, CDS Hooks, FHIR R4 REST
- **Real-world use**: Deployed at UAB Department of Anesthesiology, [N] assistant professors, [date range], [N] documented devices. Presented at STA 2026 Engineering Challenge, Tampa, January 2026.
- **SMART App Gallery**: Yes
- **Twitter summary**: "PeriopUDI: scan an implant in the OR → FHIR Device documented → FDA recalls checked. SMART-on-FHIR. US Core v8. Built at UAB."

---

## 10. Working with Claude Code — Rules

1. **Read this file at the start of every session.**
2. **Update the checkboxes as you complete tasks.** Treat them as the source of truth on progress.
3. **One phase at a time.** Don't jump ahead.
4. **Verify, don't assume.** After each major piece, run the relevant test or validator.
5. **Small prompts, specific scope.** Reference this document by section number.
6. **Don't refactor without need.** This is a demo app on a deadline.
7. **Surface blockers immediately.** If a phase can't proceed (e.g., clinician collaborator not committed), say so and propose a workaround.
8. **Architecture decisions land in `docs/architecture.md`.** Decisions stay decided.
9. **All FHIR output validates against US Core.** No exceptions.
10. **Demo-first.** Every commit should keep the demo functional.

---

## 11. Critical-Path Definition of Done

The **minimum** that must be true for a credible AMIA submission:

- [ ] HAPI runs locally with US Core IG loaded
- [ ] GUDID-to-Device mapping produces valid US Core resources
- [ ] Scan-to-chart workflow works end-to-end in under 15 seconds
- [ ] Patient implant timeline view renders correctly
- [ ] CDS Hooks recall alert fires for a known recalled UDI
- [ ] SMART App Launch works against HAPI (and ideally SMART Health IT launcher)
- [ ] ≥2 UAB assistant professors have used the tool, SUS collected
- [ ] Demo video recorded and under 3 minutes
- [ ] All 4 submission sections drafted and reviewed by a co-author

If any of these is missing 2 weeks before the deadline, **cut Bulk Data and Subscriptions, double-down on what's listed**.

---

## 12. Open Questions / Decisions Pending

> Update this section as questions arise and get resolved.

- [ ] Which UAB assistant professors are confirmed co-authors? (Names → contact → commitment date)
- [ ] Does UAB have an Epic non-production sandbox we can register against?
- [ ] IRB non-human-subjects-research determination submitted? (Date submitted → date received)
- [ ] SMART Health IT launcher: is the public sandbox sufficient for the demo or do we need our own?
- [ ] Hardware: do we have a barcode/QR scanner for the OR pilot or use phone cameras?

---

*Last updated: 2026-05-19 — Phase 0 complete (scaffolding + app relocation, verified via Docker build & /health).*