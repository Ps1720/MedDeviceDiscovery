# infrastructure/synthea  *(Phase 1)*

Synthetic patient substrate. Synthea generates the patient population loaded into HAPI.
**Synthea only — never real PHI** (Build.md §7).

Planned:
- `modules/perioperative_surgery.json` — custom module adding surgical encounters/procedures.
- `config/` — Synthea configuration overrides.
- `seed.sh` — generates 50 patients with surgical histories and loads them into HAPI via the
  `$transaction` endpoint. Wired to `make seed`.
