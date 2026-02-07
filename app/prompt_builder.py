from __future__ import annotations

import json
from typing import Any, Dict, List, Optional


def _normalize_stage(stage_type: str) -> str:
    return stage_type.strip().upper()


def _system_prompt(stage_type: str) -> str:
    stage = _normalize_stage(stage_type)
    if stage == "PLANNER":
        return (
            "You are PLANNER. You do NOT write code. "
            "Return strict JSON for PlannerOutput v0.1 only. "
            "No Markdown and no extra text."
        )
    if stage == "CODER":
        return (
            "You are CODER. Implement the plan with a minimal unified diff. "
            "Return strict JSON for CoderOutput v0.1 only. "
            "No Markdown and no extra text."
        )
    return (
        "You are a structured assistant. Return strict JSON only. "
        "No Markdown and no extra text."
    )


def build_prompt(
    orchestra_briefing: Dict[str, Any],
    stage_type: str,
    token_budget: Optional[int],
    input_payload: Dict[str, Any],
) -> List[Dict[str, str]]:
    stage = _normalize_stage(stage_type)
    system_prompt = _system_prompt(stage)
    user_payload: Dict[str, Any] = {
        "stage_type": stage,
        "orchestra_briefing": orchestra_briefing,
        "input_payload": input_payload,
        "response_format": "strict_json_only",
    }
    if token_budget is not None:
        user_payload["token_budget"] = token_budget
    return [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": json.dumps(user_payload, ensure_ascii=False)},
    ]
