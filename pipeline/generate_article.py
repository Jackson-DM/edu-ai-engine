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


def slug_to_display(config: dict) -> dict:
    return {slugify(b): b for b in config["brands"]}


def extract_brand_voice(brand: str) -> str:
    text = (FOUNDATION_DIR / "BRAND_VOICES.md").read_text(encoding="utf-8")
    pattern = rf"^## {re.escape(brand)}\b.*?(?=^## |\Z)"
    match = re.search(pattern, text, re.DOTALL | re.MULTILINE)
    if not match:
        raise ValueError(f"Brand voice section for '{brand}' not found in BRAND_VOICES.md")
    return match.group(0).strip()


def build_messages(source_text: str, brand_display: str, target_words: int) -> list:
    voice = extract_brand_voice(brand_display)
    pillars = (FOUNDATION_DIR / "CONTENT_PILLARS.md").read_text(encoding="utf-8")
    humanizer_rules = (FOUNDATION_DIR / "HUMANIZER_GUIDELINES.md").read_text(encoding="utf-8")

    system = (
        f"You are an expert content writer producing a long-form LinkedIn article "
        f"for the brand '{brand_display}'. Write in markdown. Target length: ~{target_words} words.\n\n"
        f"BRAND VOICE — follow strictly:\n\n{voice}\n\n"
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


def call_openrouter(messages: list, model: str, max_tokens: int, api_key: str) -> str:
    headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
    payload = {"model": model, "messages": messages, "max_tokens": max_tokens}
    r = requests.post(OPENROUTER_URL, headers=headers, json=payload, timeout=180)
    r.raise_for_status()
    return r.json()["choices"][0]["message"]["content"]


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
    brand_map = slug_to_display(config)
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

    print(f"[2/5] prompt built for brand: {args.brand} ({brand_display})")
    messages = build_messages(source_text, brand_display, config["article_target_length"])

    print(f"[3/5] calling OpenRouter ({config['model']})")
    try:
        article = call_openrouter(messages, config["model"], config["max_tokens"], api_key)
    except requests.HTTPError as e:
        status = e.response.status_code if e.response is not None else "?"
        body = e.response.text if e.response is not None else ""
        print(f"error: OpenRouter HTTP {status}: {body}", file=sys.stderr)
        return 1
    except requests.RequestException as e:
        print(f"error: OpenRouter request failed: {e}", file=sys.stderr)
        return 1

    sys.path.insert(0, str(Path(__file__).parent))
    from humanizer import humanize

    print("[4/5] humanizer pass")
    intensity = config["humanizer_intensity"][brand_display]
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
