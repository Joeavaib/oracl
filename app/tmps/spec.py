"""TMP-S v2.2 specification constants and rail prompt."""

from __future__ import annotations

ALLOWED_PREFIXES = {"V", "A", "E", "B", "C", "S", "O"}

LIMIT_RATIONALE_WORDS = 12
LIMIT_FIX_HINT_TOKENS = 12
LIMIT_ACTION_TOKENS = 10
LIMIT_PAYLOAD_TOKENS = 120

MIN_BRIEFS = 3
MAX_BRIEFS = 7

RAIL_PROMPT = (
    "You output ONLY TMP-S v2.2 records. No Markdown, no extra text. "
    "No spaces around pipes, and no '|' in free text. "
    "Order: V? A E* B{3..7} C. "
    "Use S stage|role|model_id|attempt to tag stage output. "
    "Use O kind|path|payload for output payloads (multiple O lines allowed). "
    "Self-check: grammar, limits, ordering."
)
