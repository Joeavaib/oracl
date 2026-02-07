"""Confidence and escalation controls for validator decisions."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, List, Optional


@dataclass(frozen=True)
class StepResult:
    confidence: float
    issues: List[str]
    retry_count: int
    tokens_used: int


@dataclass(frozen=True)
class EscalationDecision:
    action: str
    reason: str
    modified_prompt: Optional[str]
    window_adjustment: Optional[dict]


def _clamp_confidence(value: float) -> float:
    return max(0.0, min(1.0, value))


def compute_confidence(
    *,
    json_parse_ok: bool,
    required_fields_present: bool,
    output_text: str,
) -> float:
    """Compute heuristic confidence for a validator step.

    Rules:
    - JSON parse OK + required fields present -> baseline 0.7
    - Missing required fields -> -0.3
    - "can't"/"unsure" language -> -0.3
    """
    confidence = 0.0
    if json_parse_ok and required_fields_present:
        confidence = 0.7

    if not required_fields_present:
        confidence -= 0.3

    normalized = output_text.lower()
    if "can't" in normalized or "cannot" in normalized or "unsure" in normalized:
        confidence -= 0.3

    return _clamp_confidence(confidence)


def decide_escalation(
    *,
    current: StepResult,
    confidence_history: Iterable[float] | None = None,
) -> EscalationDecision:
    """Pick Adapt/Reframe/Escalate/Abort based on confidence trend."""
    history = list(confidence_history or [])
    trend_falling = bool(history) and current.confidence < history[-1]

    if current.confidence <= 0.2 and current.retry_count >= 2:
        return EscalationDecision(
            action="abort",
            reason="Confidence critically low after multiple retries.",
            modified_prompt=None,
            window_adjustment={"window_chunks": 2},
        )

    if trend_falling:
        action = "reframe" if current.retry_count < 2 else "escalate"
        return EscalationDecision(
            action=action,
            reason="Confidence is trending downward.",
            modified_prompt=None,
            window_adjustment={"window_chunks": 1},
        )

    return EscalationDecision(
        action="adapt",
        reason="Confidence stable; proceed with adaptive retry.",
        modified_prompt=None,
        window_adjustment=None,
    )
