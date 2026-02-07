from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, Optional

from app.event_store import (
    INFERENCE_COMPLETED,
    INFERENCE_STARTED,
    PROMPT_BUILT,
    STAGE_COMPLETED,
    STAGE_STARTED,
    append_event,
)
from app.llm_client import LLMClientError, chat_completions
from app.output_parser import extract_json
from app.prompt_builder import build_prompt
from app.runs import runs_dir


class StageRunnerError(RuntimeError):
    pass


def _run_path(run_id: str) -> Path:
    path = runs_dir() / run_id
    path.mkdir(parents=True, exist_ok=True)
    return path


def _normalize_base_url(base_url: Optional[str]) -> str:
    if not base_url:
        return ""
    cleaned = base_url.rstrip("/")
    if cleaned.endswith("/v1"):
        cleaned = cleaned[: -len("/v1")]
    return cleaned


def _extract_content(response: Dict[str, Any]) -> str:
    try:
        return str(response["choices"][0]["message"]["content"])
    except (KeyError, IndexError, TypeError) as exc:
        raise StageRunnerError("LLM response missing choices.message.content") from exc


def _write_json(path: Path, payload: Dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        json.dump(payload, handle, ensure_ascii=False, indent=2)


def _select_token_budget(model_snapshot: Dict[str, Any], input_payload: Dict[str, Any]) -> Optional[int]:
    params = model_snapshot.get("params") if isinstance(model_snapshot.get("params"), dict) else {}
    for candidate in (params.get("token_budget"), input_payload.get("token_budget")):
        if isinstance(candidate, int):
            return candidate
    return None


def _stage_file(stage_type: str) -> str:
    stage = stage_type.strip().lower()
    if stage == "planner":
        return "planner_output.json"
    if stage == "coder":
        return "coder_output.json"
    return f"{stage}_output.json"


def run_stage(
    run_id: str,
    stage_type: str,
    model_snapshot: Dict[str, Any],
    input_payload: Dict[str, Any],
) -> Dict[str, Any]:
    if not run_id:
        raise StageRunnerError("run_id is required")
    if not stage_type:
        raise StageRunnerError("stage_type is required")
    if not isinstance(model_snapshot, dict):
        raise StageRunnerError("model_snapshot must be a dict")

    model = model_snapshot.get("model_snapshot") or model_snapshot
    base_url = _normalize_base_url(model.get("base_url"))
    model_name = model.get("model_name")
    if not base_url or not model_name:
        raise StageRunnerError("model_snapshot must include base_url and model_name")

    token_budget = _select_token_budget(model_snapshot, input_payload)
    orchestra_briefing = input_payload.get("orchestra_briefing") or {}
    messages = build_prompt(
        orchestra_briefing=orchestra_briefing,
        stage_type=stage_type,
        token_budget=token_budget,
        input_payload=input_payload,
    )

    stage_id = stage_type.strip().lower()
    append_event(run_id, STAGE_STARTED, {"stage": stage_type}, stage_id=stage_id)
    append_event(
        run_id,
        PROMPT_BUILT,
        {"stage": stage_type, "token_budget": token_budget},
        stage_id=stage_id,
    )

    payload = {
        "model": model_name,
        "messages": messages,
        "temperature": 0,
    }

    append_event(run_id, INFERENCE_STARTED, {"stage": stage_type}, stage_id=stage_id)
    try:
        response = chat_completions(base_url=base_url, payload=payload)
        content = _extract_content(response)
        output_payload = extract_json(content)
    except (LLMClientError, ValueError) as exc:
        append_event(
            run_id,
            INFERENCE_COMPLETED,
            {"stage": stage_type, "status": "error", "error": str(exc)},
            stage_id=stage_id,
        )
        raise StageRunnerError(str(exc)) from exc

    append_event(
        run_id,
        INFERENCE_COMPLETED,
        {"stage": stage_type, "status": "ok"},
        stage_id=stage_id,
    )

    run_path = _run_path(run_id)
    _write_json(run_path / _stage_file(stage_type), output_payload)
    _write_json(
        run_path / f"{stage_id}_inference.json",
        {
            "stage": stage_type,
            "model": model_name,
            "messages": messages,
            "response_text": content,
            "output_payload": output_payload,
        },
    )

    append_event(run_id, STAGE_COMPLETED, {"stage": stage_type}, stage_id=stage_id)
    return output_payload
