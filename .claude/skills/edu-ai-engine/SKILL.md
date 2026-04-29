---
name: edu-ai-engine
description: Pipeline that turns course-module summaries and research notes into draft articles and posts for Jackson's five brands, via OpenRouter, with a mandatory humanizer pass and human review before publish.
---

## Scripts
- `pipeline/generate_article.py` — takes a source .md + brand, outputs article
- `pipeline/generate_post.py` — takes a source .md + brand, outputs short post
- `pipeline/humanizer.py` — runs humanizer pass on generated content
- `scripts/ingest_module.py` — ingests a course module summary into queue
- `scripts/batch_run.py` — runs full pipeline on all pending source material

## Environment Variables
- `OPENROUTER_API_KEY` — stored in `.env` and GitHub Actions secret

## Output Structure
output/articles/[brand-slug]/YYYY-MM-DD_[slug].md
output/posts/[brand-slug]/YYYY-MM-DD_[slug].md

## Brand Slugs
- houston-ai-club
- amplify-intelligence
- amplified-exec
- leon-coe
- ai-first-work

## Rules
- Never auto-publish — all output is draft only
- Humanizer pass runs on every piece before saving
- Amplified Exec content flagged for Leon review in output frontmatter
- No hype language (see HUMANIZER_GUIDELINES.md banned phrases)
- OpenRouter is the API layer — not direct Anthropic or OpenAI calls
