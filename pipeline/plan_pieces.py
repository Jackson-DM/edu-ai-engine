"""1-source-to-N piece planner.

Step 7a (deterministic): skip-filter notes, match brand pillars, cluster, emit slots.
Step 7b (model-assisted): for each emitted piece, call Haiku 4.5 to fill `angle`
and `title_working`. Results cached by content hash under output/plan_cache/.
"""

import argparse
import hashlib
import json
import os
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

import requests
from dotenv import load_dotenv

REPO_ROOT = Path(__file__).resolve().parent.parent
BRANDS_PATH = REPO_ROOT / "config" / "brands.json"
CACHE_DIR = REPO_ROOT / "output" / "plan_cache"

OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"
HAIKU_MODEL = "anthropic/claude-haiku-4-5"
HAIKU_MAX_TOKENS = 400

PLACEHOLDER = "[PLACEHOLDER: step 7b will populate]"

AFFINITY_STOPWORDS = {"defining", "implementing", "the", "in", "a", "with", "mcp"}
DESCRIPTOR_DROP = {"mcp", "with"}

PIECE_TYPE_TARGET_LEN = {
    "quick_take": 200,
    "explainer": 300,
    "deep_dive": 450,
}


def _tokens(title: str) -> list:
    return [t for t in re.split(r"[^a-zA-Z0-9]+", title.lower()) if t]


def _content_words(title: str) -> set:
    return {t for t in _tokens(title) if t not in AFFINITY_STOPWORDS}


def _descriptor(title: str) -> str:
    toks = [t for t in _tokens(title) if t not in DESCRIPTOR_DROP]
    return "-".join(toks) if toks else "untitled"


def _share_affinity(t1: str, t2: str) -> bool:
    return bool(_content_words(t1) & _content_words(t2))


def _pick_pillar(union_pillars: list, primary: list, secondary: list) -> str:
    for p in primary:
        if p in union_pillars:
            return p
    for p in secondary:
        if p in union_pillars:
            return p
    return union_pillars[0]


def _piece_type(cluster_size: int, content_len: int) -> str:
    if cluster_size == 1:
        return "quick_take" if content_len <= 900 else "explainer"
    return "deep_dive"


def _cluster(notes: list) -> list:
    """Group adjacent surviving notes that share a pillar tag AND title affinity. Max 3."""
    clusters = []
    i = 0
    while i < len(notes):
        cluster = [notes[i]]
        while len(cluster) < 3 and i + 1 < len(notes):
            prev = cluster[-1]
            nxt = notes[i + 1]
            shared_pillar = set(prev["pillars"]) & set(nxt["pillars"])
            if shared_pillar and _share_affinity(prev["title"], nxt["title"]):
                cluster.append(nxt)
                i += 1
            else:
                break
        clusters.append(cluster)
        i += 1
    return clusters


def _compute_hash(note_contents: list, voice_summary: str, pillar: str,
                  piece_type: str, target_length: int) -> str:
    h = hashlib.sha256()
    for c in note_contents:
        h.update(c.encode("utf-8"))
        h.update(b"\x00")
    h.update(b"||")
    h.update(voice_summary.encode("utf-8"))
    h.update(b"||")
    h.update(pillar.encode("utf-8"))
    h.update(b"||")
    h.update(piece_type.encode("utf-8"))
    h.update(b"||")
    h.update(str(target_length).encode("utf-8"))
    return h.hexdigest()[:16]


def _cache_path(module: str, brand_slug: str, piece_id: str) -> Path:
    return CACHE_DIR / module / brand_slug / f"{piece_id}.json"


def _strip_fences(text: str) -> str:
    text = text.strip()
    if text.startswith("```"):
        nl = text.find("\n")
        if nl != -1:
            text = text[nl + 1:]
        if text.endswith("```"):
            text = text[:-3]
    return text.strip()


def _build_haiku_messages(brand_name: str, voice_summary: str, pillar: str,
                          piece_type: str, target_length: int,
                          source_notes: list) -> list:
    system = (
        "You generate LinkedIn post angles and working titles for a multi-brand "
        "AI content engine. Return strict JSON only, no preamble."
    )
    notes_block = "\n\n".join(
        f"--- {n['title']} ---\n{n['content']}" for n in source_notes
    )
    user = (
        f"Brand: {brand_name}\n"
        f"Voice summary: {voice_summary}\n"
        f"Pillar tag: {pillar}\n"
        f"Piece type: {piece_type} (target ~{target_length} words)\n\n"
        f"Source notes:\n\n{notes_block}\n\n"
        "Return JSON with exactly these keys:\n"
        '{"angle": "<one-sentence framing>", "title_working": "<short LinkedIn hook>"}'
    )
    return [
        {"role": "system", "content": system},
        {"role": "user", "content": user},
    ]


def _call_haiku(messages: list, api_key: str) -> tuple:
    headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
    payload = {"model": HAIKU_MODEL, "messages": messages, "max_tokens": HAIKU_MAX_TOKENS}
    r = requests.post(OPENROUTER_URL, headers=headers, json=payload, timeout=60)
    r.raise_for_status()
    data = r.json()
    content = data["choices"][0]["message"]["content"]
    usage = data.get("usage") or {}
    return content, usage


def _enrich_pieces(pieces: list, notes_by_title: dict, brand_meta: dict,
                   module: str) -> dict:
    stats = {
        "api_calls": 0,
        "cache_hits": 0,
        "fallbacks": 0,
        "prompt_tokens": 0,
        "completion_tokens": 0,
        "cost": 0.0,
    }
    load_dotenv(REPO_ROOT / ".env")
    api_key = os.environ.get("OPENROUTER_API_KEY")
    if not api_key or api_key == "your_key_here":
        print("warn: OPENROUTER_API_KEY not set; leaving placeholders in place", file=sys.stderr)
        stats["fallbacks"] = len(pieces)
        return stats

    voice_summary = brand_meta.get("voice_summary", "")
    brand_name = brand_meta.get("display_name", brand_meta.get("name", ""))

    for piece in pieces:
        source_notes = [notes_by_title[t] for t in piece["source_notes"]]
        note_contents = [n["content"] for n in source_notes]
        pillar = piece["pillar"]
        pt = piece["piece_type"]
        tl = piece["target_length"]
        content_hash = _compute_hash(note_contents, voice_summary, pillar, pt, tl)

        cache_p = _cache_path(module, piece["brand"], piece["piece_id"])
        if cache_p.exists():
            try:
                cached = json.loads(cache_p.read_text(encoding="utf-8"))
                if cached.get("hash") == content_hash:
                    piece["angle"] = cached["angle"]
                    piece["title_working"] = cached["title_working"]
                    stats["cache_hits"] += 1
                    print(f"  cache hit: {piece['piece_id']}", file=sys.stderr)
                    continue
            except (json.JSONDecodeError, OSError) as e:
                print(f"  warn: cache read failed for {piece['piece_id']}: {e}", file=sys.stderr)

        messages = _build_haiku_messages(brand_name, voice_summary, pillar, pt, tl, source_notes)
        raw = ""
        try:
            raw, usage = _call_haiku(messages, api_key)
            stats["api_calls"] += 1
            stats["prompt_tokens"] += usage.get("prompt_tokens") or 0
            stats["completion_tokens"] += usage.get("completion_tokens") or 0
            cost = usage.get("cost")
            if isinstance(cost, (int, float)):
                stats["cost"] += cost
            cleaned = _strip_fences(raw)
            parsed = json.loads(cleaned)
            angle = str(parsed["angle"]).strip()
            title = str(parsed["title_working"]).strip()
            if not angle or not title:
                raise ValueError("empty angle or title_working in parsed response")
        except Exception as e:
            print(f"  warn: enrich failed for {piece['piece_id']}: {e}", file=sys.stderr)
            if raw:
                print(f"        raw response (first 500 chars): {raw[:500]}", file=sys.stderr)
            stats["fallbacks"] += 1
            continue

        piece["angle"] = angle
        piece["title_working"] = title
        cache_p.parent.mkdir(parents=True, exist_ok=True)
        cache_p.write_text(
            json.dumps({
                "hash": content_hash,
                "angle": angle,
                "title_working": title,
                "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                "model": HAIKU_MODEL,
            }, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
        print(f"  fetched: {piece['piece_id']}", file=sys.stderr)

    return stats


def plan_pieces(normalized_notes_path: Path, brand_slug: str, enrich: bool = True) -> dict:
    normalized_notes_path = Path(normalized_notes_path)
    data = json.loads(normalized_notes_path.read_text(encoding="utf-8"))
    brands = json.loads(BRANDS_PATH.read_text(encoding="utf-8"))
    if brand_slug not in brands["brands"]:
        raise ValueError(f"unknown brand: {brand_slug}")
    brand = brands["brands"][brand_slug]
    primary = list(brand["content_pillars"].get("primary", []))
    secondary = list(brand["content_pillars"].get("secondary", []))
    brand_pillars = set(primary) | set(secondary)

    survivors = [n for n in data["notes"] if n.get("pillars")]
    survivors = [n for n in survivors if set(n["pillars"]) & brand_pillars]
    clusters = _cluster(survivors)

    module = data.get("module", normalized_notes_path.stem)

    pieces = []
    for seq, cluster in enumerate(clusters, start=1):
        primary_note = cluster[0]
        descriptor = _descriptor(primary_note["title"])
        piece_id = f"{module}_{brand_slug}_{descriptor}_{seq:03d}"

        union_pillars = []
        for n in cluster:
            for p in n["pillars"]:
                if p in brand_pillars and p not in union_pillars:
                    union_pillars.append(p)
        pillar = _pick_pillar(union_pillars, primary, secondary)
        tier = "primary" if pillar in primary else "secondary"

        source_titles = [n["title"] for n in cluster]
        content_len = len(primary_note["content"])
        piece_type = _piece_type(len(cluster), content_len)
        target_length = PIECE_TYPE_TARGET_LEN[piece_type]

        if len(cluster) == 1:
            notes_str = (
                f"Single note '{primary_note['title']}' "
                f"({content_len} chars), matched on {pillar} ({tier} pillar)"
            )
        else:
            shared = _content_words(cluster[0]["title"])
            for n in cluster[1:]:
                shared &= _content_words(n["title"])
            shared_word = next(iter(shared)).capitalize() if shared else "shared theme"
            joined = " + ".join(n["title"] for n in cluster)
            notes_str = (
                f"Clustered {joined} by '{shared_word}' affinity, "
                f"matched on {pillar} ({tier} pillar)"
            )

        pieces.append({
            "piece_id": piece_id,
            "brand": brand_slug,
            "pillar": pillar,
            "source_notes": source_titles,
            "angle": PLACEHOLDER,
            "title_working": PLACEHOLDER,
            "piece_type": piece_type,
            "target_length": target_length,
            "cross_brand_link": None,
            "notes": notes_str,
        })

    plan = {
        "module": module,
        "brand": brand_slug,
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "pieces": pieces,
    }

    if enrich and pieces:
        notes_by_title = {n["title"]: n for n in data["notes"]}
        stats = _enrich_pieces(pieces, notes_by_title, brand, module)
        plan["enrichment_stats"] = stats

    return plan


def main() -> int:
    parser = argparse.ArgumentParser(description="Plan candidate LinkedIn pieces (7a deterministic + 7b model-assisted).")
    parser.add_argument("--source", required=True, help="Path to normalized notes JSON")
    parser.add_argument("--brand", required=True, help="Brand slug")
    parser.add_argument("--no-enrich", action="store_true", help="Skip Haiku enrichment pass (7a only)")
    args = parser.parse_args()

    plan = plan_pieces(Path(args.source), args.brand, enrich=not args.no_enrich)
    print(json.dumps(plan, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
