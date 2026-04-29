# edu-ai-engine

A practical AI content engine that produces high-quality, educational articles and posts across five brands — grounded in structured course material, deep research, and real-world AI knowledge.

## What This Engine Does

The `edu-ai-engine` generates two types of content:

- **Long-form LinkedIn articles** — deep dives, how-to guides, explainers, and practical playbooks
- **Short-form LinkedIn posts** — quick tips, frameworks, tool comparisons, and tactical takeaways

All content is sourced from two foundational inputs:

1. **Anthropic course module summaries** — structured markdown summaries of Anthropic's free AI courses, each processed into article briefs
2. **Research foundation** — a deep research report mapping the full practical AI topic universe (trending + evergreen), competitive landscape, audience intelligence, and content strategy

## Brands Served

| Brand | Voice | Audience |
|---|---|---|
| Houston AI Club | Approachable, community-driven | AI enthusiasts & Houston professionals |
| Amplify Intelligence | Authoritative, results-oriented | Business leaders & transformation teams |
| Amplified Exec | Concise, high-stakes | C-suite & senior leadership |
| Leon Coe (Personal) | Candid, opinionated | Mixed technical + non-technical |
| AI First Work | Practical, energetic | Professionals adapting to AI-first work |

## Repo Structure

```
edu-ai-engine/
├── foundation/                  # Core strategy & brand voice docs
│   ├── BRAND_VOICES.md          # Voice, tone, CTA map per brand
│   ├── CONTENT_PILLARS.md       # The 5 content pillars + topic taxonomy
│   └── HUMANIZER_GUIDELINES.md  # Rules for humanizing AI-generated content
│
├── source-material/
│   ├── anthropic-courses/       # One .md file per course module summary
│   └── research/                # Deep research report + supplementary research
│       └── RESEARCH_FOUNDATION.md
│
├── pipeline/                    # Content generation scripts
│   ├── generate_article.py      # Long-form article generator
│   ├── generate_post.py         # Short-form post generator
│   └── humanizer.py             # Humanizer pass on generated content
│
├── scripts/                     # Utility scripts
│   ├── ingest_module.py         # Ingests a course module summary into pipeline
│   └── batch_run.py             # Runs full pipeline on all pending source material
│
├── output/
│   ├── articles/                # Generated long-form articles (by brand)
│   └── posts/                   # Generated short-form posts (by brand)
│
├── config/
│   └── engine_config.json       # Model, brand settings, output preferences
│
├── docs/
│   └── PIPELINE_OVERVIEW.md     # How the pipeline works end to end
│
└── .github/
    └── workflows/
        └── weekly_run.yml       # GitHub Actions — weekly automated content run
```

## Content Pillars

1. **Implementation Playbooks** — roadmaps, agent adoption, governance, evaluation
2. **AI-First Work Systems** — workflows, productivity, tool selection, role routines
3. **Build & Ship** — AI-assisted development, prompt-to-code, vibe coding
4. **Leadership, Risk & Governance** — responsible AI, policy, board-level strategy
5. **Community & Ecosystem** — member stories, event recaps, curated learning paths

## How to Run

```bash
# Install dependencies
pip install -r requirements.txt

# Generate a single article from a course module
python pipeline/generate_article.py --source source-material/anthropic-courses/MODULE_NAME.md --brand "AI First Work"

# Generate a short-form post
python pipeline/generate_post.py --source source-material/anthropic-courses/MODULE_NAME.md --brand "Leon Coe"

# Run full batch on all pending source material
python scripts/batch_run.py
```

## Configuration

Edit `config/engine_config.json` to set:
- Default model (OpenRouter)
- Brand voice overrides
- Output preferences (format, length targets)
- Humanizer intensity settings

## Source Material

### Adding an Anthropic Course Module

1. Complete or review the module on [Anthropic's courses](https://www.anthropic.com/learn)
2. Summarize the module content in a new `.md` file under `source-material/anthropic-courses/`
3. Follow the module summary template in `docs/PIPELINE_OVERVIEW.md`
4. Run `python scripts/ingest_module.py --file YOUR_MODULE.md` to queue it for generation

### Research Foundation

The deep research report lives at `source-material/research/RESEARCH_FOUNDATION.md`. This is the strategic backbone of the engine — topic taxonomy, trending + evergreen topic maps, audience intelligence, competitive landscape, and content format guidance.

---

*Part of the Amplify Intelligence content stack. Related: [houston-engine](https://github.com/Jackson-DM/houston-engine)*
