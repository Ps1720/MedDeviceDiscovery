# PeriopUDI Architecture

## System Overview

PeriopUDI is a three-service FHIR-based system with a local FHIR R4 foundation (HAPI), a device-mapping bridge, and a clinical decision support service for FDA recall surveillance.

```
┌─────────────────────────────────────────────────────────────────┐
│                     PeriopUDI System Architecture               │
└─────────────────────────────────────────────────────────────────┘

                          ┌──────────────┐
                          │   Clinician  │
                          │ (Phone/Web)  │
                          └──────┬───────┘
                                 │
            ┌────────────────────┼────────────────────┐
            │                    │                    │
      ┌─────▼────────┐  ┌────────▼────────┐  ┌──────▼──────────┐
      │  PeriopUDI   │  │  SMART Auth     │  │  CDS Hooks      │
      │  UI/Scan     │  │  (OAuth2)       │  │  (Recalls)      │
      │              │  │                 │  │                 │
      │ Port 8090    │  │ Port 8090       │  │ Port 8091       │
      └─────┬────────┘  └────────┬────────┘  └──────┬──────────┘
            │                    │                   │
            └────────────────────┼───────────────────┘
                                 │
                    ┌────────────▼─────────────┐
                    │   HAPI FHIR R4 Server    │
                    │  (Validation Enabled)    │
                    │  (US Core v8.0.1 IG)     │
                    │                          │
                    │ Port 8080                │
                    └────────────┬─────────────┘
                                 │
                    ┌────────────▼─────────────┐
                    │   PostgreSQL Database    │
                    │  (HAPI Persistence)      │
                    │                          │
                    │ Port 5432                │
                    └──────────────────────────┘

           ┌──────────────────────┐
           │  External APIs       │
           ├──────────────────────┤
           │ FDA GUDID            │
           │ openFDA Recall       │
           │ SMART Health IT      │
           │ Launcher             │
           └──────────────────────┘
```

---

## Service Architecture

### 1. PeriopUDI Core (`services/gudid-core`)

**Purpose:** Web application providing the user interface for scanning, documenting devices, and viewing patient timelines.

**Key Components:**
- **app.py** - Flask WSGI application with routes
- **scan_to_chart.py** - Device documentation workflow orchestration
- **gudid_service.py** - FDA GUDID API client
- **hapi_client.py** - FHIR server integration (imported from fhir-bridge)
- **qr_generator.py** - QR code image generation
- **protocol_db.py / protocol_seed.py** - Perioperative protocol knowledge base (SQLite, version-gated startup seeding)
- **device_class_resolver.py** - GUDID/FHIR record → protocol device class (brand/model > FDA product code > GMDN code > keyword)
- **overrides.py** - Institutional override overlay (`data/institution_overrides.json`)
- **protocol_service.py** - Protocol block assembly with per-field provenance (override > brand > class > GUDID)
- **implant_sites.py** - Implant-location data model: per-class lead configs, SNOMED-coded FHIR Device extension (`…/StructureDefinition/implant-site`) builder/extractor. Extension present = clinician-confirmed; absent = typical-placement rendering
- **Templates** - HTML5 UI pages
- **Static** - CSS, JavaScript (`protocol_card.js` shared protocol panel; `heart_visual.js` 3D heart + magnet simulation, Three.js r128 lazy-loaded from CDN; `hv_test.html` headless-Chrome dev fixture), generated QR codes

**Key Endpoints:**
| Endpoint | Method | Purpose |
|----------|--------|---------|
| `/` | GET | Home page, device search |
| `/patient/<id>/timeline` | GET | Timeline view of patient's devices |
| `/patient/<id>/devices` | GET | JSON API: patient's devices with recalls + protocol hints |
| `/scan-to-chart` | GET/POST | Scan & document workflow (returns `protocol` block) |
| `POST /api/lookup/udi` | POST | UDI → GUDID lookup (+ `protocol` block; accepts bare DIs) |
| `/api/protocol/by-di/<di>` | GET | Perioperative protocol for a DI (`?context=surgery\|mri\|ep_study`) |
| `/api/device/<id>/implant-site` | PUT | Set clinician-confirmed implant location (lead_config, pocket_side) on a documented Device |
| `/admin/overrides` | GET | Read-only institutional overrides admin page |
| `/api/admin/overrides` | GET | JSON: active overrides + parse errors |
| `/api/ask` | POST | AI assistant (Claude/OpenAI) |
| `/health` | GET | Health check endpoint |

**Perioperative Protocol Layer:**

```
UDI scan → GUDID record (extract_device_info)
              │
   device_class_resolver  (11 classes: pacemaker, leadless_pacemaker, icd, crt_p, crt_d,
              │             vns, dbs, scs, insulin_pump, cgm, closed_loop)
   protocol_service.build_protocol_block(record, context)
       ├─ protocol_facts + checklist_items + brand_facts   (SQLite: data/protocols.db)
       └─ institution_overrides.json merge (override > brand fact > class fact > raw GUDID)
              │
   `protocol` JSON block with per-field provenance → scan result panel / timeline expander
```

- Knowledge is **reference data, not patient data** — it stays out of FHIR and is re-derived
  at render time. One exception: an applied institutional MRI override adds a
  `Device.safety` coding (`mri-institutional`, local code system) at documentation time.
- Every seeded clinical row carries `requires_verification=1` and a citation placeholder;
  the UI shows an unverified-content strip plus a decision-support disclaimer until a
  clinician reviews the row.
- Contexts: `surgery` (default), `mri`, `ep_study`. Context-specific rows shadow `all` rows.
- E2E verification: `python3 scripts/verify_protocols.py` against a running stack.

**Environment Variables:**
```
OPENAI_API_KEY          - API key for Claude/OpenAI
OPENAI_API_BASE         - Custom API base URL (optional)
OPENAI_MODEL            - Model ID (default: gpt-4o-mini)
FHIR_BASE_URL           - Internal HAPI URL (http://hapi:8080/fhir)
PUBLIC_FHIR_BASE_URL    - External HAPI URL (http://localhost:8080/fhir)
CDS_HOOKS_URL           - CDS Hooks service URL (http://cds-hooks:5001)
PROTOCOL_DB_PATH        - Protocol knowledge base SQLite path (default: data/protocols.db)
OVERRIDES_PATH          - Institutional overrides JSON (default: data/institution_overrides.json)
SECRET_KEY              - Flask session secret
FLASK_ENV               - production | development
```

**Deployment:**
- **Docker image:** Built from repo root (includes fhir-bridge modules)
- **Port:** 8090 (remapped from original 5000 due to macOS AirPlay)
- **Storage:** 
  - `static/qr_codes/` - Generated QR images
  - `data/` - Cached device info
  - `/eval/usage_logs/` - Scan event logs (CSV)

---

### 2. FHIR Bridge (`services/fhir-bridge`)

**Purpose:** Device data mapping and validation layer between FDA GUDID and FHIR R4.

**Key Modules:**
- **gudid_to_uscore_device.py** - Maps GUDID records to US Core v8.0.1 Device Profile
- **hapi_client.py** - REST client for HAPI FHIR operations
- **profiles/** - Cached US Core IG package for validation reference
- **tests/** - Unit tests and conformance validation

**Core Functions:**

#### `map_to_device(gudid_record, patient_id=None, **production_ids) → dict`
Converts a GUDID record into a FHIR Device resource.

**Input:**
```python
{
    "udi": "08717648200274",
    "di": "8717648",
    "brand_name": "XIENCE",
    "manufacturer": "Abbott Vascular",
    "device_type": "Coronary Stent",
    "gmdn_code": "C-1234",
    "mri_status": "Conditional",
    "latex_free": True,
    "single_use": False,
    "sterile": True,
    ...
}
```

**Output:**
```json
{
    "resourceType": "Device",
    "meta": {
        "profile": [
            "http://hl7.org/fhir/us/core/StructureDefinition/us-core-implantable-device"
        ]
    },
    "udiCarrier": [
        {
            "deviceIdentifier": "08717648200274",
            "issuer": "GS1",
            "carrierHRF": "08717648200274"
        }
    ],
    "status": "active",
    "manufacturer": "Abbott Vascular",
    "deviceName": [
        {
            "name": "XIENCE",
            "type": "model-name"
        }
    ],
    "type": {
        "coding": [
            {
                "system": "http://terminology.hl7.org/CodeSystem/v3-RoleCode",
                "code": "GMDN",
                "display": "Coronary Stent"
            }
        ]
    },
    "patient": {
        "reference": "Patient/123"
    },
    "safety": [
        {
            "coding": [
                {
                    "system": "http://terminology.hl7.org/CodeSystem/v3-ActCode",
                    "code": "MRI_CONDITIONAL"
                }
            ]
        }
    ],
    "distinctIdentifier": "8717648",
    "modelNumber": "...",
    "serialNumber": "...",
    ...
}
```

#### `create_device(device_resource) → str`
POSTs device to HAPI FHIR, returns logical ID.

#### `validate(device_resource) → bool`
Validates against US Core using HL7 FHIR Validator CLI.

**Validation:**
- All Device resources validated against US Core v8.0.1 Implantable Device Profile
- Validation runs on every CI commit (GitHub Actions)
- Terminology warnings allowed (GMDN codes may not have FHIR equivalents)
- Errors block submission

**Storage:**
- No persistent storage (stateless)
- Relies on HAPI for Device persistence
- Test fixtures in `tests/`

---

### 3. CDS Hooks Service (`services/cds-hooks`)

**Purpose:** Real-time FDA recall surveillance via CDS Hooks standard.

**Key Modules:**
- **app.py** - Flask app with CDS Hooks discovery and execution endpoints
- **recalls.py** - Recall data model and queries
- **recall_poller.py** - Daily openFDA feed fetch
- **data/recalls.db** - SQLite cache of recall records

**CDS Hooks Discovery Endpoint**

```
GET /cds-services
```

**Response:**
```json
{
    "services": [
        {
            "hook": "patient-view",
            "id": "recall-check",
            "title": "FDA Device Recall Check",
            "description": "Real-time surveillance for FDA device recalls",
            "prefetch": {
                "patientDevices": "Patient/{{context.patientId}}/Device"
            }
        }
    ]
}
```

**CDS Hooks Execution Endpoint**

```
POST /cds-services/recall-check

Request:
{
    "hook": "patient-view",
    "context": {
        "patientId": "Patient/123"
    },
    "prefetch": {
        "patientDevices": [<Device resources>]
    }
}

Response:
{
    "cards": [
        {
            "summary": "Critical Recall: MOSAIC Valve (Class I)",
            "indicator": "critical",
            "source": {
                "label": "FDA CDRH"
            },
            "detail": "Device identifier 00643169001763 has a Class I recall..."
        }
    ]
}
```

**Recall Data Schema:**
```sql
CREATE TABLE recalls (
    id INTEGER PRIMARY KEY,
    device_identifier TEXT,      -- UDI-DI
    recall_number TEXT,           -- FDA recall number
    classification TEXT,          -- Class I, II, or III
    reason TEXT,                  -- Recall reason
    recall_initiation_date TEXT,  -- YYYY-MM-DD
    status TEXT,                  -- Ongoing, Completed, etc.
    firm TEXT,                    -- Manufacturer name
    source TEXT,                  -- 'openFDA' or 'demo'
    UNIQUE(device_identifier, recall_number)
);
```

**Recall Polling:**
- Triggered on CDS Hooks container startup
- Can run on-demand: `make recalls`
- Fetches from openFDA `device/recall.json` endpoint daily
- Pre-loads demo recalls (XIENCE Class II, MOSAIC Class I) for reproducible demos
- Caches in SQLite to reduce API load

**Deployment:**
- **Docker image:** Built from `services/cds-hooks/`
- **Port:** 8091 (mapped from internal 5001)
- **Database:** SQLite at `/app/data/recalls.db`
- **Environment:** `FHIR_BASE_URL`, `CDS_HOOKS_URL`

---

## FHIR Foundation

### HAPI FHIR R4 Server

**Version:** Latest (as of 2026-05-19: HAPI FHIR 8.8.0, FHIR R4 4.0.1)

**Key Configuration** (`infrastructure/hapi/application.yaml`):
```yaml
fhir:
  version: R4
  implementations_guides:
    - hl7.fhir.us.core#8.0.1  # US Core v8.0.1
  validation:
    enabled: true             # Reject invalid resources
  cors:
    allow_credentials: true
    allowed_origin_patterns: [".*"]
  tester_ui:
    enabled: true             # Web UI at port 8080
```

**Capabilities:**
- FHIR R4 REST API (read/write)
- Transaction bundle support
- Resource validation against loaded IGs
- Terminology service (basic)
- SMART authorization server (built-in)

**Supported Resources:**
- `Device` (primary)
- `Patient`
- `Procedure` (with `focalDevice` reference)
- `Encounter`
- `Observation`
- `DetectedIssue` (for alerts)
- `AuditEvent`
- `CapabilityStatement`

**Database:**
- **PostgreSQL 16** for persistence
- **Container:** `periop-udi-hapi-db`
- **Credentials:** (dev-only) user=`hapi`, password=`hapi`, db=`hapi`
- **Backups:** Docker volume `hapi-pgdata` (managed by Docker)

**URL:** `http://localhost:8080/fhir`

**Tester UI:** `http://localhost:8080/` (HAPI's built-in browser interface)

---

### Synthea Synthetic Patient Seeding

**Purpose:** Generate realistic perioperative patient cohorts for testing without PHI.

**Generated Data:**
- 50 alive patients + 15 deceased (65 total, as of 2026-05-19)
- 4,550 Encounters (surgical and other)
- 11,628 Procedures (with surgical histories)
- 38,260 Observations (vital signs, lab results, etc.)
- 1,000+ Devices (implanted and non-implanted)

**Custom Module:**
- **File:** `infrastructure/synthea/modules/perioperative_surgery.json`
- **Scope:** Perioperative procedures, implant-heavy histories
- **Frequency:** Every simulated patient gets 2–5 surgical procedures

**Seeding Process:**
1. Synthea generates FHIR Bundles (transaction format)
2. Bundles posted to HAPI via `POST /fhir/` (transaction endpoint)
3. HAPI validates each resource against US Core
4. Resources persisted to PostgreSQL

**Seeding Script:**
```bash
make seed                    # Generate and load patients
PATIENT_COUNT=100 make seed # Custom patient count
```

**Validation During Seeding:**
- HAPI rejects invalid resources (HTTP 422 OperationOutcome)
- Seeding logs all rejections (none expected with Synthea output)
- If invalid: fix Synthea module or IG validation config

---

## Data Flow Diagrams

### Workflow 1: Scan-to-Chart Device Documentation

```
1. Clinician scans UDI barcode
   ↓
2. PeriopUDI sends UDI to gudid_service.py
   ↓
3. gudid_service queries FDA GUDID API
   ├─ Returns: manufacturer, model, GMDN, safety attributes
   ↓
4. map_to_device() converts GUDID → FHIR Device
   ├─ Validates against US Core v8.0.1
   ↓
5. hapi_client.create_device() POSTs to HAPI
   ├─ HAPI validates against US Core
   ├─ HTTP 201: Device created
   ├─ Returns: logical Device ID
   ↓
6. PeriopUDI logs scan to eval/usage_logs/scans.csv
   ├─ Columns: timestamp, user, udi, patient_id, device_id, time_ms, success
   ↓
7. UI redirects to /patient/{patient_id}/timeline
   ├─ Timeline fetches all patient Devices from HAPI
   ├─ Displays device cards with safety badges
   ↓
End: Device visible in patient chart (<15 seconds total)
```

### Workflow 2: CDS Hooks Recall Surveillance

```
1. Clinician opens patient in EHR (or PeriopUDI patient view)
   ↓
2. EHR calls CDS Hooks: POST /cds-services/recall-check
   ├─ Context: patientId
   ├─ Prefetch: patient's Devices (from HAPI via prefetch)
   ↓
3. CDS Hooks service iterates over Devices
   ├─ Extracts: device_identifier (UDI-DI) from each Device.udiCarrier
   ↓
4. Queries SQLite recalls.db for matching device_identifier
   ├─ SELECT * FROM recalls WHERE device_identifier = ?
   ↓
5. Builds CDS Cards for all matching recalls
   ├─ Class I recall → indicator: "critical" (red)
   ├─ Class II recall → indicator: "warning" (amber)
   ├─ Class III recall → indicator: "info" (blue)
   ↓
6. Returns CDS Cards response
   ├─ EHR displays cards in UI
   ├─ Clinician sees recall alert immediately
   ↓
End: Real-time recall surveillance
```

### Workflow 3: SMART App Launch Integration (Phase 6)

```
1. EHR user clicks "Launch PeriopUDI" link
   ├─ EHR redirects: https://launch.smarthealthit.org/
   ↓
2. SMART launcher redirects to PeriopUDI /launch
   ├─ Params: iss (issuer), launch (opaque token)
   ↓
3. PeriopUDI exchanges launch code for OAuth token
   ├─ Backend: POST /oauth/token
   ├─ Scope: launch openid fhirUser patient/Patient.read ...
   ↓
4. PeriopUDI receives patient context (patient_id)
   ├─ Stored in session
   ↓
5. UI pre-populates patient picker with launched patient
   ├─ Scan workflow defaults to this patient
   ↓
6. Clinician scans device → documented to launched patient's timeline
   ↓
End: Seamless EHR integration
```

---

## Container Orchestration (Docker Compose)

### Service Definitions

| Service | Image | Port (Host:Container) | Purpose |
|---------|-------|----------------------|---------|
| **hapi-db** | postgres:16 | 5432:5432 | HAPI database |
| **hapi** | hapiproject/hapi:latest | 8080:8080 | FHIR R4 server |
| **cds-hooks** | ./services/cds-hooks | 8091:5001 | Recall surveillance |
| **gudid-core** | ./services/gudid-core | 8090:8090 | UI & scan workflow |
| **synthea-seed** | ./infrastructure/synthea | (one-shot) | Patient generation |

### Startup Order

```mermaid
hapi-db ready
    ↓
hapi starts (depends_on: hapi-db healthy)
    ↓
cds-hooks starts (depends_on: hapi started)
gudid-core starts (depends_on: hapi started)
    ↓
synthea-seed runs (profile: seed, depends_on: hapi started)
    ↓
System ready for demo
```

### Volumes & Persistence

| Path | Purpose | Persistence |
|------|---------|-------------|
| `hapi-pgdata` | PostgreSQL data | Docker-managed volume (survives restart) |
| `./services/gudid-core/data/` | Cached device info | Host mount |
| `./services/cds-hooks/data/` | SQLite recalls cache | Host mount |
| `./eval/usage_logs/` | Scan event logs | Host mount |

### Environment File (`.env`)

```bash
# External APIs
OPENAI_API_KEY=sk-xxxxx
OPENAI_API_BASE=https://api.openai.com/v1
OPENAI_MODEL=gpt-4o-mini

# Local network
HOST_IP=192.168.1.100   # For mobile phone access
SECRET_KEY=change-in-production

# Optional: Custom patient count
PATIENT_COUNT=50

# Flask mode
FLASK_ENV=production
```

### Common Commands

```bash
# Start entire stack
docker-compose up -d

# Seed synthetic patients
docker-compose --profile seed run synthea-seed

# View logs
docker-compose logs -f gudid-core

# Stop
docker-compose down

# Clean slate (removes volumes)
docker-compose down -v
```

---

## API Contracts

### GUDID Service Interface

```python
# services/gudid-core/gudid_service.py

def lookup_by_udi(udi: str) -> dict:
    """
    Queries FDA GUDID by UDI string.
    Returns device metadata or None if not found.
    """
    # Example return:
    # {
    #     "udi": "08717648200274",
    #     "di": "8717648",
    #     "brand_name": "XIENCE",
    #     "manufacturer": "Abbott Vascular",
    #     ...
    # }
```

### HAPI Client Interface

```python
# services/fhir-bridge/hapi_client.py

class HAPIClient:
    def create_device(self, device_resource: dict) -> str:
        """Create Device resource, return logical ID."""
    
    def get_patient_devices(self, patient_id: str) -> list:
        """Fetch all Devices linked to a Patient."""
    
    def link_to_procedure(self, device_id: str, procedure_id: str):
        """Add Device to Procedure.focalDevice via JSON Patch."""
    
    def validate(self, resource: dict, profile_url: str) -> bool:
        """Validate resource against profile using HL7 Validator."""
```

### CDS Hooks Service Interface

```
GET /cds-services
→ CDS Hooks discovery (service catalog)

POST /cds-services/recall-check
→ CDS Hooks execution (recall check for patient)
```

---

## Performance Characteristics

### Latency Targets (Per Workflow)

| Operation | Target | Achieved |
|-----------|--------|----------|
| GUDID lookup (API) | <3s | ~1–2s (depends on GUDID load) |
| Map to US Core Device | <1s | <500ms |
| POST to HAPI | <2s | ~500ms–1s |
| Timeline render (HTML) | <500ms | ~200–400ms |
| CDS Hooks execution | <2s | ~800ms–1.5s |
| **Scan → Device recorded** | **<15s** | **~0.7–1.4s** ✅ |

### Scalability Limits

- **Patients:** 50–100 (demo), 1,000+ (with Postgres tuning)
- **Devices per patient:** 10–20 typical, 100+ supported
- **Recall records:** 1,000+ (no pagination in MVP)
- **Concurrent users:** Single-digit (not intended for production scale)

---

## Security Architecture

### Authentication & Authorization

- **SMART App Launch v2** (Phase 6)
  - OAuth2 code flow for EHR users
  - Patient context validated by EHR
  - Scopes: `patient/Patient.read`, `patient/Device.read`, `patient/Device.write`

- **Local development** (MVP)
  - No authentication (synthetic data only)
  - Manual patient picker

### Data Privacy

- **No PHI storage** — Synthea patients only (synthetic, no real identifiers)
- **No API logging** — GUDID/FDA API calls don't log personally identifiable info
- **FHIR validation** — All resources validated before storage (no malformed data)

### Network Security

- **Development:** All services on localhost (Docker internal network)
- **Pilot (UAB):** Running behind UAB firewalls, HTTPS on production endpoints
- **Public deployment:** HTTPS required, CORS restricted to trusted origins

---

## Monitoring & Logging

### Logs

- **PeriopUDI:** Flask logs to stdout (Docker captures)
- **HAPI:** Spring Boot logs to stdout
- **Recall poller:** Logs to file in `/app/data/recall_poller.log`
- **Scans:** CSV log in `/eval/usage_logs/scans.csv`

### Health Checks

```bash
# PeriopUDI
curl http://localhost:8090/health

# HAPI FHIR
curl http://localhost:8080/fhir/metadata

# CDS Hooks
curl http://localhost:8091/cds-services
```

### Metrics (Future)

- Scan volume (scans.csv)
- Device validation errors (HAPI logs)
- Recall match accuracy (manual review)
- System uptime

---

## Deployment Checklist

### Pre-Deployment

- [ ] `.env` configured with OPENAI_API_KEY, HOST_IP
- [ ] Docker & Docker Compose installed
- [ ] 2+ GB disk space available (HAPI Postgres data)
- [ ] Port 8080, 8090, 8091 available

### Deployment

- [ ] `docker-compose up -d`
- [ ] Wait 30s for HAPI to start
- [ ] `docker-compose --profile seed run synthea-seed`
- [ ] Verify: `curl http://localhost:8090/` (home page loads)
- [ ] Verify: `curl http://localhost:8080/fhir/Patient?_count=5` (synthetic patients)
- [ ] Verify: `curl http://localhost:8091/cds-services` (recall service ready)

### Post-Deployment

- [ ] Test scan-to-chart with a known UDI (e.g., XIENCE `08717648200274`)
- [ ] Verify device appears in patient timeline
- [ ] Verify CDS Hooks card shows XIENCE recall (Class II)
- [ ] Monitor logs for errors: `docker-compose logs -f`

---

## Technology Decisions

### Why Three Services (Not Monolith)?

1. **Separation of concerns:** GUDID lookup ≠ FHIR mapping ≠ CDS Hooks
2. **Independent deployment:** Can upgrade HAPI without restarting PeriopUDI
3. **Standards compliance:** CDS Hooks runs as a separate service per spec
4. **Testing:** Each service has isolated test suite
5. **Scalability:** Future: replace HAPI with institutional server, keep PeriopUDI and CDS Hooks

### Why HAPI (Not Vendor FHIR Server)?

1. **No licensing required** — Open source, free for pilots
2. **Easy local development** — Docker-based, runs anywhere
3. **US Core support** — HAPI maintains IG packages
4. **Test integration** — Includes SMART auth server for testing
5. **Future bridging** — Easy to swap out for Epic/Cerner servers in production

### Why Flask (Not Django)?

1. **Lightweight** — Minimal boilerplate for a demo app
2. **Learning curve** — Single developer, minimal team overhead
3. **Microframework** — Decoupled from data layer (FHIR is the DB)
4. **Docker-friendly** — Simple multi-service orchestration
5. **Precedent** — Original STA app was Flask

### Why Synthea (Not Real Data)?

1. **Privacy by design** — No PHI concerns, no IRB required
2. **Reproducibility** — Same seed = same patients every demo
3. **Realism** — Synthea produces clinically realistic data
4. **Audit trail** — Can trace back to Synthea module if needed
5. **Compliance** — No HIPAA, GDPR, or state privacy regulations

---

## Known Technical Debt

### MVP Shortcuts

- **Recall matching:** openFDA doesn't key recalls by UDI-DI. Using demo recalls for now. Production needs UDI-DI-indexed source.
- **No offline mode:** Requires internet for GUDID and FDA lookups. Caching partial.
- **Single-user:** No multi-user session management. Future: add SMART context persistence.
- **Manual patient picker:** No automatic EHR patient context in MVP. Phase 6 adds SMART launch.

### Performance Optimizations (Future)

- GUDID lookup caching (Redis or in-memory)
- Device timeline pagination (currently all at once)
- Recall card generation caching (rebuild daily, not per request)

---

*Last updated: 2026-06-04*
