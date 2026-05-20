# smart-launcher  *(Phase 6 — not yet implemented)*

SMART App Launch v2 conformance.

Planned modules:
- `smart_config.py` — `/.well-known/smart-configuration`.
- `oauth_callback.py` — OAuth2 launch + callback handling (uses `fhirclient`).
- `scopes.py` — minimum-necessary scopes:
  `launch openid fhirUser patient/Patient.read patient/Device.read patient/Device.write patient/Procedure.read`.

Test targets: HAPI's built-in SMART auth server and the public SMART Health IT launcher
(https://launch.smarthealthit.org).
