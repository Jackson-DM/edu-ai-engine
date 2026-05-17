"""Normalize a raw Anthropic course module export into structured notes.

Input shape (intro-to-mcp.md and similar):
    <notes>
      <critical>...preamble for the downstream model, to be discarded...</critical>
      <note title="...">...</note>
      <note title="...">...</note>
      ...
    </notes>

Output:
    <stem>.normalized.json — {"module": str, "source": str, "notes": [{"title": str, "content": str}, ...]}
    <stem>.normalized.md   — one H2 block per note, for human inspection

CLI:
    python scripts/ingest_module.py --source <path/to/raw.md>
"""

import argparse
import json
import re
import sys
from pathlib import Path


CRITICAL_BLOCK_RE = re.compile(r"<critical>.*?</critical>", re.DOTALL)
NOTE_BLOCK_RE = re.compile(r'<note\s+title="([^"]+)">(.*?)</note>', re.DOTALL)
ANY_TAG_RE = re.compile(r"<[^>]+>")


def _clean_note_content(content: str) -> str:
    """Strip stray tags, trim trailing line whitespace, collapse 2+ blank lines to 1."""
    content = ANY_TAG_RE.sub("", content)
    lines = [ln.rstrip() for ln in content.splitlines()]
    while lines and not lines[0].strip():
        lines.pop(0)
    while lines and not lines[-1].strip():
        lines.pop()
    out = []
    blank = 0
    for ln in lines:
        if not ln.strip():
            blank += 1
            if blank <= 1:
                out.append("")
        else:
            blank = 0
            out.append(ln)
    return "\n".join(out)


def normalize(text: str) -> dict:
    """Parse a raw module export into structured notes.

    Returns a dict with:
        notes: list of {"title": str, "content": str}
        stripped_preamble: str — the contents of <critical>...</critical>, for reporting
    """
    critical = CRITICAL_BLOCK_RE.search(text)
    stripped_preamble = critical.group(0)[len("<critical>"):-len("</critical>")].strip() if critical else ""
    body = CRITICAL_BLOCK_RE.sub("", text)

    notes = [
        {"title": m.group(1).strip(), "content": _clean_note_content(m.group(2))}
        for m in NOTE_BLOCK_RE.finditer(body)
    ]
    return {"notes": notes, "stripped_preamble": stripped_preamble}


def to_markdown(parsed: dict) -> str:
    """Render parsed notes as a flat markdown doc, one H2 per note."""
    return "\n\n".join(f"## {n['title']}\n\n{n['content']}" for n in parsed["notes"])


def to_json(parsed: dict, module: str, source: str) -> str:
    payload = {
        "module": module,
        "source": source,
        "notes": parsed["notes"],
    }
    return json.dumps(payload, indent=2, ensure_ascii=False)


def main() -> int:
    parser = argparse.ArgumentParser(description="Normalize a raw course module export.")
    parser.add_argument("--source", required=True, help="Path to raw .md export")
    args = parser.parse_args()

    src = Path(args.source).resolve()
    if not src.is_file():
        print(f"error: source file not found: {src}", file=sys.stderr)
        return 1

    raw = src.read_text(encoding="utf-8")
    parsed = normalize(raw)

    if not parsed["notes"]:
        print(f"error: no <note title=\"...\"> blocks found in {src}", file=sys.stderr)
        return 1

    module = src.stem
    md_path = src.parent / f"{src.stem}.normalized.md"
    json_path = src.parent / f"{src.stem}.normalized.json"

    md_path.write_text(to_markdown(parsed) + "\n", encoding="utf-8")
    json_path.write_text(to_json(parsed, module, src.name) + "\n", encoding="utf-8")

    print(f"parsed {len(parsed['notes'])} note(s) from {src.name}")
    for i, n in enumerate(parsed["notes"], 1):
        print(f"  {i:2d}. {n['title']}")
    if parsed["stripped_preamble"]:
        n_lines = len([ln for ln in parsed["stripped_preamble"].splitlines() if ln.strip()])
        print(f"stripped <critical> preamble ({n_lines} line(s))")
    print(f"wrote {md_path}")
    print(f"wrote {json_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
