"""Normalize a raw Anthropic course module export into clean markdown.

Strips wrapper XML tags and embedded model-instruction sentences from a raw
export, then applies light readability cleanup (sentence spacing, paragraph
breaks at clear topic shifts). Idempotent: running on an already-normalized
file is a no-op.

CLI:
    python scripts/ingest_module.py --source <path/to/raw.md>

Writes <stem>.normalized.md to the same directory.
"""

import argparse
import re
import sys
from pathlib import Path


XML_TAG_RE = re.compile(r"<[^>]+>")

INSTRUCTION_PREFIXES = (
    "below are notes from",
    "use these notes as a resource",
    "write your answer as a standalone response",
)

AMBIGUOUS_EXACT = frozenset({"serve users.", "serve users"})

TOPIC_STARTERS = ("Real examples:",)


def _add_sentence_spaces(text: str) -> str:
    return re.sub(r"([.!?])([A-Z])", r"\1 \2", text)


def _split_sentences(text: str) -> list:
    text = _add_sentence_spaces(text)
    parts = re.split(r"(?<=[.!?])\s+", text)
    return [p.strip() for p in parts if p.strip()]


def _classify(sentence: str) -> str:
    lower = sentence.strip().lower()
    if lower in AMBIGUOUS_EXACT:
        return "ambiguous"
    for prefix in INSTRUCTION_PREFIXES:
        if lower.startswith(prefix):
            return "instruction"
    return "content"


def _paragraphize(sentences: list) -> str:
    paragraphs = []
    current = []
    for s in sentences:
        if current and s.startswith(TOPIC_STARTERS):
            paragraphs.append(" ".join(current))
            current = [s]
        else:
            current.append(s)
    if current:
        paragraphs.append(" ".join(current))
    return "\n\n".join(paragraphs)


def normalize(text: str) -> tuple:
    """Return (cleaned_text, removed_instructions, ambiguous_sentences)."""
    text = XML_TAG_RE.sub("", text)
    text = re.sub(r"[ \t]+", " ", text)
    sentences = _split_sentences(text)

    kept, removed, ambiguous = [], [], []
    for s in sentences:
        cat = _classify(s)
        if cat == "instruction":
            removed.append(s)
        elif cat == "ambiguous":
            ambiguous.append(s)
        else:
            kept.append(s)

    return _paragraphize(kept), removed, ambiguous


def main() -> int:
    parser = argparse.ArgumentParser(description="Normalize a raw course module export.")
    parser.add_argument("--source", required=True, help="Path to raw .md export")
    args = parser.parse_args()

    src = Path(args.source).resolve()
    if not src.is_file():
        print(f"error: source file not found: {src}", file=sys.stderr)
        return 1

    raw = src.read_text(encoding="utf-8")
    cleaned, removed, ambiguous = normalize(raw)

    out_path = src.parent / f"{src.stem}.normalized.md"
    out_path.write_text(cleaned + "\n", encoding="utf-8")

    print(f"wrote {out_path}")
    if removed:
        print(f"stripped {len(removed)} instructional sentence(s):")
        for s in removed:
            print(f"  - {s}")
    if ambiguous:
        print(f"flagged {len(ambiguous)} ambiguous sentence(s) (stripped, review):")
        for s in ambiguous:
            print(f"  - {s}")
    if not removed and not ambiguous:
        print("no instructional or ambiguous content detected (input may already be normalized)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
