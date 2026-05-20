"""Two-pass humanizer for the edu-ai-engine pipeline.

Pass 1 produces a draft rewrite using the project's humanizer guidelines.
Pass 2 audits the draft for remaining AI tells and produces a final rewrite.
On a pass-2 failure, falls back to the pass-1 draft so a degraded humanizer
pass never fails the whole article pipeline.
"""

import json
import os
import sys
from pathlib import Path

import requests
from dotenv import load_dotenv

REPO_ROOT = Path(__file__).resolve().parent.parent
CONFIG_PATH = REPO_ROOT / "config" / "engine_config.json"
GUIDELINES_PATH = REPO_ROOT / "foundation" / "HUMANIZER_GUIDELINES.md"
VOICES_DIR = REPO_ROOT / "foundation" / "voices"
OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"

VALID_INTENSITIES = ("light", "medium", "heavy")
SHORT_INPUT_WORD_THRESHOLD = 100

INTENSITY_DIRECTIVES = {
    "light": (
        "Apply a light touch. Fix the most obvious banned phrases and AI tells, "
        "punch up the opening, and tighten the CTA. Preserve as much of the "
        "original phrasing as possible."
    ),
    "medium": (
        "Apply the standard rewrite. Work through the full pattern guide, "
        "rewrite weak or generic sections, vary sentence rhythm, and swap "
        "vague claims for concrete details. Preserve meaning and structure."
    ),
    "heavy": (
        "Apply an aggressive rewrite. Replace any generic section wholesale, "
        "force concrete examples and named specifics, vary sentence length "
        "deliberately, and let voice and opinion show. Preserve only the core "
        "argument and key facts."
    ),
}

_guidelines_cache = ""
_config_cache: dict = {}
_voice_cache: dict = {}


def _load_guidelines() -> str:
    """Load and cache the humanizer guidelines markdown."""
    global _guidelines_cache
    if not _guidelines_cache:
        _guidelines_cache = GUIDELINES_PATH.read_text(encoding="utf-8")
    return _guidelines_cache


def _load_brand_voice(brand_slug: str) -> str:
    """Load and cache the brand voice file (foundation/voices/<brand_slug>.md)."""
    if brand_slug not in _voice_cache:
        path = VOICES_DIR / f"{brand_slug}.md"
        _voice_cache[brand_slug] = path.read_text(encoding="utf-8")
    return _voice_cache[brand_slug]


def _format_piece_context(plan: dict) -> str:
    """Render the piece-context block injected at the top of humanizer prompts."""
    source_notes = plan.get("source_notes") or []
    angle = plan.get("angle") or ""
    return (
        "Piece context:\n"
        f"- Type: {plan.get('piece_type', '')}\n"
        f"- Target length: {plan.get('target_length', '')} words\n"
        f"- Angle: {angle}\n"
        f"- Source notes: {', '.join(source_notes) if source_notes else '(none)'}"
    )


def _load_config() -> dict:
    """Load and cache the engine config."""
    global _config_cache
    if not _config_cache:
        _config_cache = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    return _config_cache


def _get_api_key() -> str:
    """Read OPENROUTER_API_KEY from .env, raising if unset."""
    load_dotenv(REPO_ROOT / ".env")
    api_key = os.environ.get("OPENROUTER_API_KEY")
    if not api_key or api_key == "your_key_here":
        raise RuntimeError("OPENROUTER_API_KEY is not set in .env")
    return api_key


def _call_openrouter(
    messages: list,
    model: str,
    max_tokens: int,
    temperature: float,
    api_key: str,
) -> dict:
    """POST to OpenRouter chat completions and return the parsed JSON response."""
    headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
    payload = {
        "model": model,
        "messages": messages,
        "max_tokens": max_tokens,
        "temperature": temperature,
    }
    r = requests.post(OPENROUTER_URL, headers=headers, json=payload, timeout=180)
    r.raise_for_status()
    return r.json()


def _extract(response: dict) -> tuple:
    """Pull (assistant_message_text, total_tokens) from a chat-completions response."""
    content = response["choices"][0]["message"]["content"]
    tokens = response.get("usage", {}).get("total_tokens", 0)
    return content, tokens


def _parse_pass2_json(raw: str) -> dict:
    """Parse the pass-2 JSON response. Tolerates a fenced ```json``` wrapper."""
    text = raw.strip()
    if text.startswith("```"):
        text = text.split("\n", 1)[1] if "\n" in text else text[3:]
        if text.endswith("```"):
            text = text[:-3]
        text = text.strip()
    return json.loads(text)


def _draft_messages(
    text: str,
    intensity: str,
    brand: str,
    guidelines: str,
    brand_voice: str,
    voice_summary: str,
    plan: dict,
) -> list:
    """Build pass-1 messages: piece context + intensity directive + guidelines + brand voice."""
    system = (
        "You are a writing editor. Apply the following guidelines to humanize "
        "the text. Preserve meaning and brand voice. Return only the rewritten "
        "text, no preamble."
    )
    user = (
        f"This text is for the {brand} brand on LinkedIn.\n"
        f"Voice summary: {voice_summary}\n\n"
        f"{_format_piece_context(plan)}\n\n"
        f"Intensity: {intensity}. {INTENSITY_DIRECTIVES[intensity]}\n\n"
        f"--- HUMANIZER GUIDELINES ---\n\n{guidelines}\n\n"
        f"--- BRAND VOICE ({brand}) ---\n\n{brand_voice}\n\n"
        f"--- TEXT TO HUMANIZE ---\n\n{text}"
    )
    return [
        {"role": "system", "content": system},
        {"role": "user", "content": user},
    ]


def _audit_messages(
    draft: str,
    intensity: str,
    brand: str,
    guidelines: str,
    brand_voice: str,
    voice_summary: str,
    plan: dict,
) -> list:
    """Build pass-2 messages: audit + final rewrite returned as JSON."""
    system = (
        "First, identify what still sounds AI-generated about the draft below "
        "in 3-5 brief bullets. Then provide a final rewrite that fixes those "
        'specific issues. Return JSON: {"audit": [...], "final": "..."}.'
    )
    user = (
        f"This text is for the {brand} brand on LinkedIn.\n"
        f"Voice summary: {voice_summary}\n\n"
        f"{_format_piece_context(plan)}\n\n"
        f"Intensity: {intensity}.\n\n"
        f"--- HUMANIZER GUIDELINES (reference) ---\n\n{guidelines}\n\n"
        f"--- BRAND VOICE ({brand}) ---\n\n{brand_voice}\n\n"
        f"--- DRAFT TO AUDIT AND FINALIZE ---\n\n{draft}"
    )
    return [
        {"role": "system", "content": system},
        {"role": "user", "content": user},
    ]


def humanize(text: str, intensity: str, brand: str, plan: dict, voice_summary: str) -> str:
    """Run two-pass humanizer on generated content. Always returns humanized text or raises.

    Args:
        text: Article or post content to humanize.
        intensity: One of "light", "medium", "heavy" (matches brands.json).
            Overridden to "light" automatically if plan["piece_type"] == "quick_take".
        brand: Brand slug (e.g., "ai-first-work"). Used for prompt context AND
            to look up the brand voice file under foundation/voices/<brand>.md.
        plan: Piece-plan dict from step 7 (plan_pieces.py). Used for piece_type
            override and to inject piece context (type, target_length, angle,
            source_notes) into the humanizer prompts.
        voice_summary: Short brand voice description from brands.json, injected
            into the prompt header.

    Returns:
        Final humanized text. On pass-2 failure, returns the pass-1 draft
        rather than failing the pipeline.

    Raises:
        ValueError: if intensity is not one of the supported values.
        RuntimeError: if OPENROUTER_API_KEY is unset.
        requests.RequestException: if the pass-1 API call fails.
    """
    # Piece-type intensity override — applied before validation.
    if plan.get("piece_type") == "quick_take" and intensity != "light":
        print(f"[humanizer] piece_type=quick_take, overriding intensity {intensity!r} -> light")
        intensity = "light"

    if intensity not in VALID_INTENSITIES:
        raise ValueError(
            f"intensity must be one of {VALID_INTENSITIES}, got {intensity!r}"
        )

    guidelines = _load_guidelines()
    brand_voice = _load_brand_voice(brand)
    config = _load_config()
    humanizer_cfg = config["humanizer"]
    model = config["model"]
    api_key = _get_api_key()

    is_short = len(text.split()) < SHORT_INPUT_WORD_THRESHOLD
    if is_short:
        print("[humanizer] short input, single-pass mode.")

    pass1_response = _call_openrouter(
        _draft_messages(text, intensity, brand, guidelines, brand_voice, voice_summary, plan),
        model=model,
        max_tokens=humanizer_cfg["max_tokens_pass_1"],
        temperature=humanizer_cfg["temperature"],
        api_key=api_key,
    )
    draft, pass1_tokens = _extract(pass1_response)
    print(f"[humanizer] pass 1 complete ({pass1_tokens} tokens)")

    if is_short:
        return draft.strip()

    try:
        pass2_response = _call_openrouter(
            _audit_messages(draft, intensity, brand, guidelines, brand_voice, voice_summary, plan),
            model=model,
            max_tokens=humanizer_cfg["max_tokens_pass_2"],
            temperature=humanizer_cfg["temperature"],
            api_key=api_key,
        )
    except requests.RequestException as e:
        print(
            f"[humanizer] pass 2 API call failed ({type(e).__name__}: {e}); "
            "falling back to pass 1 draft.",
            file=sys.stderr,
        )
        return draft.strip()

    raw, pass2_tokens = _extract(pass2_response)
    print(f"[humanizer] pass 2 complete ({pass2_tokens} tokens)")

    try:
        parsed = _parse_pass2_json(raw)
        final = parsed["final"]
        if not isinstance(final, str) or not final.strip():
            raise ValueError("pass 2 JSON missing or empty 'final' field")
        return final.strip()
    except (ValueError, KeyError) as e:
        print(
            f"[humanizer] pass 2 parse failed ({type(e).__name__}: {e}); "
            f"falling back to pass 1 draft. Raw audit attempt: {raw!r}",
            file=sys.stderr,
        )
        return draft.strip()
