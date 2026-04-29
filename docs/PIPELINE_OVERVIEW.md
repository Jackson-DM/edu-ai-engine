# Pipeline Overview

This document explains how the edu-ai-engine works end to end — from source material input to publishable content output.

---

## Pipeline Flow

```
Source Material
    │
    ├── Anthropic Course Modules (source-material/anthropic-courses/)
    └── Research Foundation (source-material/research/)
         │
         ▼
    Ingest & Queue
    (scripts/ingest_module.py)
         │
         ▼
    Content Brief Generation
    (topic + angle + brand assignment)
         │
         ▼
    Article / Post Generation
    (pipeline/generate_article.py or generate_post.py)
         │
         ▼
    Humanizer Pass
    (pipeline/humanizer.py)
         │
         ▼
    Output
    (output/articles/ or output/posts/)
         │
         ▼
    Human Review → Publish
```

---

## Source Material

### Anthropic Course Modules

Each completed Anthropic course module gets summarized into a markdown file in `source-material/anthropic-courses/`. These summaries are the raw input for the pipeline.

**Module Summary Template:**

```markdown
# Module: [Module Name]
**Course:** [Course Name]
**Completed:** [Date]

## Key Concepts
- [Concept 1]
- [Concept 2]
- [Concept 3]

## Main Takeaways
[2-3 paragraph summary of what the module covers and why it matters]

## Practical Applications
[What can someone actually DO with this knowledge? Workflows, use cases, examples]

## Audience Relevance
- **Technical:** [How this applies to developers/engineers]
- **Non-technical:** [How this applies to business users/executives]

## Content Angles
[3-5 specific article or post ideas that could be extracted from this module]

## Raw Notes
[Any additional notes, quotes, or details worth preserving]
```

---

## Configuration

### engine_config.json

```json
{
  "model": "openrouter/anthropic/claude-sonnet-4-5",
  "max_tokens": 4000,
  "brands": [
    "Houston AI Club",
    "Amplify Intelligence",
    "Amplified Exec",
    "Leon Coe",
    "AI First Work"
  ],
  "output_formats": ["article", "post"],
  "humanizer_intensity": {
    "Houston AI Club": "light",
    "Amplify Intelligence": "medium",
    "Amplified Exec": "heavy",
    "Leon Coe": "medium",
    "AI First Work": "light"
  },
  "article_target_length": 800,
  "post_target_length": 250
}
```

---

## Output Structure

All generated content lands in `output/` organized by type and brand:

```
output/
├── articles/
│   ├── houston-ai-club/
│   ├── amplify-intelligence/
│   ├── amplified-exec/
│   ├── leon-coe/
│   └── ai-first-work/
└── posts/
    ├── houston-ai-club/
    ├── amplify-intelligence/
    ├── amplified-exec/
    ├── leon-coe/
    └── ai-first-work/
```

Each output file is named: `YYYY-MM-DD_[slug].md`

---

## GitHub Actions — Weekly Run

The `.github/workflows/weekly_run.yml` workflow runs every Monday at 8am CT and:

1. Checks for any new source material added since the last run
2. Generates one article and one post per new module, assigned to the most relevant brand
3. Commits output files to the `output/` directory
4. Opens a draft PR for human review before publish

Manual trigger is also available via `workflow_dispatch`.

---

## Human Review Before Publish

The pipeline does not auto-publish. Every generated piece goes through:

1. **Automated humanizer pass** (pipeline/humanizer.py)
2. **Human review** — check against `HUMANIZER_GUIDELINES.md`
3. **Brand approval** — Amplified Exec requires Leon sign-off
4. **Publish** — manually scheduled via LinkedIn or Buffer
