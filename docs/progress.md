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
