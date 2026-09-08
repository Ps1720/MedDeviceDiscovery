# smart-launcher  *(Phase 6)*

SMART App Launch v2 conformance.

**Implemented — but as a blueprint inside the running app**, not a standalone
service. The launcher only needs the Flask session and the existing FHIR wiring
in `gudid-core`, so splitting it into its own container would buy nothing for the
pilot. The code lives at:

    services/gudid-core/smart_launch.py

What it provides:

| Route | Purpose |
|---|---|
| `GET /launch` | EHR launch — `iss` + `launch` params, discovers the auth server, redirects to `authorize` with PKCE |
| `GET /launch/standalone` | Standalone launch against `SMART_DEFAULT_ISS` (patient picker at the auth server) |
| `GET /smart/callback` | OAuth2 redirect target — exchanges the code for tokens + patient context, stores them in the session |
| `GET /smart/status` | JSON view of the current SMART session |
| `GET|POST /smart/logout` | Drop the SMART session |
| `GET /.well-known/smart-configuration` | Advertises this app's SMART capabilities |

- Public client + PKCE (S256), **no client secret**. `requests` + stdlib only.
- Scopes (minimum-necessary, from `Config.SMART_SCOPES`):
  `launch openid fhirUser profile patient/Patient.read patient/Device.read
  patient/Device.write patient/Procedure.read`
- When a SMART session is active, `app.py`'s `before_request` hook points
  `scan_to_chart`'s FHIR reads/writes at the **launched** FHIR server with the
  bearer token (see `scan_to_chart.set_fhir_context`). No session → local HAPI.

Config: `SECRET_KEY` (required — signs the session), `APP_BASE_URL`,
`SMART_CLIENT_ID`, `SMART_DEFAULT_ISS`. See `.env.example`.

Test target: the public SMART Health IT launcher — <https://launch.smarthealthit.org>.
Register `http://localhost:8090/smart/callback` as the app's Redirect URL there,
or use the launcher's "Provider EHR Launch" against `http://localhost:8090/launch`.
