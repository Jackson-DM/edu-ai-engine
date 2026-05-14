# Phase 2 — Deferred Items

Tracking items deferred from Phase 1 of the v2 migration. See `docs/PIPELINE_V2.md` for context.

- Populate `content_pillars: []` per brand (after step 5 pillar parser exists)
- Build pillar filtering (step 5)
- Build `scripts/ingest_module.py` (step 6)
- Build `pipeline/plan_pieces.py` (step 7)
- Decide whether `foundation/BRAND_VOICES.md`'s Cross-Brand Rules section should be injected per-brand or kept out

## v1 issues to revisit

- Articles consistently produced under target length (800 → ~280-470). May need explicit length instruction in system prompt, or revisit whether 800 is the right target.
