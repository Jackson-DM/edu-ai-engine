edu-ai-engine: Build Log
Project Genesis
edu-ai-engine is the multi-brand successor to Houston Engine. Where Houston Engine was a single-brand pipeline ingesting RSS signals and publishing AI content for Houston AI Club, edu-ai-engine is a multi-brand pipeline ingesting Anthropic course module exports and publishing educational LinkedIn content across five brands, with every post backlinking to Leon Coe's personal LinkedIn and Twitter.
Five brands, each with its own URL, voice, and content pillars:

* `houston-ai-club`
* `amplify-intelligence`
* `amplified-exec`
* `leon-coe` (personal brand, the linking hub)
* `ai-first-work`
The fundamental design shift from Houston Engine: every place Houston could hardcode "Houston AI Club," edu-ai-engine needs a per-brand switch. URLs, voice files, pillars, humanizer intensity, what content the brand publishes about.
Why v2 Exists
v1 of edu-ai-engine treated content pillars and voice as single global resources injected wholesale into every prompt regardless of brand. URLs were inferred by the model and frequently fabricated. The "1-source-→-N pieces" framing existed but wasn't structurally supported.
v2 is the migration to fix these. It's organized as two phases of small, scoped steps, each shipped to `main` as a discrete commit.
Source Material Reality
Anthropic course modules are exported via the course UI's "Copy Notes" button. Despite the name, this button always exports the entire module's notes as one wrapped XML blob — there is no per-topic export. The export shape is:

* A `<notes><critical>...</critical>` envelope containing an instructional preamble ("Use these notes as a resource to answer the user's question. Write your answer as a standalone response — do not refer directly to these notes...")
* Followed by N `<note title="...">...</note>` blocks, each a discrete topic within the module
* Closed by `</notes>`
For intro-to-MCP, this produces 11 notes totaling ~12KB. Per-note bodies range 774–1,406 chars.
This export shape is why v2's planner architecture (step 7) exists. The slicing into pieces has to happen in the pipeline because it can't happen at export time.
Phase 1 (shipped, January–April 2026 apprenticeship era continuing into May)
Phase 1 restructured config and foundation to be brand-aware end to end.
Step 1 — Config restructure to brand-as-object. `engine_config.json` and `config/brands.json` split into two files with different edit cadences. `brands.json` keyed by slug, each brand an object. Empty `content_pillars: []` placeholder added per brand for future Phase 2 use.
Step 2 — Split `BRAND_VOICES.md` into per-brand voice files. Voice files moved under `foundation/voices/`, one per brand.
Step 3 — Rewire `generate_article.py` to v2 config shape. `load_brands()` reads from `brands.json`, loads the matching voice file per brand.
Step 4 — Inject brand URLs from `brands.json`. Closed the URL fabrication problem by injecting authoritative URLs from config with a negative instruction against fabrication. Verified across three runs.
Phase 2 (in progress, May 2026)
Phase 2 is the per-brand-everything migration for the remaining pipeline concerns.
Step 5 — Per-brand content pillar filtering. ✓ SHIPPED
`CONTENT_PILLARS.md` was being injected wholesale into every prompt. Step 5 filters it to only the brand's relevant pillars.
Pillar structure clarified during step 5 investigation: `CONTENT_PILLARS.md` has four H2 sections (`The Five Pillars`, `Topic Taxonomy`, `Engagement Type Definitions`, `Pillar-to-Brand Quick Reference`). The actual pillar blocks are H3s inside `The Five Pillars`. Always-injected scaffolding includes the intro, taxonomy, engagement type definitions, and quick-reference table. Only the H3 pillar blocks are filtered.
Slug rule: lowercase, strip `&`/`,`/`.`, spaces → hyphens, collapse double-hyphens. Produces clean slugs like `build-ship`, `community-ecosystem`, `leadership-risk-governance`.
`content_pillars` populated for all five brands from the quick-reference table (binary list, primary and secondary combined):

* `houston-ai-club`: `build-ship`, `community-ecosystem`
* `amplify-intelligence`: `implementation-playbooks`, `build-ship`, `leadership-risk-governance`
* `amplified-exec`: `implementation-playbooks`, `leadership-risk-governance`
* `leon-coe`: all five (secondary on all per the table)
* `ai-first-work`: `ai-first-work-systems`
Empty `content_pillars` array = inject all (migration-safe default).
Verified across three brand shapes: houston-ai-club (2 pillars, ~32% prompt reduction), ai-first-work (1 pillar), leon-coe (all 5, no-op). All four H2 sections preserved in every case.
Step 6 — `scripts/ingest_module.py` for Anthropic course exports. ✓ SHIPPED
First pass of step 6 ran against a truncated `intro-to-mcp.md` (only the MCP Review note, 622 bytes) and built an ingester that flattened content to prose. Caught during verification: the on-disk file was a fragment, not a full export. File replaced with the real 11-note export (~12KB), ingester rewritten to parse the note structure properly.
Final ingester:

1. Strips the `<notes><critical>...</critical>` envelope and instructional preamble.
2. Parses the body into individual notes by splitting on `<note title="...">` boundaries. Preserves title from the attribute, strips inner `<note>`/`</note>` tags from content.
3. Light cleanup per note: strips remaining XML tags, collapses excess whitespace, preserves sentence breaks, code blocks, and bullet lists.
4. Outputs two files:
   * `intro-to-mcp.normalized.json` — canonical structured input, shape `{"module": "...", "notes": [{"title": "...", "content": "..."}]}`
   * `intro-to-mcp.normalized.md` — human inspection, one H2 per note title
Generator integration: `generate_article.py` handles three input shapes — `.json` (load and concatenate all notes), `.md` with wrappers (run ingester inline), plain `.md` (passthrough).
Note clusters observed in intro-to-MCP that step 7 should be aware of: Defining Resources / Accessing Resources (paired), Defining Prompts / Prompts in the Client (paired), MCP Review (synthesis of all preceding notes). These suggest the planner should be able to recognize that some notes work better as multi-note pieces than as standalone pieces.
Step 7 — `pipeline/plan_pieces.py` (1-source-→-N planner). IN PROGRESS
The 1-source-→-N piece planner. Takes a normalized note set + a brand and produces N piece-plans describing what posts to generate.
Output shape (settled):
json

```json
{
  "module": "intro-to-mcp",
  "generated_at": "ISO timestamp",
  "pieces": [
    {
      "piece_id": "intro-to-mcp_<brand-slug>_<short-descriptor>_<seq>",
      "brand": "<brand-slug>",
      "pillar": "<pillar-slug>",
      "source_notes": ["Note Title 1", ...],
      "angle": "one-sentence framing",
      "title_working": "proposed LinkedIn hook",
      "piece_type": "explainer | listicle | deep_dive | quick_take | tutorial",
      "target_length": 300,
      "cross_brand_link": null,
      "notes": "planner reasoning, freeform"
    }
  ]
}
```

Input shape (settled pending implementation):

* Normalized notes from step 6's JSON
* Module name
* Brand object from `brands.json` — with two new/changed fields:
   * `content_pillars` promoted to structured `{primary: [...], secondary: [...]}` (was a flat binary list in step 5; step 7 is the first consumer that benefits from the distinction)
   * `voice_summary` — new explicit one-sentence string per brand describing audience and tone, for planner-level angle selection. Full voice file remains a generation-time concern.
* Filtered pillars from `filter_pillars()`
Open question (next): model-assisted vs deterministic planner architecture. Current lean: hybrid — deterministic filtering and grouping, model-assisted angle/title generation per group.
Step 8 — Source-aware humanizer. NOT STARTED
The humanizer currently runs on generated content without awareness of where the source material came from or what the piece type is. Step 8 makes humanizer intensity and style context-aware per brand and piece type.
Step 9 — `scripts/batch_run.py`. NOT STARTED
The batch orchestrator. Runs the full pipeline (ingest → plan → generate → humanize) for one or more sources across one or more brands. Outputs ready-to-publish pieces.
Architectural Patterns
A few patterns established by Phase 1 and carried through Phase 2:

* `brands.json` is the runtime source of truth for anything brand-specific. Markdown foundation files are human-readable documentation that should match but aren't authoritative.
* Empty-array-means-all as a migration-safe default. Empty `content_pillars: []` injects all pillars; same pattern likely applicable to future filter fields.
* Sibling-file normalization. Ingested/normalized outputs live next to raw inputs (`intro-to-mcp.md` + `intro-to-mcp.normalized.json`). Inspectable, re-runnable, preserves originals.
* Direct-to-main commits, no feature branches. Solo repo, fast iteration, Claude Code commits each step directly to `main`.
* Dry-run verification before live runs. Each step verifies its prompt assembly or output shape via local dry-run before any OpenRouter call is made.
Tooling

* Claude Code Pro: all repo-level execution and commits
* Claude (chat): design discussions, planning, decision-making
* Anthropic course modules: source material, accessed via course UI's "Copy Notes" export
* OpenRouter: model API endpoint for generation (budget-tracked, ~$20/month soft cap)
* GitHub Actions: cron-driven scheduled runs (inherited pattern from Houston Engine)
