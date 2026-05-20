# infrastructure/hapi  *(Phase 1)*

Local HAPI FHIR R4 server configuration.

Planned:
- `application.yaml` — FHIR R4, US Core v8.0.1 IG loaded at startup, validation enabled for
  writes, CORS open for local dev.
- `Dockerfile` — if a customized HAPI image is needed; otherwise `hapiproject/hapi:latest`
  is used directly from docker-compose.

HAPI is the source of truth for patient/device state (Build.md §2). All reads/writes go through it.
