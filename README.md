# PeriopUDI

**SMART-on-FHIR perioperative device documentation with real-time FDA recall surveillance.**

A clinician scans the UDI barcode on an implanted device (pacemaker, ICD, insulin pump,
neurostimulator, stent, …) and within seconds PeriopUDI:

1. Looks the device up in the FDA's official **GUDID** registry.
2. Maps that record into a **US Core v8.0.1**–conformant FHIR `Device` resource and stores
   it in the patient's chart on a local HAPI FHIR server.
3. Surfaces **perioperative protocol guidance** for that device — magnet behavior, MRI
   conditionality, electrocautery precautions, 24-hour support contacts — with a 3D heart
   visualization and magnet-response simulation for cardiac devices.
4. Checks the device against the FDA recall feed via **CDS Hooks** and raises a real-time
   alert if it has been recalled.
5. Automatically **finds and reads the manufacturer's IFU** (Instructions For Use) PDF to
   extract structured clinical facts, cross-validated against GUDID.

A 30-second barcode scan becomes a USCDI-conformant, GUDID-validated, recall-aware
implantable device record — at the point of care, in the OR.

Developed in the Department of Anesthesiology, University of Alabama at Birmingham.

**Documentation:** [Architecture](architecture.md) · [Code flow](docs/code-flow.md) ·
[Development progress](docs/progress.md)

---

## Architecture

Four Docker services plus a shared mapping library:

| Service | Role | Port |
|---|---|---|
| **`hapi`** | HAPI FHIR R4 server — store for `Device` / `Patient` / `Procedure`, validated against US Core v8.0.1 | 8080 |
| **`gudid-core`** (`services/gudid-core`) | Flask app — scan workflow, patient timeline, protocol cards, IFU pipeline, admin | 8090 |
| **`cds-hooks`** (`services/cds-hooks`) | CDS Hooks recall-surveillance service, fires on `patient-view` | 8091 |
| **`hapi-db`** | PostgreSQL 16 — persistence for HAPI | 5432 (internal) |
| **`fhir-bridge`** (`services/fhir-bridge`) | Library, not a service — GUDID → US Core `Device` mapper + HAPI client, baked into the `gudid-core` image | — |

`synthea-seed` is a one-shot container (behind the `seed` profile) that generates
synthetic patients and loads them into HAPI, so there is no PHI and no IRB burden during
development.

```
UDI scan ─▶ GUDID lookup ─▶ fhir-bridge (US Core map) ─▶ HAPI ─▶ patient timeline
                     │                                             │
                     └─▶ protocol layer (3D heart, magnet sim)     └─▶ CDS Hooks recall check
                     └─▶ IFU pipeline (find PDF ─▶ extract ─▶ validate vs GUDID ─▶ store)
```

---

## Quick start (Docker)

### Prerequisites

- Docker + Docker Compose
- An OpenAI-compatible API key (or the UAB proxy) for the AI assistant — optional; the
  scan, FHIR, protocol, and recall paths all work without it

### 1. Configure environment

```bash
cp.env.example.env
```

Edit `.env`:

| Var | Required | Notes |
|---|---|---|
| `OPENAI_API_KEY` | for AI assistant | OpenAI key, or a UAB-proxy key |
| `OPENAI_API_BASE` | optional | defaults to `https://api.openai.com/v1`; set for Azure / UAB proxy / local LLM |
| `OPENAI_MODEL` | optional | defaults to `gpt-4o-mini` |
| `HOST_IP` | for phone scanning | your machine's LAN IP, so QR codes resolve from a phone. `ifconfig \| grep "inet " \| grep -v 127.0.0.1` |
| `GOOGLE_API_KEY`, `GOOGLE_CSE_ID` | optional | Google Custom Search for the IFU finder; the curated seed table + FCC scraper + DuckDuckGo cover most cases without it |
| `SECRET_KEY` | optional | Flask session key; `python -c "import secrets; print(secrets.token_hex(32))"` |
| `FLASK_ENV` | optional | `production` (default) or `development` |
| `PATIENT_COUNT` | optional | Synthea patient count for `make seed` (default 50) |

### 2. Bring up the stack

```bash
make up            # docker-compose up --build (foreground, logs attached)
# or
make demo          # down, then rebuild and start detached
```

- PeriopUDI core: <http://localhost:8090>
- HAPI FHIR: <http://localhost:8080/fhir>
- CDS Hooks health: <http://localhost:8091/health>

### 3. Seed synthetic patients (optional)

```bash
make hapi          # bring up just HAPI + Postgres, wait until healthy
make seed          # generate Synthea patients and load them into HAPI
```

### 4. Refresh the recall cache (optional)

```bash
make recalls       # seeds demo recalls + best-effort openFDA pull
```

### Stop

```bash
make down
```

---

## Make targets

| Target | Does |
|---|---|
| `make up` | Full stack, `docker-compose up --build` |
| `make demo` | `down` then rebuild + start detached |
| `make hapi` | Just HAPI + Postgres, blocks until `/fhir/metadata` responds |
| `make seed` | Synthea → HAPI (needs HAPI healthy first) |
| `make recalls` | Refresh the device-recall cache in the `cds-hooks` service |
| `make down` | Stop the stack |
| `make test` | Run service test suites |
| `make validate` | Validate FHIR output against US Core v8.0.1 |

---

## Running `gudid-core` without Docker

Fastest loop for UI / route work. There is no committed project venv; use a throwaway one.

```bash
python3 -m venv.venv
.venv/bin/pip install -r services/gudid-core/requirements.txt pytest

cd services/gudid-core
PYTHONPATH=../fhir-bridge FLASK_ENV=development../../.venv/bin/python app.py
```

App serves on port 8090 (`PORT` env / `Config.PORT`). FHIR, recall, and IFU features
degrade gracefully when HAPI and `cds-hooks` aren't running.

### Hot-reload container alternative

```bash
docker-compose --profile dev up gudid-core-dev
```

Mounts `services/gudid-core` (and the two `fhir-bridge` modules) live and runs
`python app.py`.

---

## Key routes (`services/gudid-core`)

| Route | Method | Purpose |
|---|---|---|
| `/` | GET | Home — recent devices, QR codes |
| `/scan` | GET | Barcode / QR scanner page |
| `/scan-to-chart` | GET/POST | Scan → GUDID → US Core `Device` → HAPI |
| `/device/<device_id>` | GET | Device detail — safety badges, protocol card, 3D heart |
| `/patients` | GET | Patient picker |
| `/patient/<patient_id>/devices` | GET | Devices for a patient |
| `/patient/<patient_id>/timeline` | GET | Perioperative device timeline |
| `/tools` | GET | Admin / utilities |
| `/admin/overrides` | GET | Institutional protocol overrides |
| `/api/lookup/udi` | POST | Look up a full UDI string |
| `/api/lookup/di/<di>` | GET | Look up by Device Identifier |
| `/api/search?q=` | GET | Search devices |
| `/api/protocol/by-di/<di>` | GET | Perioperative protocol block for a DI |
| `/api/quick-facts` | GET | Magnet rate / MRI / support-line strip |
| `/api/ifu/extract` | POST | Kick off the IFU find→extract→validate pipeline |
| `/api/ifu/status` | GET | Live pipeline status (polled by the scan page) |
| `/api/recalls/check/<device_id>` | GET | Recall check for one device |
| `/api/ask` | POST | AI assistant |
| `/api/device/<device_id>/implant-site` | PUT | Set clinician-confirmed implant location |
| `/generate-qr` | POST | Create a custom QR code |
| `/qr/<device_id>` | GET | QR image |
| `/health` | GET | Health check |

---

## The IFU pipeline

IFU = the manufacturer's official device manual. PeriopUDI finds and reads them
automatically:

1. **Find** — the **offline manual library** first (12 manuals committed under
   `services/gudid-core/data/manuals/`, instant, no network); then the curated seed table;
   then GUDID labeling URLs, EUDAMED, a targeted `fcc.report` scraper, and DuckDuckGo/Bing
   search as fallbacks.
2. **Extract** — download the PDF, `pdfplumber`, keep pages mentioning magnet / MRI /
   electrocautery / EMI.
3. **AI extraction** — a local Qwen3-8B model (via MLX) pulls structured facts: magnet
   rate & mode, programmable-off, MRI conditionality, 24-hour support line, electrocautery
   recommendation, EMI notes.
4. **Validate against GUDID** — conflicts (e.g. MRI safety) are flagged and withheld from
   display, not shown silently.
5. **Store with provenance** — facts keyed to brand/manufacturer, shown with a "Brand"
   badge (from the actual manual, not a generic guideline).

Every extracted fact carries a mandatory `requires_verification` flag until a clinician
signs off — a deliberate safety gate:

```bash
cd services/gudid-core
python ifu_pipeline.py --verify <id> --by "Dr. Name"
```

### Offline manual library

`services/gudid-core/data/manuals/` holds 12 clinician-facing manuals committed to the
repo, indexed by `index.json`. **The demo does not depend on any third-party site**:
fcc.report now returns 403 to every automated request and the fccid.io mirror IP-blocks
after a handful of fetches, so the URLs in `ifu_seed.json` no longer resolve.

| Device family | Manual |
|---|---|
| Medtronic Azure pacemaker | Device Manual (44 pp) |
| Boston Scientific RESONATE/PERCIVA ICD | Physician's Technical Manual (96 pp) |
| Boston Scientific ImageReady | MRI Technical Guide (50 pp) |
| Boston Scientific CIED (any) | Magnet Response (7 pp) |
| Abbott Gallant/Ellipse ICD | MRI-Ready Systems Manual (24 pp) + scan checklist (2 pp) |
| Nevro Senza HFX SCS | MRI Guidelines (32 pp) + Physician Implant Manual (31 pp) |
| Tandem t:slim X2 Control-IQ | User Guide (364 pp) |
| LivaNova VNS Therapy | Physician's Manual (312 pp) + MRI Guidelines (7 pp) + Surgical Procedure (43 pp) |

- The IFU finder tries this library **first**, so covered devices extract with no network
  call at all.
- When a device isn't covered, the "paste PDF URL" box in the scan page and patient
  timeline is **pre-filled** from the library if anything matches (`/api/ifu/suggest`).
- Manuals are served at `/manuals/<file>` and read straight off disk by the extractor.
- `python scripts/fetch_manuals.py --list` shows status, `--verify` checks every PDF
  opens and page counts match, and a bare run re-downloads anything missing from the
  `source_url` recorded in `index.json`.

---

## SMART App Launch

PeriopUDI is EHR-launchable (SMART App Launch v2, public client + PKCE). Code:
`services/gudid-core/smart_launch.py`.

- **Standalone launch** — visit <http://localhost:8090/launch/standalone>. It bounces
  through the SMART Health IT sandbox auth server (patient picker), then returns to
  scan-to-chart with the patient context locked in.
- **EHR launch** — from <https://launch.smarthealthit.org>, register redirect URL
  `http://localhost:8090/smart/callback`, App Launch URL `http://localhost:8090/launch`,
  and launch.
- While a SMART session is active, the app reads/writes FHIR against the **launched**
  server with the bearer token; with no session it uses the local HAPI. `/smart/status`
  shows the current session; `/smart/logout` clears it.
- Requires `SECRET_KEY` set (signs the session). `APP_BASE_URL`, `SMART_CLIENT_ID`,
  `SMART_DEFAULT_ISS` are in `.env.example`.

---

## Standards & compliance

- **FHIR R4** via HAPI; **US Core v8.0.1** Implantable Device Profile (validated via the
  HL7 FHIR Validator)
- **SMART App Launch v2** — EHR + standalone launch, PKCE, minimum-necessary scopes
  (tested against the SMART Health IT sandbox; Epic/Cerner registration pending)
- **CDS Hooks** for the recall-alert service
- **FDA GUDID** as the authoritative device-metadata source; **openFDA** for the recall feed

---

## Repository layout

```
med-device-discovery/
├── docker-compose.yml         # HAPI + Postgres + gudid-core + cds-hooks (+ dev/seed profiles)
├── Makefile                   # up / demo / hapi / seed / recalls / down / test / validate
├──.env.example
├── infrastructure/
│   ├── hapi/                  # HAPI application.yaml
│   └── synthea/               # synthetic-patient seeder
├── services/
│   ├── gudid-core/            # Flask app (scan, timeline, protocol layer, IFU pipeline)
│   ├── fhir-bridge/           # GUDID → US Core Device mapper + HAPI client (library)
│   ├── cds-hooks/             # recall-surveillance CDS Hooks service
│   ├── smart-launcher/        # SMART App Launch v2 (implemented in gudid-core/smart_launch.py)
│   └── ui/                    # scan-to-chart frontend assets
├── scripts/                   # verify_protocols.py, …
├── eval/                      # usability study, usage logs
└── docs/                      # architecture, FHIR conformance, demo script
```

See [`architecture.md`](architecture.md) for the system diagram and data flow,
[`docs/code-flow.md`](docs/code-flow.md) for how a scan moves through the code, and
[`docs/progress.md`](docs/progress.md) for the development record.

---

## Troubleshooting

**Phone can't reach the server** — phone and computer on the same WiFi; `HOST_IP` in
`.env` is your real LAN IP; try `http://<HOST_IP>:8090` directly.

**AI assistant not responding** — check `OPENAI_API_KEY` / `OPENAI_API_BASE`; the rest of
the app works without it.

**HAPI slow to start** — first boot builds its schema; `make hapi` blocks until
`/fhir/metadata` answers. Give it a minute.

**Docker rebuild from scratch**

```bash
docker-compose down
docker-compose build --no-cache
docker-compose up
```

---

## License

Apache-2.0. See [`LICENSE`](LICENSE). Citation metadata in [`CITATION.cff`](CITATION.cff).
