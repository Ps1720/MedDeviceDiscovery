# Code Flow

How a request moves through PeriopUDI. Companion to [`architecture.md`](../architecture.md),
which covers the system diagram and deployment topology; this document covers the code.

---

## Module map (`services/gudid-core/`)

| Module | Responsibility |
|---|---|
| `app.py` | Flask routes, request wiring, background-job kickoff |
| `config.py` | Environment configuration (single source of truth for settings) |
| `gudid_service.py` | FDA AccessGUDID client — UDI parsing and device lookup |
| `scan_to_chart.py` | Orchestrates the scan workflow; owns FHIR target resolution |
| `smart_launch.py` | SMART App Launch v2 — EHR/standalone launch, OAuth2 + PKCE |
| `protocol_service.py` | Assembles the perioperative protocol block for a device |
| `protocol_db.py` / `protocol_seed.py` | Protocol knowledge base (SQLite) and its seed data |
| `device_class_resolver.py` | GUDID record → one of 11 device classes |
| `overrides.py` | Institution-specific annotations layered over GUDID |
| `implant_sites.py` | SNOMED-coded implant-location extension |
| `ifu_finder.py` | Locates a manual: local library → curated seed → GUDID → EUDAMED → web |
| `ifu_extractor.py` | Downloads/reads the PDF, filters pages, calls the LLM |
| `ifu_validator.py` | Cross-checks extracted facts against GUDID |
| `pathway_engine.py` | Resolves the perioperative pathway from case parameters |
| `auth.py` / `auth_routes.py` | Access gate and local sign-in |
| `ifu_pipeline.py` | Drives find → extract → validate → store; CLI for clinician sign-off |
| `ifu_store.py` | Persists extracted facts with provenance |
| `qr_generator.py` / `database_setup.py` | QR codes and their local catalogue |
| `llm_service.py` | Free-text device Q&A |

Shared library, mounted into the image from `services/fhir-bridge/`:

| Module | Responsibility |
|---|---|
| `gudid_to_uscore_device.py` | GUDID record → US Core v8.0.1 `Device` resource |
| `hapi_client.py` | Thin FHIR REST client (create/update/read/validate) |

---

## Flow 1 — Scan to chart

The primary workflow. `POST /scan-to-chart` with `{udi, patient_id}`.

```
app.scan_to_chart_submit
  └─ scan_to_chart.document_device(udi, patient_id, …)
       1. _resolve_di(udi)                    parse UDI → DI + production identifiers
       2. gudid_service.get_device_from_gudid(di)          FDA GUDID lookup
       3. protocol_service.build_protocol_block(record)    advisory — never blocks
            └─ device_class_resolver.resolve_device_class
            └─ overrides / brand facts / class defaults    (layered, see Flow 3)
       4. gudid_to_uscore_device.map_to_device(...)        → US Core Device
       5. _apply_institutional_mri_safety(device, protocol)
       6. implant_sites.upsert_implant_extension(...)      cardiac rhythm devices only
       7. HapiClient.create_device(device)                 → FHIR server
            └─ on rejection, retry once without the implant extension
       8. HapiClient.link_to_procedure(...)                if procedure_id given
       9. background thread: ifu_pipeline (Flow 2)         if not already attempted
      10. _log_scan(...)                                   → eval/usage_logs/scans.csv
```

Two design rules hold throughout:

- **Enrichment is advisory.** Protocol assembly, implant-site coding, and IFU extraction
  are each wrapped so a failure degrades the result rather than blocking documentation of
  the device.
- **Documentation is the transaction.** Only steps 4–7 must succeed for the scan to count.

### Where the FHIR writes go

`scan_to_chart` does not hardcode a server. `_fhir_base()` / `_fhir_headers()` read a
`contextvars` override:

- **No SMART session** → local HAPI (`FHIR_BASE_URL`), no auth header.
- **SMART session active** → the EHR-launched server, with the OAuth2 bearer token.

`app.py`'s `before_request` hook installs the override per request and `teardown_request`
clears it. Background threads deliberately do **not** inherit it, so a token never leaks
across requests.

---

## Flow 2 — IFU pipeline

Finds the manufacturer's manual, reads it, and stores structured perioperative facts.
Runs in a background thread after a scan, or on demand from the UI.

```
ifu_pipeline.run_pipeline(manufacturer, brand, model, di, ifu_url=None)
  ├─ ifu_finder.find_ifu(...)              (skipped when a URL is supplied)
  │    Step -1  _try_local        offline library, data/manuals/    ← no network
  │    Step  0  _try_curated      data/ifu_seed.json
  │    Step  1  _try_gudid_v3/v2  GUDID labeling URLs
  │    Step  2  _try_eudamed      EU registry
  │    Step  3  _try_manufacturer_site
  │    Step  4  _try_fcc          fcc.report filing scraper
  │    Step  5  _try_bing / _try_google_cse / _try_duckduckgo
  ├─ ifu_extractor.extract_from_url(url)
  │    _download_pdf              http(s) | file:// | /manuals/<file> | local path
  │    _extract_relevant_text     pdfplumber; pages RANKED by weighted keyword
  │                               density, not document order, then restored to
  │                               document order (a 312-page manual otherwise
  │                               spends the whole budget on its contents page)
  │    _call_llm                  constrained JSON schema, ≤12k chars
  │    _drop_ungrounded           every fact must point at evidence in the source
  │                               text; numbers verbatim, claims need their domain
  │                               terms. Unsupported facts are discarded.
  ├─ ifu_validator                cross-check against the GUDID record
  │                               conflicts are withheld from display, not shown silently
  └─ ifu_store                    persist with provenance + requires_verification=1
```

Every extracted fact stays `requires_verification` until a clinician signs off:

```bash
python ifu_pipeline.py --verify <id> --by "Dr. Name"
```

**The offline library is the reliable path.** `data/manuals/` holds clinician-facing PDFs
committed to the repo with `index.json` recording provenance and brand-match patterns.
Steps 4–5 depend on third-party sites that now block automated requests, so covered
devices resolve at Step -1 with no network call.

---

## Flow 3 — Protocol assembly

`GET /api/protocol/by-di/<di>` and the enrichment inside Flow 1.

```
protocol_service.build_protocol_block(gudid_record)
  ├─ device_class_resolver.resolve_device_class(record)   → class + module
  │     11 classes: pacemaker, leadless_pacemaker, icd, crt_p, crt_d,
  │                 vns, dbs, scs, insulin_pump, cgm, closed_loop
  └─ for each fact, first source wins:
        1. institutional override        overrides.py / data/institution_overrides.json
        2. brand fact from the manual    ifu_store (badge: "Brand")
        3. device-class default          protocol_db, seeded by protocol_seed
        4. raw GUDID field
```

Protocol content is **reference data, not patient data** — it is re-derived at render
time and never written into a FHIR resource. The one exception is the clinician-confirmed
implant site, which is a `Device` extension because it records a clinical decision.

---

## Flow 3b — Case-parameter pathway

`GET /api/pathway?class_key=&surgical_site=&cautery=&pacing_dependence=`

```
pathway_engine.resolve(class_key, answers)
  ├─ load data/pathway_rules.json      rules as data: condition, output, citation
  ├─ _resolve_input per question       an unknown answer falls to the conservative
  │                                    value and is recorded as an assumption
  ├─ match the site × cautery matrix   no matching cell also fails conservative
  └─ filter escalated_actions          by device class, and by answers where the
                                       action declares a `when` clause
```

Returns the pathway, a `because` string naming the inputs that selected it, the
assumptions applied, and the actions. Rendered above the checklist; no checklist
items are hidden, because which items drop out is a clinical judgement.

Pacing dependence is never inferred from the UDI or the programmed mode: devices
are commonly programmed on-demand even in patients with no intrinsic escape
rhythm, so an on-demand mode does not exclude dependence.

---

## Flow 4 — Recall surveillance

```
app.api_patient_devices  →  scan_to_chart.get_patient_chart(patient_id)
  ├─ get_patient_summary(patient_id)          demographics
  ├─ HapiClient.get_patient_devices(...)      the device timeline
  └─ get_patient_recall_cards(patient_id)
       POST {CDS_HOOKS_URL}/cds-services/recall-check
         { hook: "patient-view", context: {patientId}, fhirServer: <current FHIR base> }
       → services/cds-hooks reads the patient's devices from that server,
         matches each UDI-DI against its cached openFDA recall table,
         returns Class I/II/III cards (critical / warning / info)
```

`fhirServer` tracks the same target as the rest of the request, so recall checking keeps
working inside an EHR-launched session. Recall lookup is advisory: a failure logs and
returns no cards rather than breaking the chart.

---

## Flow 5 — SMART App Launch

```
EHR launch:   GET /launch?iss=<fhir base>&launch=<opaque>
standalone:   GET /launch/standalone
   └─ _discover(iss)       .well-known/smart-configuration,
   │                        falling back to CapabilityStatement oauth-uris
   └─ 302 → authorization_endpoint  (PKCE S256 challenge, state, aud)

GET /smart/callback?code=…&state=…
   └─ POST token_endpoint  (code + PKCE verifier, public client, no secret)
   └─ tokens → in-process store; only a random handle goes in the session cookie
   └─ 302 → /scan-to-chart?patient_id=<patient>
```

Tokens are held server-side because SMART access/refresh JWTs run 700–1500 characters
each; both in a signed cookie exceeds the 4093-byte browser limit, and browsers drop an
oversized cookie silently. The handle keeps the cookie under 200 bytes.

This assumes a single application process (the container runs gunicorn with
`--workers 1`). Scaling out requires moving the store to Redis or a database table.

---

## Request-scoped state

| Mechanism | Set by | Cleared by | Carries |
|---|---|---|---|
| `scan_to_chart._fhir_override` | `app.before_request` | `app.teardown_request` | FHIR base URL + auth headers |
| Flask `session` | `smart_launch.callback` | `/smart/logout` | SMART session handle |
| `smart_launch._TOKEN_STORE` | `smart_launch.callback` | logout, or 12h TTL | access/refresh tokens, patient context |

---

## Data stores

| Store | Location | Contents |
|---|---|---|
| HAPI FHIR + Postgres | container | `Device`, `Patient`, `Procedure`, `Encounter` — source of truth |
| `data/protocols.db` | SQLite | protocol knowledge base, brand facts, IFU records |
| `qr_codes.db` | SQLite | generated QR-code catalogue |
| `services/cds-hooks/data/recalls.db` | SQLite | cached openFDA recall feed |
| `data/manuals/` | files | offline manual library + `index.json` |
| `data/pathway_rules.json` | file | versioned pathway rules, reviewable as data |
| `eval/usage_logs/scans.csv` | CSV | scan telemetry for evaluation |
