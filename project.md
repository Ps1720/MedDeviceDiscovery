# PeriopUDI Project Documentation

## Project Overview

**PeriopUDI** is a SMART-on-FHIR perioperative device documentation application designed to close the device-documentation gap in surgical settings. The system enables clinicians to scan medical device identifiers (UDI barcodes) and instantly capture FDA-validated device data into FHIR-conformant electronic health records with real-time FDA recall surveillance.

### Project Vision

> *PeriopUDI transforms a 30-second scan into a USCDI-conformant, GUDID-validated, recall-aware implantable device record — at the point of care, in the OR.*

---

## Project Goals

### Primary Goals
1. **Streamline device documentation** - Reduce manual entry time from minutes to seconds via barcode scanning
2. **Ensure data accuracy** - Leverage FDA's GUDID database as the authoritative source for device metadata
3. **Enable FHIR conformance** - Create US Core v8.0.1 conformant Device resources automatically
4. **Provide clinical safety** - Real-time FDA recall surveillance via CDS Hooks to alert clinicians about device recalls before use
5. **Support clinical integration** - Full SMART-on-FHIR compatibility for EHR integration
6. **Demonstrate real-world value** - Pilot with clinical collaborators to prove operational benefit

### Secondary Goals
- Generate evaluation data for academic publication and competition submission
- Establish a model for perioperative technology that other institutions can adopt
- Contribute to the FHIR community and demonstrate US Core adoption

---

## Target Users & Use Cases

### Primary Users
- **Anesthesiologists** - Pre-operative device verification and risk assessment
- **Surgical nurses** - Device inventory and procedure tracking in the OR
- **Operating room staff** - Quick device information lookup without leaving the patient care area

### Key Use Cases

#### 1. Pre-Op Device Verification
**Scenario:** During pre-operative assessment, an anesthesiologist reviews a patient's implanted devices (pacemaker, ICD, stent, etc.) to determine perioperative risks.

**Current workflow:** Manual chart review, phone calls, unreliable information
**PeriopUDI solution:** 
- Scan the device (from the patient record or physical device)
- Automatic GUDID lookup returns manufacturer, model, MRI safety status
- FHIR Device resource created and linked to patient
- Timeline view shows all implanted devices with safety profiles

#### 2. Real-Time Recall Surveillance
**Scenario:** A patient arrives with a recalled implantable device.

**Current workflow:** Clinicians may not know about recent recalls
**PeriopUDI solution:**
- CDS Hooks service automatically checks patient's devices against daily FDA recall feed
- Critical Class I recalls trigger urgent warning cards
- Class II/III recalls show as advisories on the device timeline

#### 3. Device Inventory in the OR
**Scenario:** During a procedure, staff need to verify device details without leaving the OR.

**Current workflow:** Physical device lookup, incomplete information
**PeriopUDI solution:**
- Scan device barcode on package with phone
- Instant access to regulatory status, manufacturer info, device classification
- No app installation required, works with native camera

---

## Project Scope

### In Scope (MVP Functionality)
- ✅ FDA GUDID database integration for device lookup
- ✅ FHIR R4 REST integration with local HAPI server
- ✅ US Core v8.0.1 Implantable Device Profile mapping
- ✅ Scan-to-chart workflow (UDI → Device → HAPI in <15 seconds)
- ✅ Patient device timeline visualization
- ✅ CDS Hooks recall surveillance service
- ✅ SMART App Launch v2 for EHR integration
- ✅ US Core conformance validation in CI/CD
- ✅ Clinical pilot with UAB Anesthesiology

### Out of Scope (Future Work)
- ❌ FHIR Bulk Data exchange
- ❌ Subscription-based alerts
- ❌ Multi-tenant SaaS deployment
- ❌ Production-grade user authentication
- ❌ CQL-based clinical decision support
- ❌ Custom device profile extensions

---

## Success Criteria

### Technical Metrics
- [ ] HAPI FHIR R4 server running locally with US Core v8.0.1 validation enabled
- [ ] 100% of generated Device resources pass US Core validation (zero errors)
- [ ] Scan-to-chart workflow completes in <15 seconds end-to-end
- [ ] CDS Hooks recall service returns valid cards with 100% accuracy against test data
- [ ] Patient timeline renders correctly with 50+ synthetic patients
- [ ] SMART App Launch authentication works against HAPI and SMART Health IT launcher

### Clinical Metrics
- [ ] ≥2 UAB assistant professors (non-student track) engage in pilot
- [ ] ≥6 weeks of active pilot deployment
- [ ] ≥30 documented devices during pilot
- [ ] System Usability Scale (SUS) score ≥68 (above average)
- [ ] Qualitative feedback collected from all pilot users

### Submission Metrics
- [ ] AMIA 2026 submission accepted (deadline: ~August 2026)
- [ ] 8-minute presentation recorded and polished
- [ ] All submission sections drafted and reviewed
- [ ] Live demo presented at AMIA 2026 Annual Symposium (November 10, 2026, Dallas)

---

## Regulatory & Compliance Context

### FDA GUDID
- **Role:** Authoritative source for device metadata (manufacturer, model, classification, safety attributes)
- **Update frequency:** Daily refreshes (used as-is, no local modifications)
- **Coverage:** ~5M+ medical devices in the US

### US Core v8.0.1
- **Role:** FHIR Implementation Guide defining US healthcare data standards
- **Primary profile:** Implantable Device Profile
- **Conformance:** All generated Device resources validated against this IG
- **Testing:** Automated validation in CI/CD via HL7 FHIR Validator CLI

### SMART-on-FHIR v2
- **Role:** Standard for EHR app launch and patient context
- **OAuth2:** Secures patient data access
- **Scope:** `launch openid fhirUser patient/Patient.read patient/Device.read patient/Device.write patient/Procedure.read`

### CDS Hooks
- **Role:** Standards-based service for clinical decision support
- **Trigger:** `patient-view` (when a patient record is opened in the EHR)
- **Action:** Real-time FDA recall surveillance

### Clinical Pilot
- **Data:** Synthetic patients only (Synthea-generated, no PHI)
- **Devices:** Real device packages (empty boxes) from UAB OR
- **IRB:** Non-human-subjects-research determination (no IRB approval needed)
- **Duration:** 6–8 weeks with 2+ UAB assistant professors

---

## Deployment Environments

### Development
- **Docker Compose** for local multi-container deployment
- **Ports:**
  - HAPI FHIR: `http://localhost:8080/fhir`
  - PeriopUDI: `http://localhost:8090`
  - CDS Hooks: `http://localhost:8091`
  - Postgres: `localhost:5432`

### Testing & CI
- **GitHub Actions** for automated validation
- HL7 FHIR Validator integration for US Core conformance
- Unit tests for mapping logic

### Clinical Pilot (UAB Anesthesiology)
- **Deployment:** Docker containers on secured UAB infrastructure
- **Synthetic data only** (Synthea patients, no patient privacy concerns)
- **Real devices:** Physical implant packages from OR

### Future Production
- **EHR Integration:** SMART-on-FHIR registered as app in Epic, Cerner, or other EHR
- **FHIR Server:** Institutional FHIR R4 server (HAPI or vendor-supplied)
- **Recall Feed:** Production openFDA or institutional device recall database

---

## Key Stakeholders

| Role | Name/Affiliation | Responsibilities |
|------|------------------|------------------|
| **Technical Lead** | Prashant Sharma (UAB) | Overall development, architecture, submission |
| **Clinical Co-Authors** | UAB Dept. of Anesthesiology (2+ assistant professors) | Pilot participation, feedback, clinical validation |
| **Advisor** | Dr. [Name] (UAB) | Clinical oversight, IRB determination |
| **AMIA Competition** | HL7/AMIA | Submission review, presentation opportunity |

---

## Project Timeline

| Week | Phase | Key Deliverables | Status |
|------|-------|------------------|--------|
| 1 | 0–1 | Scaffolding, HAPI setup, 50 synthetic patients | ✅ Complete |
| 1–2 | 2 | GUDID→US Core mapper, validation | ✅ Complete |
| 2 | 3 | Scan-to-chart workflow, logging | ✅ Complete |
| 2–3 | 4 | Timeline view, device cards, safety profiles | ✅ Complete |
| 3 | 5 | CDS Hooks recalls, FDA feed integration | ✅ Complete |
| 3 | 6 | SMART App Launch v2 | In Progress |
| 3–4 | 7–8 | CI validation, evaluation harness | In Progress |
| 5–7 | 9 | Clinical pilot (6–8 weeks) | Pending |
| 7–8 | 10 | Submission writing, demo video, polish | Pending |
| End of Q3 2026 | — | **AMIA submission deadline** | Target: July 2026 |
| Nov 10, 2026 | — | **Presentation at AMIA 2026** | Dallas, TX |

---

## Technology Stack Summary

### Backend Services
- **Python 3.9+** runtime
- **Flask 3.0** web framework
- **FHIR R4** standard (via HAPI server)
- **HAPI FHIR** open-source FHIR server
- **PostgreSQL** for HAPI persistence
- **SQLite** for recall cache (CDS Hooks)

### Frontend
- **HTML5** + **CSS3** (Tailwind CSS for styling)
- **Vanilla JavaScript** (no framework for simplicity)
- **QR code scanning** via html5-qrcode library

### Data Integration
- **FDA GUDID API** (AccessGUDID) for device data
- **OpenFDA API** for recall feed
- **Synthea** for synthetic patient data generation

### DevOps & Testing
- **Docker** & **Docker Compose** for containerization
- **GitHub Actions** for CI/CD
- **HL7 FHIR Validator CLI** for conformance testing
- **pytest** for unit testing

---

## Competitive Landscape

### Existing Solutions
- **Implant registries** (vendor-specific, siloed data)
- **FDA GUDID web lookup** (requires manual navigation, no integration)
- **Clinical decision support systems** (generic, not device-specific)
- **Point-of-care clinical apps** (exist but not FHIR-based)

### PeriopUDI's Differentiation
1. **Workflow integration** - Scan → FHIR → Chart in one flow
2. **Standards-based** - SMART-on-FHIR + US Core + CDS Hooks (portable)
3. **Real-time recall** - Automatic surveillance, not manual lookup
4. **No installation** - Works with native phone camera (zero friction)
5. **Open source** - Inspectable, auditable, reproducible

---

## Risk Mitigation

### Technical Risks

| Risk | Impact | Mitigation |
|------|--------|-----------|
| GUDID API downtime | Device lookups fail | Fallback to local cache, graceful error messages |
| FHIR validation failure | Submission invalidated | Validate in CI on every commit, never ship invalid resources |
| HAPI data loss | Pilot data lost | Daily backups of Postgres, tested restore procedure |

### Clinical Risks

| Risk | Impact | Mitigation |
|------|--------|-----------|
| Clinicians don't adopt | Pilot fails to generate data | Regular user feedback loops, UX iteration during pilot |
| Data privacy concern | Legal/regulatory block | Synthetic data only (Synthea), IRB non-human-subjects determination |
| Device recall misses | False negative on safety | Daily openFDA refresh, human review of demo recalls |

### Submission Risks

| Risk | Impact | Mitigation |
|------|--------|-----------|
| Missed AMIA deadline | Not accepted | Submission ready 1 week early, buffer for revisions |
| Demo video poor quality | Judges unimpressed | Professional recording, practice walkthrough, backup video |
| Judges unfamiliar with FHIR | Low score on tech | Clear explanations in submission, focus on clinical value |

---

## Known Limitations & Assumptions

### Limitations
- **Synthetic patients only** — No real patient data during pilot (by design for privacy)
- **Demo device set** — openFDA recall matching uses curated demo entries (production needs UDI-DI-keyed source)
- **Local HAPI only** — No connection to Epic/Cerner during pilot (Phase 6 adds SMART integration)
- **Single user** — No multi-user authentication in MVP (future enhancement)
- **No offline mode** — Requires internet for GUDID and FDA API lookups

### Assumptions
- **GUDID coverage** — Assumption that target implantable devices are in FDA GUDID (true for most, some older/niche devices may be missing)
- **QR readability** — Assumption that existing UDI barcodes on device packages are readable by phone camera (mostly true, some may need physical scanner)
- **Clinician internet access** — Assumption that OR has adequate WiFi for FHIR API calls (reasonable for modern ORs)
- **SMART-conformant EHR** — Assumption that target EHR supports SMART App Launch (true for Epic, Cerner, others)

---

## Metrics & Evaluation

### Quantitative Metrics (from Pilot)
- **Time-to-documentation:** Mean/median seconds from scan to FHIR Device created (target <15s)
- **Success rate:** % of scans that result in valid Device resource
- **Unique patients:** Count of distinct patients whose devices were documented
- **Unique devices:** Count of distinct UDIs successfully documented
- **Recall detection:** Sensitivity/specificity of CDS Hooks recall matching

### Qualitative Metrics
- **SUS score:** System Usability Scale (target ≥68)
- **Clinician quotes:** Direct feedback from pilot users
- **Workflow integration:** Perceived ease of integration into existing OR workflow
- **Safety concerns:** Any negative feedback on device recall alert accuracy or false positives

### Publication Metrics
- **Abstract:** 1,000 characters (fits AMIA abstract field)
- **Full paper:** Not required for AMIA competition (8-minute presentation instead)
- **Presentation:** 8 minutes, no Q&A, audience voting

---

## Related Documents

- **Build.md** - Detailed phase-by-phase implementation roadmap
- **docs/architecture.md** - System design and data flow
- **docs/fhir-conformance.md** - FHIR profiles and capability statement
- **docs/pilot-protocol.md** - Clinical pilot protocol and SUS questionnaire
- **docs/demo-script.md** - 8-minute presentation walkthrough

---

## Contact & Attribution

**Project Lead:** Prashant Sharma (psharma2@uab.edu)  
**Affiliation:** University of Alabama at Birmingham, Department of Anesthesiology  
**License:** Apache 2.0  
**Citation:** See `CITATION.cff`

---

*Last updated: 2026-06-04*
