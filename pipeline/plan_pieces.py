"""Deterministic planner: 1 source module → N candidate piece-plans per brand.

Step 7a — deterministic only. Step 7b will add model-assisted angle/title generation.
"""

import argparse
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
BRANDS_PATH = REPO_ROOT / "config" / "brands.json"

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


def plan_pieces(normalized_notes_path: Path, brand_slug: str) -> dict:
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
            "angle": "[PLACEHOLDER: step 7b will populate]",
            "title_working": "[PLACEHOLDER: step 7b will populate]",
            "piece_type": piece_type,
            "target_length": target_length,
            "cross_brand_link": None,
            "notes": notes_str,
        })

    return {
        "module": module,
        "brand": brand_slug,
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "pieces": pieces,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Plan candidate LinkedIn pieces (deterministic, step 7a).")
    parser.add_argument("--source", required=True, help="Path to normalized notes JSON")
    parser.add_argument("--brand", required=True, help="Brand slug")
    args = parser.parse_args()

    plan = plan_pieces(Path(args.source), args.brand)
    print(json.dumps(plan, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
