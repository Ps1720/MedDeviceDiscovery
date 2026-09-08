# PeriopUDI Changelog

All notable changes to the PeriopUDI project are documented in this file. This changelog tracks implementation progress phase by phase.

---

## [Unreleased]

---

### Added — Case-parameter pathway engine; extraction integrity (2026-09-08)

**Pathway engine.** Three case questions — surgical field above the umbilicus,
monopolar cautery expected, pacing dependence — select one perioperative pathway
for cardiac devices. Requested directly by the clinical collaborators.

- `data/pathway_rules.json` — rules as versioned data, not code: condition,
  output text and citation per rule, reviewable without reading Python. Every
  rule ships `requires_verification: true`; the collaborator wrote "if surgery
  expected to extend above the umbilicus and monopolar cautery use expected, then
  xxxxxx" and left the consequent blank, so this content is a draft awaiting them.
- `pathway_engine.py` + `GET /api/pathway`, `GET /api/pathway/inputs`.
- **Unknown is not "No".** An unanswered question resolves to the conservative
  branch and the result reports the assumption. Every result states the inputs
  that produced it, so a wrong recommendation can be traced to the wrong input.
- Pacing dependence defaults to "not determined" and is never inferred.
- The escalated branch splits by device type: ICD/CRT-D suspend tachytherapy and
  place external pads; pacemakers arrange asynchronous pacing when dependent *or
  undetermined*.
- Rendered in the protocol card above the existing checklist. No checklist items
  are hidden — deciding which items drop out is a clinical judgement the
  collaborators have not yet made.

**Extraction integrity — the model fabricated a fact.** Asked to extract from the
Medtronic Azure manual, the model returned an electrocautery recommendation for a
document containing zero occurrences of "electrocautery", "cautery" or
"tachytherapy". It was stored and displayed badged "Extracted from IFU", beside
genuinely extracted facts such as the magnet rate of 65.

- **Grounding check** (`ifu_extractor._is_grounded`): numeric claims must appear
  verbatim in the source; textual claims must carry the domain terms they depend
  on. Unsupported facts are dropped. Short abbreviations match on word boundaries
  — as a bare substring "esu" matches "result" and "resume", which let the
  fabricated cautery text pass the first version of the check.
- Audited all stored LLM facts against their manuals; removed 2 fabricated.
- **Page ranking.** Pages were taken in document order and truncated at 12,000
  characters, so a 312-page manual spent the whole budget on its table of
  contents. Pages are now ranked by weighted keyword density, then restored to
  document order. Weak terms ("therapy", "support") score near zero — they
  matched 212 of 312 pages, which is noise rather than a filter.
- **Rate-unit awareness.** Medtronic writes "65 min-1", never "bpm", so the
  magnet-rate page ranked 7th and fell outside the budget. Ranking now rewards a
  number adjacent to any rate unit, more so when "magnet" is on the same page.

**Fixed**

- `no_facts` was unreachable: `ifu_validator` returned "No extracted facts to
  validate" as a *conflict*, so every device whose manual could not be found was
  recorded as a conflict. Conflict suppression appeared to fire constantly when
  it had never fired at all. 4 historical records relabelled.
- Re-seeding wiped LLM-extracted facts. `brand_facts` is in `CONTENT_TABLES`, so
  bumping `SEED_VERSION` destroyed the extracted Azure magnet rate of 65 and left
  the generic seeded Medtronic 85 bpm in its place — a value the Azure manual
  explicitly contradicts. Re-seed now deletes only `source != 'llm'`.
- Manufacturer aliases: GUDID files Abbott's cardiac devices under "ST. JUDE
  MEDICAL, INC.", so the Gallant matched no manual. `manufacturer_patterns` now
  accepts a list; added St. Jude/SJM and Guidant aliases.
- Citations beginning "VERIFY" carried two meanings — a missing citation and a
  real source to check — rendered identically, so sound content read as invented.
  Placeholders now render as nothing; real sources render as citations.
- Pacing-dependence guidance corrected per collaborator feedback: an on-demand
  programmed mode does not exclude dependence.
- Support-contact numbers are all hand-entered and unverified; the card now says
  so beside the number.

**Camera scanning**

- Barcode scanning moved into the scan-to-chart UDI field. `BarcodeDetector`
  where available, `@zxing/browser` as fallback — both handle **GS1 DataMatrix**,
  which is what implant packaging actually carries; a 1D-only reader is close to
  useless on a real device box.
- Scanned payloads are normalised: PeriopUDI's own QR codes encode a URL so a
  plain phone camera opens the device page, and GS1 Digital Link encodes
  `https://id.gs1.org/01/<GTIN>`. Both reduce to the identifier.
- `getUserMedia` requires a secure context, so the camera is blocked over plain
  HTTP on a LAN address. The button says so rather than failing silently.

**SMART navigation.** The launched patient's chart lives on the EHR's FHIR
server, so they never appear in the local patient list and were unreachable once
you navigated away. The header context chip, and the patient name in the scan
banner, now link to the chart; the timeline states which server it is reading.

---

### Added — Offline manual library; IFU finding no longer depends on the open web (2026-09-07)

**The curated IFU path was silently broken.** Every `ifu_url` in `data/ifu_seed.json`
points at fcc.report, and fcc.report now returns **403 to every automated request**
(verified: all 12 direct PDF URLs). The fccid.io mirror serves, but IP-blocks after
roughly six fetches. So the "zero-API-key IFU finding for 13 device families" claimed
on 2026-06-24 no longer worked at all.

Fixed by committing the manuals to the repo:

- **`services/gudid-core/data/manuals/`** — 12 clinician-facing PDFs (~27 MB), each
  downloaded from the manufacturer, FDA CDRH, or an FCC filing, with `index.json`
  recording label, brand-match patterns, category, page count, `source_url` and
  provenance note. Covers Medtronic Azure, Boston Scientific RESONATE ICD /
  ImageReady MRI / CIED magnet response, Abbott MRI-Ready + scan checklist,
  Nevro Senza HFX (MRI guidelines + implant manual), Tandem t:slim X2 Control-IQ,
  and LivaNova VNS (physician's manual + MRI guidelines + surgical procedure).
- **`ifu_finder`** — new Step -1 `_try_local` ahead of the curated seed, plus
  `find_local_manual` / `list_local_manuals`. Ranking is by an explicit
  `priority` field (1 = primary clinician manual, 3 = supplement) so a 2-page
  checklist can't beat the 312-page physician's manual just by matching a longer
  brand string.
- **`ifu_extractor._download_pdf`** — now accepts a local path, a `file://` URL, or
  the canonical `/manuals/<file>` form, resolving the last against the library
  directory (with a traversal guard) instead of making the app HTTP-request itself.
  Also rejects non-PDF payloads up front, which is what a 403 HTML error page is.
- **Routes** — `GET /manuals/<file>` serves a manual (PDF-only, traversal-guarded),
  `GET /api/ifu/suggest?manufacturer=&brand=` returns the best library match, and
  `GET /api/manuals` lists the library.
- **UI** — the "paste manufacturer PDF URL" box on both the patient timeline and the
  scan-to-chart result now **pre-fills from the library** and links the matched manual
  by name and page count, instead of asking a clinician to go hunting mid-case.
- **`scripts/fetch_manuals.py`** — `--list`, `--verify` (opens every PDF, checks page
  counts), and a re-download mode driven by `index.json`. Hosts known to block bots are
  named explicitly rather than retried.

Verified: all 12 PDFs open with the expected page counts; `/manuals/` rejects
traversal, non-PDF and missing files (404); extraction from the local Boston Scientific
magnet document yields 47 magnet references in the LLM-bound text.

---

### Added — SMART App Launch v2 (Phase 6) (2026-09-07)

PeriopUDI is now EHR-launchable. New blueprint `services/gudid-core/smart_launch.py`
(registered in `app.py`), public client + PKCE, `requests` + stdlib only — no
`fhirclient` dependency.

- **Routes**: `GET /launch` (EHR launch, `iss` + `launch`), `GET /launch/standalone`
  (patient picker at the auth server), `GET /smart/callback` (code → token +
  patient context, stored in the Flask session), `GET /smart/status`,
  `GET|POST /smart/logout`, `GET /.well-known/smart-configuration`.
- **Auth server discovery**: `.well-known/smart-configuration` with a
  CapabilityStatement `oauth-uris` fallback. Verified against
  `https://launch.smarthealthit.org/v/r4/fhir`.
- **Scopes** (minimum-necessary, `Config.SMART_SCOPES`): `launch openid fhirUser
  profile patient/Patient.read patient/Device.read patient/Device.write
  patient/Procedure.read`. Standalone launch swaps `launch` → `launch/patient`.
- **FHIR retargeting**: `scan_to_chart` gained `set_fhir_context` /
  `clear_fhir_context` (a `contextvars` override). `app.py`'s `before_request`
  hook installs the launched FHIR base + bearer token when a SMART session is
  live; otherwise everything keeps talking to the local HAPI server. `HapiClient`
  gained an `extra_headers` arg to carry the token.
- **UI**: scan-to-chart shows a "Launched from EHR" banner and locks the patient
  picker to the launch context; otherwise shows a "Connect to an EHR (SMART)"
  link. Callback redirects to `/scan-to-chart?patient_id=<patient>`.
- **Token storage**: SMART access/refresh tokens are JWTs of ~700–1500 chars each;
  putting both in the signed session cookie pushes it past the 4093-byte browser
  limit, and browsers drop an oversized cookie *silently* (OAuth appears to
  succeed, then the app has no session). The cookie therefore holds only a random
  handle and the tokens live in an in-process store. Measured: cookie is 188 B
  regardless of token size. **Assumes one app process** — the Dockerfile runs
  gunicorn `--workers 1`; use Redis/a DB table before scaling out.
- **Recall surveillance follows the launch**: `get_patient_recall_cards` now sends
  `fhirServer: _fhir_base` so the CDS Hooks service reads devices from whichever
  server holds them (local HAPI normally, the launched server during a SMART
  session). Previously it always pointed at local HAPI, so recall cards would have
  come back empty during an EHR-launched demo.
- **Config**: `SECRET_KEY` is now active in `config.py` (was commented out) — it
  signs the session that carries the OAuth state/PKCE verifier/session handle. New
  env: `APP_BASE_URL`, `SMART_CLIENT_ID`, `SMART_DEFAULT_ISS` (see `.env.example`
  and `docker-compose.yml`).
- **Hardening**: `next=` is restricted to same-site absolute paths (open-redirect);
  patient id is URL-encoded into the post-login redirect; the callback rejects a
  token response with no `access_token`; `.well-known` no longer advertises
  `authorize-post`, which the client does not implement.
- **Not yet**: full browser OAuth round-trip is a manual test; Epic/Cerner
  sandbox registration pending.

---

### Current Status — 2026-06-24

**Where we are:** The IFU pipeline now finds device manuals without any external API keys
for 13 of the most common perioperative device families — hitting a curated FCC filing
table first (instant, no network call), then scraping fcc.report directly to pick the
document labeled "User Manual" specifically (not test reports or SAR reports). The scan
page now shows live step-by-step status messages while the AI reads the PDF, and
automatically switches to a success or conflict card when done. The pipeline no longer
shows the manual PDF input form when a device has already been extracted.

**What's wired up:**
- **Curated seed table** (`data/ifu_seed.json`) — 13 device families with confirmed FCC
  User Manual PDF URLs: Medtronic Azure S/XT, Cobalt/Crome, Percepta/Serena/Solara,
  Micra; Abbott/SJM ICD family; Boston Scientific CRM 3300 series; Nevro HFX;
  Dexcom G6/Stelo; Omnipod 5; Medtronic Guardian Link; Tandem t:slim
- **Zero-API-key IFU finding** for all seeded devices — instant local lookup
- **FCC targeted scraper** — when Bing finds the filing page, scrapes fcc.report HTML to
  pick specifically the "User Manual" document (not the first PDF, which may be a test
  report or SAR report)
- **EUDAMED groundwork** — queries EU device registry for cross-validation; will return
  IFU URLs automatically when the EU eIFU mandate is enforced (phasing in May 2026)
- **Live scan-page status strip** — step-by-step messages ("Finding PDF…", "Downloading…",
  "AI reading clinical content…") poll every 6 s and replace the spinner with a green
  success card showing the facts count when extraction completes
- **Correct timing** — message now says 2–4 minutes (was wrong "30–60 seconds")
- **Already-extracted devices** — scan page shows "Facts already extracted — N clinical
  facts on file" instead of the manual PDF input form

**Immediate next steps:**
1. Test with a new device not yet in the DB to see the live status strip in action
2. Go to patient timeline after extraction to see the quick-facts strip (magnet rate, MRI, support phone)
3. Clinician review and sign-off (`python ifu_pipeline.py --verify <id> --by "Dr. ..."`)
4. Phase 6: SMART App Launch

---

### Added — IFU Finder: Curated Seed Table + FCC Targeted Scraper + EUDAMED (2026-06-24)

Removes the need for any external API key to find manuals for the 13 most common
perioperative device families. Adds a hand-verified local lookup table and a direct
fcc.report scraper that picks the "User Manual" document specifically.

**`data/ifu_seed.json`** — new curated seed table. Each entry stores the FCC grantee ID
and confirmed direct PDF URL for the physician manual, verified against the fcc.report
filing page. Covers:

| Category | Devices |
|---|---|
| Pacemakers | Medtronic Azure S/XT SR/DR, Cobalt/Crome XT SR/DR/CRT-D, Percepta/Serena/Solara CRT-P, Micra leadless |
| ICDs | Abbott/SJM family (Gallant, Ellipse), Boston Scientific CRM 3300 series |
| Neurostimulators | Nevro HFX IPG3000 (prescriber manual selected) |
| CGM | Dexcom G6, Dexcom Stelo |
| Insulin pumps | Omnipod 5, Medtronic Guardian Link (MiniMed 600/700 series), Tandem t:slim |

**`ifu_finder.py` — three new functions:**

- **`_try_curated(manufacturer, brand, model)`** — loads the seed JSON once (cached in
  memory), matches by manufacturer + brand keyword substring (case-insensitive), returns
  the PDF URL instantly with no network call. Logged with FCC ID for traceability.

- **`_try_fcc(manufacturer, brand, model)`** _(enhanced)_ — now a two-step process:
  (1) Bing `site:fcc.report/FCC-ID` to find the filing index page;
  (2) scrape that page's HTML table to find the row labeled "User Manual" or
  "Users Manual" specifically — not the first PDF on the page, which may be a
  test report, SAR report, or cover letter. Falls back to the filing URL if scraping
  fails.

- **`_scrape_fcc_filing(url)`** — shared helper; given any `fcc.report/FCC-ID/XXXXX`
  page, parses `<td><a>document name</a></td>…<td><a href="…pdf">` table rows and
  returns the User Manual PDF URL. Tested on LF5BLEIMPLANT (Azure XT DR): correctly
  returns `3357083.pdf` (User Manual, 349 KB) not `3357077.pdf` (Test Report, 1.8 MB).

- **`_try_eudamed(di)`** — queries EUDAMED EU device registry API for the device UUID
  and manufacturer. Currently returns `None` for URL (EUDAMED API has no IFU document
  fields yet — the EU eIFU mandate is phasing in through May 2026). Will return IFU URLs
  automatically when EUDAMED adds them. Already wired into the priority chain.

**Updated lookup priority chain:**
```
curated → GUDID v3 → GUDID v2 → EUDAMED → manufacturer_site → FCC targeted
  → Bing → Google CSE → DuckDuckGo → hint_only
```

**`scan_to_chart.py`** — when `_ifu_already_attempted()` is True (device already in DB),
now looks up the existing IFU record status and returns it as `ifu_pipeline` so the scan
page shows the right UI state instead of falling back to the manual URL input form.

**`scan_to_chart.html`** — scan page now shows live extraction progress:
- Step-by-step messages update every 6 s while the pipeline runs
- Timing corrected to 2–4 minutes (was wrong "30–60 seconds")
- On completion: green success card with facts count; "View facts on timeline →" button
  turns green
- On conflict: amber warning card explaining review needed
- On failure: falls back to manual PDF URL input form
- Already-extracted devices: shows "Facts already extracted — N clinical facts on file"
  card immediately (fetches real count from `/api/ifu/status`)

**`/api/ifu/status`** — now counts `brand_facts` rows directly from the DB so
`brand_facts_count` is always accurate (was returning `None` before because the column
wasn't stored in `ifu_records`).

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

Implements all five requested clinical features on a shared foundation: a UDI scan now
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

- [x] **Phase 6: SMART App Launch v2** — EHR integration with OAuth2, patient context
  - [x] `/.well-known/smart-configuration` endpoint
  - [x] `/launch` (EHR) + `/launch/standalone` + `/smart/callback` OAuth2 code flow
  - [x] Public client + PKCE (S256), no client secret — `requests` + stdlib, no `fhirclient` dep
  - [x] Minimum-necessary scopes (`Config.SMART_SCOPES`)
  - [x] Active SMART session retargets `scan_to_chart` FHIR reads/writes at the launched server (bearer token); no session → local HAPI
  - [x] Discovery + authorize redirect verified against the SMART Health IT sandbox; full browser round-trip pending manual test
  - [ ] Register redirect URL with Epic/Cerner sandboxes
  
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
- [x] Created the service-oriented repo layout
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

*Last updated: 2026-06-24*  
*Phases 0–5 complete. Periop protocol layer, 3D heart visual, and IFU pipeline fully wired. Pipeline now finds manuals for 13 device families with zero API keys via curated FCC seed table. Scan page shows live 2–4 min extraction progress and auto-updates on completion. Next: clinical verification of extracted facts, then Phase 6 (SMART launch). Target submission: July 2026, presentation: November 10, 2026.*
