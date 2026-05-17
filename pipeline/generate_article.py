"""Generate a long-form draft article from a source .md + brand."""

import argparse
import json
import os
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

import requests
from dotenv import load_dotenv

REPO_ROOT = Path(__file__).resolve().parent.parent
CONFIG_PATH = REPO_ROOT / "config" / "engine_config.json"
BRANDS_PATH = REPO_ROOT / "config" / "brands.json"
FOUNDATION_DIR = REPO_ROOT / "foundation"
OUTPUT_DIR = REPO_ROOT / "output" / "articles"
OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"


def slugify(text: str) -> str:
    text = text.lower().strip()
    text = re.sub(r"[^a-z0-9\s-]", "", text)
    text = re.sub(r"[\s_-]+", "-", text)
    return text.strip("-")


def load_config() -> dict:
    return json.loads(CONFIG_PATH.read_text(encoding="utf-8"))


def load_brands() -> dict:
    return json.loads(BRANDS_PATH.read_text(encoding="utf-8"))


def slug_to_display(brands: dict) -> dict:
    return {slug: brands["brands"][slug]["display_name"] for slug in brands["brands"]}


def extract_brand_voice(brand_slug: str, config: dict) -> str:
    voice_path = REPO_ROOT / config["brands"][brand_slug]["voice_file"]
    return voice_path.read_text(encoding="utf-8")


def filter_pillars(pillars_md: str, allowed_slugs: list) -> str:
    """Inside ## The Five Pillars, keep only H3 blocks whose slug is in allowed_slugs.

    Slug rule: H3 heading with the 'Pillar N — ' prefix stripped, lowercased,
    spaces replaced with hyphens. Empty allowed_slugs returns the file unchanged
    (migration-safe default). All other sections of the file are preserved.
    """
    if not allowed_slugs:
        return pillars_md

    allowed = set(allowed_slugs)

    h2_match = re.search(r"^## The Five Pillars\s*$", pillars_md, re.MULTILINE)
    if not h2_match:
        return pillars_md

    section_start = h2_match.start()
    next_h2 = re.search(r"^## ", pillars_md[h2_match.end():], re.MULTILINE)
    section_end = h2_match.end() + next_h2.start() if next_h2 else len(pillars_md)
    section = pillars_md[section_start:section_end]

    h3_matches = list(re.finditer(r"^### Pillar \d+ — (.+)$", section, re.MULTILINE))
    if not h3_matches:
        return pillars_md

    prefix = section[:h3_matches[0].start()]
    kept = []
    for i, m in enumerate(h3_matches):
        heading = m.group(1).strip()
        cleaned = re.sub(r"[&,.]", "", heading).lower()
        slug = re.sub(r"-+", "-", cleaned.replace(" ", "-")).strip("-")
        block_end = h3_matches[i + 1].start() if i + 1 < len(h3_matches) else len(section)
        if slug in allowed:
            kept.append(section[m.start():block_end])

    filtered_section = prefix + "".join(kept)
    return pillars_md[:section_start] + filtered_section + pillars_md[section_end:]


def build_url_section(brand_slug: str, brands: dict) -> str:
    brand = brands["brands"][brand_slug]
    urls = brand["urls"]
    present = [(k, v) for k, v in urls.items() if v is not None]
    if not present:
        return ""
    lines = [f"{brand['display_name']}'s verified URLs (use verbatim, never modify, never invent):"]
    for k, v in present:
        lines.append(f"- {k}: {v}")
    lines.append("")
    lines.append(
        "These are the only verified URLs for this brand. Do not include URLs "
        "in any other category (Twitter/X, secondary CTAs, etc.) — if a category "
        "isn't listed above, that brand does not have a public URL for it."
    )
    return "\n".join(lines)


def build_messages(
    source_text: str,
    brand_slug: str,
    brand_display: str,
    target_words: int,
    config: dict,
    brands: dict,
) -> list:
    voice = extract_brand_voice(brand_slug, config)
    url_section = build_url_section(brand_slug, brands)
    pillars_raw = (FOUNDATION_DIR / "CONTENT_PILLARS.md").read_text(encoding="utf-8")
    brand_pillar_slugs = brands["brands"][brand_slug].get("content_pillars", [])
    pillars = filter_pillars(pillars_raw, brand_pillar_slugs)
    humanizer_rules = (FOUNDATION_DIR / "HUMANIZER_GUIDELINES.md").read_text(encoding="utf-8")

    voice_block = f"BRAND VOICE — follow strictly:\n\n{voice}"
    if url_section:
        voice_block = f"{voice_block}\n\n{url_section}"

    system = (
        f"You are an expert content writer producing a long-form LinkedIn article "
        f"for the brand '{brand_display}'. Write in markdown. Target length: ~{target_words} words.\n\n"
        f"{voice_block}\n\n"
        f"CONTENT PILLARS — map the article to the most natural-fit pillar:\n\n{pillars}\n\n"
        f"HUMANIZER RULES — apply during drafting; never use banned phrases:\n\n{humanizer_rules}"
    )
    user = (
        "Generate a complete, ready-to-edit article based on this source material. "
        "Open with a hook that sounds like a real person. Include at least one concrete "
        "example. Vary sentence length. End with a brand-appropriate CTA. "
        "Output ONLY the article in markdown — no commentary, no preamble.\n\n"
        f"--- SOURCE MATERIAL ---\n\n{source_text}"
    )
    return [
        {"role": "system", "content": system},
        {"role": "user", "content": user},
    ]


def call_openrouter(messages: list, model: str, max_tokens: int, api_key: str) -> tuple:
    headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
    payload = {"model": model, "messages": messages, "max_tokens": max_tokens}
    r = requests.post(OPENROUTER_URL, headers=headers, json=payload, timeout=180)
    r.raise_for_status()
    data = r.json()
    return data["choices"][0]["message"]["content"], data


def derive_slug(source_path: Path, content: str) -> str:
    m = re.search(r"^#\s+(.+)$", content, re.MULTILINE)
    if m:
        candidate = slugify(m.group(1))[:60]
        if candidate:
            return candidate
    return slugify(source_path.stem)


def build_frontmatter(brand_slug: str, brand_display: str, source_path: Path) -> str:
    review = "leon" if brand_slug == "amplified-exec" else "standard"
    generated_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
    return (
        "---\n"
        f"brand: {brand_slug}\n"
        f"brand_display: {brand_display}\n"
        f"source: {source_path.as_posix()}\n"
        f"generated_at: {generated_at}\n"
        f"format: article\n"
        f"status: draft\n"
        f"review: {review}\n"
        "---\n\n"
    )


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Generate a long-form article from a source .md + brand."
    )
    parser.add_argument("--source", required=True, help="Path to source .md")
    parser.add_argument(
        "--brand",
        required=True,
        help="Brand slug (e.g., 'ai-first-work'). One of: houston-ai-club, amplify-intelligence, amplified-exec, leon-coe, ai-first-work",
    )
    args = parser.parse_args()

    load_dotenv(REPO_ROOT / ".env")
    api_key = os.environ.get("OPENROUTER_API_KEY")
    if not api_key or api_key == "your_key_here":
        print("error: OPENROUTER_API_KEY not set in .env", file=sys.stderr)
        return 1

    config = load_config()
    brands = load_brands()

    config_slugs = set(config["brands"].keys())
    brands_slugs = set(brands["brands"].keys())
    if config_slugs != brands_slugs:
        only_in_config = sorted(config_slugs - brands_slugs)
        only_in_brands = sorted(brands_slugs - config_slugs)
        print(
            "error: brand slug mismatch between engine_config.json and brands.json.\n"
            f"  only in engine_config.json: {only_in_config}\n"
            f"  only in brands.json:       {only_in_brands}",
            file=sys.stderr,
        )
        return 1

    brand_map = slug_to_display(brands)
    if args.brand not in brand_map:
        print(
            f"error: '{args.brand}' is not a valid brand slug. Choose from: {sorted(brand_map)}",
            file=sys.stderr,
        )
        return 1
    brand_display = brand_map[args.brand]

    source_path = Path(args.source).resolve()
    if not source_path.is_file():
        print(f"error: source file not found: {source_path}", file=sys.stderr)
        return 1

    print(f"[1/5] source loaded: {source_path}")
    source_text = source_path.read_text(encoding="utf-8")

    sys.path.insert(0, str(REPO_ROOT / "scripts"))
    from ingest_module import normalize

    source_text, removed, ambiguous = normalize(source_text)
    if removed:
        print(f"      ingester stripped {len(removed)} wrapper/instruction sentence(s)")
    if ambiguous:
        print(f"      ingester flagged {len(ambiguous)} ambiguous sentence(s) (stripped, review)")

    print(f"[2/5] prompt built for brand: {args.brand} ({brand_display})")
    target_words = config["brands"][args.brand]["article_target_length"]
    messages = build_messages(source_text, args.brand, brand_display, target_words, config, brands)

    print(f"[3/5] calling OpenRouter ({config['model']})")
    try:
        article, response = call_openrouter(messages, config["model"], config["max_tokens"], api_key)
    except requests.HTTPError as e:
        status = e.response.status_code if e.response is not None else "?"
        body = e.response.text if e.response is not None else ""
        print(f"error: OpenRouter HTTP {status}: {body}", file=sys.stderr)
        return 1
    except requests.RequestException as e:
        print(f"error: OpenRouter request failed: {e}", file=sys.stderr)
        return 1

    usage = response.get("usage") or {}
    prompt_tok = usage.get("prompt_tokens", "?")
    completion_tok = usage.get("completion_tokens", "?")
    total_tok = usage.get("total_tokens", "?")
    cost = usage.get("cost") or response.get("total_cost")
    cost_str = f", cost=${cost:.6f}" if isinstance(cost, (int, float)) else ""
    print(f"      usage: prompt={prompt_tok}, completion={completion_tok}, total={total_tok}{cost_str}")

    sys.path.insert(0, str(Path(__file__).parent))
    from humanizer import humanize

    print("[4/5] humanizer pass")
    intensity = config["brands"][args.brand]["humanizer_intensity"]
    article = humanize(article, intensity=intensity, brand=args.brand)

    out_dir = OUTPUT_DIR / args.brand
    out_dir.mkdir(parents=True, exist_ok=True)
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    out_path = out_dir / f"{today}_{derive_slug(source_path, article)}.md"
    out_path.write_text(
        build_frontmatter(args.brand, brand_display, source_path) + article.strip() + "\n",
        encoding="utf-8",
    )
    print(f"[5/5] wrote {out_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
