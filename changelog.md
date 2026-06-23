# PeriopUDI Changelog

All notable changes to the PeriopUDI project are documented in this file. This changelog tracks implementation progress through the 10-phase build plan outlined in Build.md.

---

## [Unreleased]

---

### Current Status — 2026-06-23

**Where we are:** The IFU pipeline now fires automatically in the background every time
a device is documented via scan-to-chart. When a UDI is scanned and the device has a
recognized protocol class (cardiac, neuro, diabetes), a daemon thread immediately starts
searching for the manual PDF — first via GUDID labeling URLs, then via Google Custom
Search — downloading and extracting magnet/MRI facts without blocking the scan response.
The pipeline skips devices whose brand has already been processed (no wasted API quota).

**What's wired up:**
- Scan-to-chart auto-triggers IFU pipeline background thread on every successful document
- GUDID DI lookup (v3 + v2) → Google Custom Search fallback → PDF download → magnet/MRI
  fact extraction via LLM → GUDID cross-validation → `brand_facts` storage
- Google Custom Search keys set in `.env` (free tier: 100 queries/day)
- `ifu_pipeline` field returned in the scan result (`"started"` or `"skipped"`)
- All extracted facts remain `requires_verification=1` until a clinician runs `--verify`

**Immediate next steps:**
1. Document the Abbott Aveir™ (`05415067040725`) — watch Docker logs for `[ifu-pipeline]` output
2. Verify the IFU facts (magnet_mode: no magnet response for Aveir) appear in the protocol panel
3. Clinician review and sign-off (`python ifu_pipeline.py --verify <id> --by "Dr. ..."`)
4. Phase 6: SMART App Launch

---

### Added — IFU Pipeline: Automated Brand-Specific Fact Extraction (2026-06-22)

Closes the gap where magnet behavior and other brand-specific clinical facts were
generic class-level text ("varies by manufacturer — see brand info") with no actual
brand data behind them. The pipeline finds the device's Instructions for Use PDF,
extracts structured clinical facts via LLM, cross-validates them against GUDID, and
stores them in the `brand_facts` table with full provenance tracking.

**Files added (`services/gudid-core/`):**

- **`ifu_finder.py`** — IFU URL discovery in priority order:
  (1) AccessGUDID v3 labeling endpoint, (2) AccessGUDID v2 device endpoint,
  (3) **Google Custom Search JSON API** (requires `GOOGLE_API_KEY` + `GOOGLE_CSE_ID`
  env vars — both are set in `.env`; query: `"{Manufacturer} {Brand} {Model} physician
  manual IFU filetype:pdf"`; returns first PDF link from results),
  (4) hint-only fallback that returns a Google search URL for manual follow-up.

- **`ifu_extractor.py`** — Downloads the PDF, extracts text from clinically relevant
  pages (magnet, MRI, electrocautery, support sections) via `pdfplumber`, then calls
  the configured LLM to return a structured JSON of clinical facts:
  `magnet_rate_bpm`, `magnet_mode`, `magnet_response_programmable_off`,
  `magnet_inhibits_tachy_therapy`, `mri_conditional`, `mri_conditions_summary`,
  `support_phone_24hr`, `electrocautery_recommendation`, `em_interference_notes`.

- **`ifu_validator.py`** — Cross-validates extracted facts against the GUDID record:
  MRI safety status consistency (GUDID `MRISafetyStatus` vs extracted `mri_conditional`),
  manufacturer name match (catches wrong-manual fetches), magnet rate plausibility check.
  Returns a `confidence` score (0–1) and `conflicts` list; any conflict blocks facts
  from serving without a VERIFY banner and flags the record for clinician review.

- **`ifu_store.py`** — Writes pipeline results to two DB tables. `ifu_records` stores
  one row per (device, IFU URL): `ifu_url`, `ifu_hash`, `last_fetched`, `extracted_at`,
  `conflict_flags`, `status` (pending/extracted/conflict/verified). `brand_facts` rows
  are written with `source='llm'`, `source_url`, `extracted_at`, and `ifu_record_id`
  so every fact is traceable to its source document. `mark_verified(id, by)` clears
  `requires_verification` on all facts for a record once a clinician signs off.

- **`ifu_pipeline.py`** — Orchestrator + CLI. Ties all four steps together in sequence.
  Re-hash detection: if the PDF hash matches the stored `ifu_hash`, extraction is skipped
  and the existing facts remain valid. CLI usage:
  ```
  # Run pipeline for a device
  python ifu_pipeline.py --di 00643169634589 --manufacturer Medtronic \
                         --brand "Azure XT DR" --model W1DR01

  # Provide PDF URL directly (skip finder)
  python ifu_pipeline.py --manufacturer Medtronic --brand "Azure XT" \
                         --url https://example.com/azure_ifu.pdf

  # List all IFU records with status
  python ifu_pipeline.py --list

  # Mark record 3 as clinician-verified
  python ifu_pipeline.py --verify 3 --by "Dr. Smith"
  ```

**`protocol_db.py` changes:**
- New `ifu_records` table in schema (tracked above).
- `brand_facts` extended with: `source`, `source_url`, `extracted_at`, `ifu_record_id`.
- `_run_migrations()` handles backward-compatible column additions for existing DBs.
- New functions: `upsert_ifu_record()`, `get_ifu_record()`, `list_ifu_records()`.

**`requirements.txt`:** added `pdfplumber==0.11.4`.

**Design notes:**
- All LLM-extracted facts carry `requires_verification=1` and show the VERIFY banner
  until a clinician runs `mark_verified()`. This is non-negotiable for clinical safety.
- If GUDID returns a labeling URL, no web search API key is needed. `GOOGLE_API_KEY`
  and `GOOGLE_CSE_ID` are only used as a fallback for devices without GUDID labeling
  links. Free tier covers 100 queries/day — well within budget for a per-model-ever
  caching strategy.
- The pipeline degrades gracefully at each step: no PDF URL → record saved with status
  `pending`; PDF unparseable → `no_facts`; LLM fails → `no_facts`; validation conflict
  → `conflict` (facts saved but not auto-written to `brand_facts`).

### Added — 3D Heart Visual + Clinician-Captured Implant Location (2026-06-11)

A "Visual" tab on the patient-chart protocol view for cardiac rhythm devices: an
interactive Three.js 3D heart with the device drawn at its implant location and an
interactive magnet simulation. Implant location is now real patient data.

- **Implant location data model** — `services/gudid-core/implant_sites.py` (pure module):
  per-class lead configs (pacemaker ra_rv/rv_only/ra_only; CRT ra_rv_lv; ICD rv_only/
  ra_rv/subcutaneous S-ICD; leadless leadless_rv) + pocket side. Stored on the FHIR
  Device as a complex extension (`…/StructureDefinition/implant-site`) with SNOMED-coded
  body sites (codes flagged VERIFY; uncoded sites emit text-only CodeableConcepts).
  **Extension present = clinician-confirmed; absent = "typical placement" rendering.**
- **Capture at scan time** — scan-to-chart form pre-resolves the UDI (debounced lookup)
  and reveals an "Implant location" selector for cardiac rhythm devices; the choice rides
  the existing POST and is written with the Device (with a retry-without-extension safety
  net if HAPI rejects it). `protocol` blocks for cardiac classes now carry
  `implant_options`.
- **Set location later** — `PUT /api/device/<id>/implant-site` (new HapiClient
  `get_device`/`update_device`) lets clinicians confirm location on devices documented
  before this feature; available inline in the Visual tab.
- **Visual tab** — timeline overlay gains Protocol | Visual tabs (Visual only for
  cardiac rhythm devices). `static/heart_visual.js`: procedurally built stylized 3D
  heart (Three.js r128 via CDN, lazy-loaded; license-clean, no downloaded mesh),
  translucent chambers with RA/RV/LA/LV labels, device can + leads routed to the stored
  (or typical) location, leadless capsule and S-ICD variants, beating animation synced
  to an ECG-style strip, orbit/zoom controls, WebGL-absent fallback message.
- **Magnet simulation** — "Apply magnet" animates a magnet onto the can; behavior driven
  by the protocol knowledge base: pacemaker/CRT-P → asynchronous pacing at the brand
  magnet rate (e.g. Medtronic 85 bpm, VERIFY) with pacing-spike ECG + pulse rings at lead
  tips; ICD/CRT-D → "TACHY THERAPY SUSPENDED — PACING UNCHANGED" badge; leadless → "NO
  MAGNET RESPONSE — REPROGRAMMING REQUIRED". Missing rate facts fall back to a generic
  90 bpm explicitly labeled illustrative. CRT-P magnet-rate brand facts added to the seed
  (SEED_VERSION 2026.06.2).
- **Honest labeling** — "Location confirmed by clinician" vs "Typical placement — not
  confirmed" badge; magnet-rate verification status surfaced; standing "Stylized anatomy —
  illustrative, not a clinical image" + protocol disclaimer.
- **Tests** — 65 passing (new: test_implant_sites.py, test_implant_write.py, implant
  options + CRT-P rate coverage). Headless-Chrome screenshot harness at
  `static/hv_test.html` (dev fixture) validated all four scene variants.

### Added — Perioperative Protocol Layer (2026-06-10)

Implements all five features from Suggestions.md on a shared foundation: a UDI scan now
returns actionable perioperative guidance ("what do I do right now"), not just a data sheet.

- **Protocol knowledge base (SQLite)** — `services/gudid-core/protocol_db.py` +
  `protocol_seed.py`. Version-gated startup seeding (recall-cache pattern); DB at
  `data/protocols.db` (`PROTOCOL_DB_PATH`). 11 device classes across three modules:
  cardiac rhythm (pacemaker, leadless, ICD, CRT-P, CRT-D), neuromodulation (VNS, DBS, SCS),
  diabetes (insulin pump, CGM, closed-loop AID).
- **Device-class resolver** — `device_class_resolver.py`. Precedence: brand/model rules
  (only way to detect closed-loop AID) > FDA product code > GMDN code > GMDN-name keyword >
  free-text fallback, with confidence grading. Works on GUDID records and FHIR-lite dicts.
- **Cardiac rhythm protocols** — magnet behavior (pacemaker async vs ICD therapy-suspension,
  leadless no-magnet-response), electrocautery precautions, pacer-dependence note, NBG code
  semantics, per-manufacturer magnet rates and 24-hr CRM support lines (HRS/ASA citations).
- **Guideline-backed checklists** — ordered per class per context with per-item citations,
  rendered with checkboxes at scan time.
- **Institutional override layer** — `overrides.py` + admin-editable
  `data/institution_overrides.json` (volume-mounted, no rebuild). Match by UDI-DI >
  manufacturer/brand > GMDN > device class; merge precedence override > brand fact > class
  protocol > raw GUDID, with per-field provenance. Read-only admin page at `/admin/overrides`.
  When an MRI override applies at scan time, an extra `Device.safety` coding
  (`mri-institutional`) is written to the FHIR Device.
- **Context scoping** — every protocol is scoped to surgery / MRI / EP-study; context
  selector in the UI, `?context=` on the API.
- **API** — `protocol` block in `POST /scan-to-chart` and `POST /api/lookup/udi`
  (which now also accepts bare numeric DIs); new `GET /api/protocol/by-di/<di>?context=`,
  `GET /admin/overrides`, `GET /api/admin/overrides`. Timeline devices carry
  `protocol_class`/`protocol_available` hints (resolver on FHIR fields only — no GUDID
  calls on chart load; full protocol lazy-loads on card expand via a 15-min TTL cache).
- **UI** — protocol panel in the scan result (`scan_to_chart.html`, now on the timeline
  theme) and as an expander on timeline device cards, both via shared
  `static/protocol_card.js`; provenance badges (Institution/Brand/Guideline/GUDID),
  severity-coded headline actions, `tel:` support lines, `diabetes` category color.
- **Tests & verification** — 27 pytest units in `services/gudid-core/tests/`;
  `scripts/verify_protocols.py` e2e against a running stack (all green 2026-06-10 with
  live-GUDID-confirmed DIs: Azure XT DR `00643169634589`, Percept PC `00763000519216`,
  SenTiva `05425025750405`, t:slim X2 Control-IQ `00389152000107`, MiniMed 780G
  `00199150047048`, Dexcom G7 `00386270003584`).

**Clinical content status:** every seeded fact/checklist row carries
`requires_verification=1` with citation placeholders; the UI shows an "unverified content"
strip and a persistent decision-support disclaimer. Phone numbers, magnet rates, FDA product
codes, and guideline citations MUST be clinician-verified before demo/pilot use.

**Known fixture note:** `00643169001763` is the Medtronic MOSAIC valve in live GUDID — the
`fhir-bridge` test fixture labeling it "Azure XT DR" is a mislabel (the cds-hooks comment is
correct).

### In Progress (Phase 6–8)

- [ ] **Phase 6: SMART App Launch v2** — EHR integration with OAuth2, patient context
  - [ ] `/.well-known/smart-configuration` endpoint
  - [ ] `/launch` endpoint with OAuth2 callback
  - [ ] FHIRCLIENT library integration
  - [ ] Testing against SMART Health IT launcher
  
- [ ] **Phase 7: CI Conformance Validation** — GitHub Actions for US Core validation
  - [ ] GitHub Actions workflow (`.github/workflows/validate.yml`)
  - [ ] Automated HL7 FHIR Validator integration
  - [ ] CI badge in README
  - [ ] Capability Statement generation and validation

- [ ] **Phase 8: Evaluation Harness** — Analytics for submission
  - [ ] `eval/analysis.ipynb` (Jupyter notebook)
  - [ ] SUS questionnaire (Google Form)
  - [ ] Usage metrics report generation
  - [ ] `make evaluation-report` Makefile target

---

## [Complete] Phases 0–5 (2026-05-19)

### Phase 0 — Scaffolding ✅

**Completed:** 2026-05-19

**Tasks:**
- [x] Created repo layout per Build.md §3
- [x] Moved existing Flask app into `services/gudid-core/`
- [x] Created stub READMEs in each service directory
- [x] Initialized `.gitignore`, `LICENSE`, `CITATION.cff`, `Makefile`
- [x] Updated `docker-compose.yml` for new build context
- [x] Verified: `docker-compose build && docker-compose up` → HTTP 200 on `/health`

**Key Commit:**
```
Phase 0: repo scaffolding — relocated Flask app, created service structure
```

---

### Phase 1 — Local FHIR Foundation ✅

**Completed:** 2026-05-19

**Tasks:**
- [x] Wrote `docker-compose.yml` with HAPI + Postgres + Synthea seeder
- [x] Configured `infrastructure/hapi/application.yaml`:
  - FHIR R4 (version 4.0.1)
  - US Core v8.0.1 IG loaded at startup
  - Validation enabled on write operations
  - CORS open for local dev
  - HAPI Tester UI enabled
  
- [x] Wrote `infrastructure/synthea/seed.sh`:
  - Generates 50 synthetic patients (+ 15 deceased)
  - Custom `perioperative_surgery.json` module for surgical histories
  - Posts bundles via HAPI's `$transaction` endpoint
  - Generates: 4,550 Encounters, 11,628 Procedures, 38,260 Observations, 1,000+ Devices

- [x] Added `make seed` and `make hapi` Makefile targets
- [x] Verified: `curl http://localhost:8080/fhir/Patient?_count=5` returns synthetic patients

**Acceptance Criteria Met:**
- HAPI R4 4.0.1 running (HAPI FHIR 8.8.0)
- US Core v8.0.1 validation active
- 65 Patients with surgical histories seeded
- Invalid Device resource rejected with HTTP 422
- All resources pass validation

**Key Commits:**
```
Phase 1: local FHIR foundation (HAPI R4 + US Core v8.0.1 + Synthea seed)
Infrastructure: configure HAPI with US Core validation
Synthea: custom perioperative module with surgical procedures
```

---

### Phase 2 — GUDID → US Core Device Mapper ✅

**Completed:** 2026-05-19

**Tasks:**
- [x] Implemented `services/fhir-bridge/gudid_to_uscore_device.py`:
  - Function: `map_to_device(gudid_record, patient_id=None, **production_ids) → dict`
  - Populates: `meta.profile`, `udiCarrier`, `manufacturer`, `deviceName`, `type`, `patient`, `safety`, `distinctIdentifier`, `modelNumber`, `serialNumber`, `expiration_date`, `manufacturing_date`
  - Handles: Multi-part UDI parsing, production identifiers, GMDN coding

- [x] Implemented `services/fhir-bridge/hapi_client.py`:
  - `create_device(device_resource) → str` (returns logical ID)
  - `get_patient_devices(patient_id) → list`
  - `link_to_procedure(device_id, procedure_id)` via JSON Patch
  - `validate(resource, profile_url) → bool`

- [x] Implemented `services/fhir-bridge/tests/validate_against_ig.py`:
  - HL7 FHIR Validator CLI wrapper
  - Validates Device resources against US Core v8.0.1 Implantable Device Profile

- [x] Wrote `services/fhir-bridge/tests/test_mapper.py`:
  - 17 test cases covering 5+ sample GUDID records
  - Tests UDI parsing, mapping, validation, HAPI POST
  - Uses `requests` library on Docker Compose network

**Acceptance Criteria Met:**
- `pytest services/fhir-bridge/tests` → **17 passed**
- 100% of generated Devices pass US Core validation (zero errors)
- Mapped Devices POST to HAPI → HTTP 201
- Devices retrievable via `Device?patient=...`
- US Core requires `Device.type` (min=1) → **mapper always emits one**

**Key Commits:**
```
Phase 2: GUDID -> US Core v8.0.1 Implantable Device mapper + HAPI client
fhir-bridge: implement mapper, tests, HL7 Validator integration
Fix: handle US Core Device.type cardinality (min=1)
```

---

### Phase 3 — Scan-to-Chart Workflow ✅

**Completed:** 2026-05-19

**Tasks:**
- [x] Implemented `services/gudid-core/scan_to_chart.py`:
  - `POST /scan-to-chart` endpoint
  - Input: UDI string, patient_id, optional procedure_id
  - Flow: parse UDI → GUDID lookup → map_to_device → POST to HAPI → return Device URL
  - Timing: <15 seconds end-to-end (achieved ~0.7–1.4s)

- [x] Created `services/gudid-core/templates/scan_to_chart.html`:
  - UDI text input (camera scan deferred, text entry works)
  - Patient picker dropdown (live from HAPI API)
  - "Document Device" button
  - Result panel showing created Device FHIR URL
  - error handling for not-found UDIs

- [x] Created `services/gudid-core/templates/timeline.html`:
  - Reverse-chronological device list
  - Cards show: name, manufacturer, model, UDI-DI, expiry, status
  - US Core and recall placeholder badges
  - Patient demographics header

- [x] Logging infrastructure: `eval/usage_logs/scans.csv`
  - Columns: timestamp, user, udi, device_identifier, patient_id, device_id, time_to_complete_ms, success
  - Tracks every scan for evaluation metrics

**Acceptance Criteria Met:**
- Abbott XIENCE stent (DI `08717648200274`) documented end-to-end in **~0.7–1.4 seconds**
- Device visible at HAPI: `http://localhost:8080/fhir/Device/90152`
- Patient timeline renders correctly
- Not-found UDIs fail gracefully with error message
- **Note:** PeriopUDI app moved to **host port 8090** (AirPlay holds 5000 on macOS)

**Key Commits:**
```
Phase 3: scan-to-chart workflow (UDI -> US Core Device in HAPI + timeline)
UI: implement scan form and timeline view
Logging: add usage metrics to eval/usage_logs/scans.csv
Fix: move gudid-core to host port 8090 (macOS AirPlay holds 5000)
```

---

### Phase 4 — Implant Timeline View ✅

**Completed:** 2026-05-19

**Tasks:**
- [x] Endpoint: `GET /patient/<id>/devices` → JSON API with Devices + recalls + demographics
- [x] Endpoint: `GET /patient/<id>/timeline` → rendered HTML chart
- [x] Visual design:
  - Full-width patient header (avatar, ID, sex, age, DOB)
  - Responsive device **grid** (not list)
  - Color-coded by device category (cardiac, neuro, ortho, vascular, ophthalmic, general)

- [x] Device cards display:
  - Device name, manufacturer, model
  - GMDN terminology (code + text)
  - UDI-DI, expiry date, status
  - **Safety chips:** MRI status, latex, single-use, sterile
  - US Core and recall badges
  - Empty state message when no devices

**Acceptance Criteria Met:**
- Patients with multiple devices render cleanly in grid
- XIENCE stent shows: cardiac category, MR Conditional, single-use, sterile chips (from GUDID)
- New scans appear immediately on reload
- Device safety attributes pulled directly from GUDID mapping
- **Note:** GUDID carries no implant date → cards show manufacture/expiry/documentation timestamp instead

**Key Commits:**
```
Phase 4: device-category color-coding + Device.safety (MRI/latex) on the chart
Patient chart: move avatar to the left with a person icon
Redesign patient chart: full-width patient header + avatar + device grid
Patient-first homepage: device search + Patient/Device cards + recent feed
Patients page: full-width Material-style data table + enriched demographics
Home: redesign with cozy plum/blush theme, wired to live data
Home: add standalone "Identify a Device" card
Home: widen to max-w-7xl and cool the neutrals
Patient chart: restyle to cooled burgundy theme
Patient chart: flat outlined device cards (drop heavy shadows)
Patient chart: flat cards — remove top category accent bar
Home: give the three workflow cards distinct pale colors
Home: editorial redesign (Fraunces hero, scanner mock, how-it-works, stats)
Home: replace narrative hero with tool-focused headline
```

---

### Phase 5 — FDA Recall Feed + CDS Hooks Service ✅

**Completed:** 2026-05-19

**Tasks:**
- [x] Implemented `services/cds-hooks/recall_poller.py`:
  - Runs on container startup (or `make recalls` on demand)
  - Fetches from openFDA `device/recall.json` endpoint daily
  - SQLite cache: `recalls.db` with columns (device_identifier, recall_number, classification, reason, recall_initiation_date, status, firm, source)
  - Pre-loads demo recalls for reproducible demos

- [x] CDS Hooks discovery: `GET /cds-services`
  - Returns valid CDS Hooks service catalog
  - One service: `recall-check` on `patient-view` hook

- [x] CDS Hooks execution: `POST /cds-services/recall-check`
  - Input: patient context with Devices
  - Fetches patient's Devices from FHIR server
  - Matches `udiCarrier.deviceIdentifier` against recall cache
  - Returns CDS Cards (summary, indicator, source)
  - Indicators: `critical` (Class I), `warning` (Class II/III)

- [x] Timeline UI integration:
  - Recall banner at top (red for critical, amber for warning)
  - Per-device RECALL badges (unmissable)
  - Empty cards array for clean patients

- [x] Demo data:
  - XIENCE `08717648200274` → Class II recall
  - MOSAIC `00643169001763` → Class I recall
  - Both marked `source=demo` for clarity

**Acceptance Criteria Met:**
- Discovery returns valid CDS Hooks catalog
- Recalled-device patient → warning Card (XIENCE/Class II)
- Critical device patient → critical Card (MOSAIC/Class I)
- Clean patient → empty `cards` array
- UI: red/amber banner + unmissable per-device RECALL badges
- **Note:** openFDA's recall feed isn't UDI-DI keyed. Demo uses curated entries. Production needs UDI-DI-indexed source.

**Key Commits:**
```
Phase 5: CDS Hooks recall surveillance + timeline recall badges
Recall poller: fetch openFDA daily + SQLite cache
CDS Hooks: implement discovery + execution endpoints
Timeline: add recall banner and device RECALL badges
```

**CDS Hooks Service Deployment:**
- **Port:** 8091 (mapped from internal 5001)
- **Database:** SQLite at `/app/data/recalls.db`
- **Startup:** Recall poller runs automatically
- **Status:** Ready for EHR integration (HAPI's built-in SMART launcher can call it)

---

## [2026-05-19] — Phases 0–5 Complete

**Status:** ✅ MVP complete, ready for Phase 6 (SMART launch)

**What's Working:**
1. FHIR foundation (HAPI R4 + US Core v8.0.1)
2. Synthetic patient cohort (50 alive, surgical histories)
3. GUDID-to-Device mapping (100% US Core validation)
4. Scan-to-chart workflow (<1.5s)
5. Patient timeline with device cards + safety profiles
6. Real-time FDA recall surveillance via CDS Hooks
7. Demo-ready UI (home, scan, timeline, device search)

**What's Next (Phases 6–10):**
- Phase 6: SMART App Launch v2 (EHR integration)
- Phase 7: CI conformance validation (GitHub Actions)
- Phase 8: Evaluation harness (analytics notebook)
- Phase 9: Clinical pilot (6–8 weeks with UAB Anesthesiology)
- Phase 10: AMIA submission & presentation (deadline: July 2026, present: Nov 10, 2026)

**Open Questions:**
- Which UAB assistant professors confirmed as co-authors?
- Does UAB have an Epic non-production sandbox for SMART testing?
- IRB non-human-subjects-research determination status?
- Hardware for OR pilot (barcode scanner vs. phone camera)?

---

## Recent Commit History (Last 20)

```
9cbd31b version 2 (protocol layer, 3D heart visual, IFU pipeline)
36e07c9 Home: replace narrative hero with tool-focused headline
5705dbf Home: editorial redesign (Fraunces hero, scanner mock, how-it-works, stats)
96d1818 Home: give the three workflow cards distinct pale colors
aa3f1bc Patient chart: flat cards — remove top category accent bar + all shadows
219b49b Patient chart: flat outlined device cards (drop heavy shadows)
ee826cc Patient chart: restyle to cooled burgundy theme, keep color-coding
ff24443 Patients page: full-width Material-style data table + enriched demographics
3d92608 Home: widen to max-w-7xl and cool the neutrals (keep burgundy accent)
4483dc2 Home: adopt cozy plum/blush design, wired to live data (no fabricated content)
05d8219 Home: add standalone "Identify a Device" card alongside Document/Patient
88b031e Patient-first homepage: device search + Patient/Device cards + recent feed
1a69b5e Phase 4: device-category color-coding + Device.safety (MRI/latex) on the chart
099b2c9 Patient chart: move avatar to the left with a person icon
040a7c5 Redesign patient chart: full-width patient header + avatar + device grid
fe2d693 Phase 5: CDS Hooks recall surveillance + timeline recall badges
ff82417 Fix parse_udi (top-level di) and wire UDI production identifiers into Device
ab0492d Phase 3: scan-to-chart workflow (UDI -> US Core Device in HAPI + timeline)
bcbb6eb Phase 2: GUDID -> US Core v8.0.1 Implantable Device mapper + HAPI client
f056d3a Phase 1: local FHIR foundation (HAPI R4 + US Core v8.0.1 + Synthea seed)
```

---

## Performance Metrics (As of 2026-05-19)

### Scan-to-Chart Latency
- **GUDID lookup:** ~1–2s
- **Map to US Core Device:** <500ms
- **POST to HAPI:** ~500ms–1s
- **Total (scan → stored):** **~0.7–1.4s** ✅ (target: <15s)

### Data Generated
- **Synthetic patients:** 65 (50 alive, 15 deceased)
- **Encounters:** 4,550
- **Procedures:** 11,628
- **Observations:** 38,260
- **Devices:** 1,000+

### Validation Results
- **US Core Device validation:** 100% pass (0 errors)
- **Terminology warnings:** Allowed (non-blocking)
- **HAPI validation:** HTTP 422 on invalid resources

---

## Known Issues & Workarounds

### Issue: macOS AirPlay holds port 5000
**Status:** ✅ Fixed (2026-05-19)
**Solution:** Moved gudid-core to port 8090

### Issue: openFDA recall feed not UDI-DI keyed
**Status:** ⚠️ Known limitation
**Workaround:** Use curated demo recalls for now
**Future:** Connect to UDI-DI-indexed recall source (commercial or custom)

### Issue: html5-qrcode camera scanning unreliable
**Status:** ⚠️ Deferred to Phase 10 (polish)
**Workaround:** Text input for UDI (fully functional)
**Future:** Improve mobile UX, add physical barcode scanner for OR

---

## Dependency Updates

### Recent Dependency Versions (as of 2026-05-19)

| Package | Version | Reason |
|---------|---------|--------|
| Flask | 3.0.0 | LTS, stable |
| Gunicorn | 21.2.0 | Production WSGI |
| Requests | 2.31.0 | HTTP client |
| HAPI FHIR | 8.8.0 | Latest (R4 4.0.1) |
| PostgreSQL | 16 | Latest LTS |
| Python | 3.9+ | (from base image) |

### Pinned in requirements.txt
All dependencies are pinned to specific versions for reproducibility.

---

## Future Work (Phases 6–10)

### Phase 6: SMART App Launch v2
- [ ] OAuth2 redirect flow
- [ ] Patient context persistence
- [ ] EHR launcher testing

### Phase 7: CI Conformance
- [ ] GitHub Actions workflow
- [ ] Automated US Core validation
- [ ] CI badge in README

### Phase 8: Evaluation Harness
- [ ] Jupyter notebook for metrics
- [ ] SUS questionnaire
- [ ] Usage report generation

### Phase 9: Clinical Pilot
- [ ] UAB Anesthesiology deployment
- [ ] 6–8 week pilot window
- [ ] SUS data collection
- [ ] Qualitative feedback

### Phase 10: AMIA Submission
- [ ] Abstract (1,000 chars)
- [ ] Rationale (3,500 chars)
- [ ] Design (7,000 chars)
- [ ] Evaluation (3,500 chars)
- [ ] 3-minute demo video
- [ ] Presentation (8 minutes, Nov 10, 2026)

---

## Contributing

To add to this changelog, follow the format:
- **[Date] — Brief summary** (if milestone)
- **### Phase X — Title** (for major phases)
- **### Feature/Fix Name** (for smaller work)
- Include: **Completed:** date, **Tasks:** checklist, **Key Commits:** git messages

---

*Last updated: 2026-06-23*  
*Phases 0–5 complete. Periop protocol layer, 3D heart visual, and IFU pipeline (GUDID + Google Custom Search) built and auto-wired into scan-to-chart. Pipeline fires in background on every scan. Next: verify Aveir™ IFU extraction in live logs, then Phase 6 (SMART launch). Target submission: July 2026, presentation: November 10, 2026.*
