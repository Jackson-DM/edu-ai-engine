# edu-ai-engine — Pipeline v2 Design

**Status:** Draft  
**Date:** 2026-05-11  
**Context:** Drafted after v1 smoke test (2026-05-12 UTC) on Houston AI Club + `intro-to-mcp.md`.

---

## Why v2

The v1 pipeline ran end-to-end successfully on its first smoke test. It produced a markdown article in the right brand folder, the OpenRouter API call worked, the humanizer ran two passes, and total cost came in at roughly $0.10 per article. Mechanically, the pipeline works.

But reading the output critically revealed three structural problems that no amount of prompt tuning fixes cleanly:

1. **The source contract is wrong.** v1 assumes one source file = one focused topic. The actual source format (Anthropic's "Copy notes" export) is one file = an entire course wrapped in instruction tags meant for a different consumer. The generator inherited those instructions and skipped the source content.

2. **Brand identity is fragmented across three places.** Display name lives in `engine_config.json`, the H2 header lives in `BRAND_VOICES.md`, and the slug is derived at runtime via `slugify()`. Renames silently break. There's no single source of truth per brand.

3. **Per-brand URLs don't exist as data.** The model invented `https://houstonai.club` because nothing in the pipeline provided a real URL. This is fixable structurally, not via prompts.

v2 addresses all three by changing the underlying contracts rather than patching prompts on top of a broken foundation.

---

## Core design shift

| Aspect | v1 | v2 |
|---|---|---|
| Source contract | 1 file = 1 article | 1 file = body of knowledge → N pieces |
| Brand representation | String, three loose references | First-class config object keyed by slug |
| URLs | Not in the system | Structured fields on the brand object |
| Pillar injection | All pillars, model picks | Filtered to the brand's relevant pillars |
| Length / model config | Global only | Per-brand overrides supported |
| BRAND_VOICES.md | One file, regex-extracted | Split into per-brand voice files |

The unifying idea: **promote brand and source from strings to structured objects**, then let the generation step decide how to slice a source into pieces appropriate for each brand.

---

## New pipeline stages

### 1. Ingestion (`scripts/ingest_module.py` — to build)

**Input:** A raw Anthropic "Copy notes" markdown dump (or any similar structured source).

**What it does:**
- Strips hostile wrapper tags (`<notes>`, `<critical>`, etc.) that are meant for a different AI consumer
- Parses out individual `<note title="...">` blocks
- Builds a structured representation: `[{title, content}, ...]`
- Saves the cleaned, parsed source as a normalized JSON or markdown sidecar

**Why this stage exists:** The current source file at `source-material/anthropic-courses/intro-to-mcp.md` contains instructions that actively prevent the generator from teaching from it. Ingestion is where we neutralize that mismatch.

### 2. Topic planning (new — `pipeline/plan_pieces.py`)

**Input:** A normalized source + a target brand (or set of brands).

**What it does:**
- Reviews the available notes/sections
- Proposes N article angles and M post angles per brand
- Filters proposed angles by the brand's `content_pillars`
- Outputs a plan: `[{brand_slug, format, angle, source_notes: [titles]}, ...]`

**Why this stage exists:** v1 conflates "what should this become" with "write it." Separating planning from generation lets you review the plan before spending tokens, and makes the 1-source-→-N-pieces architecture explicit rather than implicit.

### 3. Generation (`pipeline/generate_article.py`, `pipeline/generate_post.py`)

**Input:** A single plan entry + the relevant source notes.

**What it does:**
- Loads the brand object from config
- Builds a system prompt with: the brand's voice file (only that brand's), filtered pillar guidance, humanizer rules, and the brand's structured URL set with instructions to use them verbatim
- Calls OpenRouter
- Passes the draft to the humanizer

**Key change from v1:** Only the relevant source notes are included — not the entire source file. This reduces token cost and improves grounding.

### 4. Humanization (`pipeline/humanizer.py` — modified)

**Input:** A draft + the source notes it was generated from.

**What changes from v1:** The humanizer now sees the source notes. Pass 2 can audit not just for AI tells but for fabrication — invented anecdotes, statistics, or URLs that aren't in the source. The audit prompt expands from "does this sound AI?" to "is this faithful to the source?"

### 5. Output (`pipeline/format_and_save.py` — new utility)

Same as v1's output step, plus frontmatter now includes: `source_notes_used`, `plan_id`, `angle`, and per-piece token/cost data.

### 6. Batch runner (`scripts/batch_run.py` — to build)

Coordinates the above stages across a queue. Reads a planning file, runs through each plan entry, tracks completion, logs costs, supports filters (`--brand`, `--format`, `--source`).

---

## Brand as a first-class config object

### Current shape

`engine_config.json` treats brand as a flat string in a list, with separate parallel structures (`humanizer_intensity` keyed by display name). `BRAND_VOICES.md` has H2 headers that must match those display names exactly. `generate_article.py` derives slugs at runtime via `slugify()`.

### v2 shape

Brand becomes a structured object keyed by slug:

```json
"brands": {
  "houston-ai-club": {
    "display_name": "Houston AI Club",
    "voice_file": "foundation/voices/houston-ai-club.md",
    "urls": {
      "linkedin": "https://linkedin.com/company/houston-ai-club",
      "website": "https://houstonaiclub.com",
      "twitter": null,
      "cta_primary": "https://houstonaiclub.com/events"
    },
    "humanizer_intensity": "light",
    "article_target_length": 800,
    "post_target_length": 250,
    "content_pillars": [
      "community-ecosystem",
      "implementation-playbooks",
      "build-ship"
    ]
  }
}
```

### What this enables

- **Renames are safe.** Display name is a field; slug is the identity.
- **URLs are data.** The generator injects them as `"You must use these exact URLs. Do not invent URLs."`. Fabrication path closes.
- **Per-brand overrides.** Amplified Exec articles can target 1200 words at higher humanizer intensity without touching code.
- **Filtered pillar injection.** Houston AI Club's prompt sees only its three pillars, not all five. System prompt shrinks from ~36k chars to ~12k. Token cost drops proportionally on batch runs.

### BRAND_VOICES.md migration

Split into `foundation/voices/<slug>.md` files. The brand object's `voice_file` field points at the correct file. Regex extraction goes away — replaced by a direct file read.

---

## What stays the same

- Sonnet 4.5 via OpenRouter, same auth pattern
- Two-pass humanizer architecture (just with source-awareness added)
- Output paths: `output/articles/<slug>/` and `output/posts/<slug>/`
- `.env` for secrets
- Markdown frontmatter at the top of each generated piece

---

## Open questions to resolve before building

1. **URL inventory.** Need confirmed canonical URLs from Leon for all five brands: LinkedIn, website, primary CTA destination, Twitter/X if applicable. Without this, URL injection can't go live.

2. **How many pieces per source?** Auto-decided by the planner, or capped per brand? Initial proposal: planner suggests up to 3 articles and up to 5 posts per brand per source, human approves the plan before generation.

3. **Cross-brand or single-brand runs?** Should `batch_run.py --source X` generate for all five brands automatically, or default to single-brand with `--brand` required? Initial proposal: single-brand default, `--all-brands` flag for the full sweep.

4. **Topic deduplication across runs.** When the second course gets ingested, how does the planner know not to repeat angles already generated? Initial proposal: each piece's frontmatter records its angle; planner reads existing output before proposing new angles.

5. **Pillar definitions.** `CONTENT_PILLARS.md` is currently injected wholesale. For filtered injection to work, pillars need to be addressable by slug (`community-ecosystem`, `implementation-playbooks`, etc.). Either restructure that file or add a parsing layer.

6. **Per-brand model overrides?** Should Amplified Exec use Opus while Houston AI Club uses Sonnet? Not blocking for v2, but the brand-object structure should accommodate this if needed later.

---

## Migration order

Sequenced so each step is independently verifiable:

1. **Build the brand config object.** Restructure `engine_config.json`. Don't change pipeline code yet. Verify the JSON parses cleanly and all five brands are represented.
2. **Split BRAND_VOICES.md.** Create `foundation/voices/<slug>.md` for each brand. Leave the original file in place temporarily.
3. **Rewrite `extract_brand_voice()` to read from `voice_file`.** Verify v1 smoke test still passes against the new structure.
4. **Add URL injection to the system prompt.** Re-run smoke test. Verify the generated article uses the real URL, not a fabricated one.
5. **Build pillar filtering.** Restructure `CONTENT_PILLARS.md` or add a parser. Inject only the brand's pillars. Verify article voice/angle didn't regress.
6. **Build `scripts/ingest_module.py`.** Test on the existing `intro-to-mcp.md`. Output: ~11 normalized note objects.
7. **Build `pipeline/plan_pieces.py`.** Test on the ingested course. Output: a plan file with proposed angles per brand.
8. **Wire humanizer source-awareness.** Pass relevant notes to pass 2. Verify fabrication audit works on a deliberately fabrication-prone test.
9. **Build `scripts/batch_run.py`.** End-to-end test on one source + one brand. Then one source + all brands.

Steps 1–4 alone close the URL fabrication problem and lay the structural foundation. Steps 5–9 unlock the 1-source-→-N-pieces architecture. v2 can ship in two phases if needed.

---

## What we're not doing in v2

- Cross-source synthesis (one article drawing from two different courses). Possible later; not in scope.
- Auto-publishing to LinkedIn. Manual review remains the gate.
- Image generation. Articles stay text-only.
- Auto-routing source to brand based on topic. Brand selection stays explicit.
- Multi-model fallback. Sonnet 4.5 only for now.
