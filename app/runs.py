from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional

from app.event_store import (
    DECISION_MADE,
    RUN_COMPLETED,
    RUN_CREATED,
    RUN_FAILED,
    RUN_STARTED,
    STAGE_COMPLETED,
    STAGE_STARTED,
    append_event,
    list_events,
)
from app.paths import repo_root as paths_repo_root, runs_dir as paths_runs_dir
from app.pipelines_registry import get_pipeline, resolve_model_snapshots
from app.stage_runner import StageRunnerError, run_stage
from app.validator.engine import compress_user_prompt_to_script, validate_request
from app.validator.schema import FinalValidatorLabel, OrchestraBriefing, RequestRecord


MAX_PREVIEW_BYTES = 200 * 1024


def repo_root() -> Path:
    return paths_repo_root()


def runs_dir() -> Path:
    return paths_runs_dir()


def _safe_run_dir(run_id: str) -> Path:
    candidate = runs_dir() / run_id
    resolved = candidate.resolve()
    if runs_dir().resolve() not in resolved.parents:
        raise ValueError("Invalid run_id")
    return resolved


def _read_json(path: Path) -> Optional[Dict[str, Any]]:
    if not path.exists():
        return None
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def _write_json(path: Path, payload: Dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        json.dump(payload, handle, ensure_ascii=False, indent=2)


def _write_validator_artifacts(
    run_path: Path,
    *,
    stage: str,
    request_record: RequestRecord,
    label: FinalValidatorLabel,
) -> None:
    _write_json(run_path / f"validator_{stage}.json", label.dict())
    _write_json(
        run_path / f"validator_{stage}_step_01_ingest.json",
        request_record.dict(),
    )
    _write_json(
        run_path / f"validator_{stage}_step_02_policy.json",
        {"hard_checks": label.hard_checks.dict(), "soft_checks": label.soft_checks.dict()},
    )
    _write_json(
        run_path / f"validator_{stage}_step_03_compress.json",
        label.orchestra_briefing.dict(),
    )


def _file_preview(path: Path, max_bytes: int = MAX_PREVIEW_BYTES) -> Dict[str, Any]:
    if not path.exists():
        return {
            "exists": False,
            "path": str(path),
            "size": 0,
            "truncated": False,
            "content": None,
        }
    size = path.stat().st_size
    truncated = size > max_bytes
    with path.open("r", encoding="utf-8", errors="replace") as handle:
        content = handle.read(max_bytes)
    try:
        parsed = json.loads(content) if not truncated else None
    except json.JSONDecodeError:
        parsed = None
    if parsed is not None:
        content = json.dumps(parsed, ensure_ascii=False, indent=2)
    return {
        "exists": True,
        "path": str(path),
        "size": size,
        "truncated": truncated,
        "content": content,
    }


def _approx_token_count(text: str) -> int:
    return max(1, len(text) // 4) if text else 0


def _build_input_payload(payload: Dict[str, Any]) -> Dict[str, Any]:
    run_config = payload.get("run_config") or {}
    if not isinstance(run_config, dict):
        run_config = {}
    run_config = {
        "max_retries_per_stage": run_config.get("max_retries_per_stage", 2),
        "escalation_threshold": run_config.get("escalation_threshold", 0.4),
    }
    return {
        "goal": payload.get("goal") or payload.get("user_prompt") or "",
        "user_prompt": payload.get("user_prompt") or "",
        "repo_root": payload.get("repo_root") or "",
        "constraints": payload.get("constraints") or [],
        "pipeline_id": payload.get("pipeline_id") or "",
        "run_config": run_config,
    }


def _initial_orchestra_briefing(user_prompt: str) -> OrchestraBriefing:
    return OrchestraBriefing(
        known_correct=[],
        uncertain_or_needs_check=[],
        missing_inputs=[],
        next_actions=[
            "Summarize the task intent.",
            "Follow constraints.",
            "Produce strict JSON output.",
        ],
        optional_patch=None,
        retry_prompt="No retry required.",
        script=compress_user_prompt_to_script(user_prompt),
        current_scope=[],
        allowed_actions=[],
        token_budget=None,
        constraints=[],
    )


def _log_decision(
    run_id: str,
    stage_id: str,
    label: FinalValidatorLabel,
) -> None:
    append_event(
        run_id,
        DECISION_MADE,
        {
            "decision": label.control.dict(),
            "hard_checks": label.hard_checks.dict(),
            "soft_checks": label.soft_checks.dict(),
            "minimal_rationale": label.minimal_rationale,
            "retry_prompt": label.orchestra_briefing.retry_prompt,
        },
        stage_id=stage_id,
    )


def _pause_run(run_id: str, label: FinalValidatorLabel) -> None:
    run_path = _safe_run_dir(run_id)
    _write_json(
        run_path / "state_paused.json",
        {
            "run_id": run_id,
            "paused_at": datetime.now(timezone.utc).isoformat(),
            "status": "PAUSED",
            "reason": "validator_decision",
            "decision": label.control.dict(),
        },
    )


def _validator_stage_suffix(stage_id: str) -> str:
    if stage_id.startswith("validator_"):
        return stage_id[len("validator_") :]
    return stage_id


def _validator_label_path(run_path: Path, stage_id: str) -> Path:
    return run_path / f"validator_{_validator_stage_suffix(stage_id)}.json"


def _validator_ingest_path(run_path: Path, stage_id: str) -> Path:
    return run_path / f"validator_{_validator_stage_suffix(stage_id)}_step_01_ingest.json"


def _stage_output_filename(stage_id: str) -> str:
    stage = stage_id.strip().lower()
    if stage == "planner":
        return "planner_output.json"
    if stage == "coder":
        return "coder_output.json"
    return f"{stage}_output.json"


def _load_steps(run_path: Path) -> List[Dict[str, Any]]:
    pipeline_snapshot = _read_json(run_path / "pipeline_snapshot.json") or {}
    steps = pipeline_snapshot.get("steps")
    if isinstance(steps, list) and steps:
        return steps
    model_snapshots = _read_json(run_path / "model_snapshots.json") or {}
    steps = model_snapshots.get("steps")
    if isinstance(steps, list):
        return steps
    return []


def _resolve_stage(run_id: str, stage_index: int) -> Dict[str, Any]:
    if stage_index < 1:
        raise ValueError("stage index must be >= 1")
    run_path = _safe_run_dir(run_id)
    steps = _load_steps(run_path)
    if not steps:
        raise ValueError("No stages available for run")
    if stage_index > len(steps):
        raise ValueError("stage index out of range")
    step = steps[stage_index - 1]
    stage_type = str(step.get("step") or step.get("role") or f"stage_{stage_index}")
    role = str(step.get("role") or "").strip().lower()
    stage_id = stage_type.strip().lower()
    return {
        "run_path": run_path,
        "step": step,
        "stage_type": stage_type,
        "stage_id": stage_id,
        "role": role,
        "index": stage_index,
    }


def get_stage_prompt(run_id: str, stage_index: int) -> Dict[str, Any]:
    info = _resolve_stage(run_id, stage_index)
    run_path = info["run_path"]
    stage_id = info["stage_id"]
    role = info["role"]
    if role == "validator":
        record = _read_json(_validator_ingest_path(run_path, stage_id)) or {}
        return {
            "run_id": run_id,
            "stage_index": stage_index,
            "stage": stage_id,
            "prompt": record.get("prompt"),
            "request_record": record,
        }
    inference = _read_json(run_path / f"{stage_id}_inference.json") or {}
    return {
        "run_id": run_id,
        "stage_index": stage_index,
        "stage": stage_id,
        "messages": inference.get("messages"),
        "model": inference.get("model"),
    }


def get_stage_output(run_id: str, stage_index: int) -> Dict[str, Any]:
    info = _resolve_stage(run_id, stage_index)
    run_path = info["run_path"]
    stage_id = info["stage_id"]
    role = info["role"]
    if role == "validator":
        label = _read_json(_validator_label_path(run_path, stage_id))
        if label is None:
            raise ValueError("Validator output not found")
        return {
            "run_id": run_id,
            "stage_index": stage_index,
            "stage": stage_id,
            "output": label,
        }
    output = _read_json(run_path / _stage_output_filename(stage_id))
    if output is None:
        raise ValueError("Stage output not found")
    return {
        "run_id": run_id,
        "stage_index": stage_index,
        "stage": stage_id,
        "output": output,
    }


def get_stage_decision(run_id: str, stage_index: int) -> Dict[str, Any]:
    info = _resolve_stage(run_id, stage_index)
    run_path = info["run_path"]
    stage_id = info["stage_id"]
    role = info["role"]
    if role != "validator":
        raise ValueError("Stage has no validator decision")
    label = _read_json(_validator_label_path(run_path, stage_id))
    if label is None:
        raise ValueError("Validator decision not found")
    return {
        "run_id": run_id,
        "stage_index": stage_index,
        "stage": stage_id,
        "decision": label.get("control"),
    }


def get_token_usage(run_id: str) -> Dict[str, Any]:
    run_path = _safe_run_dir(run_id)
    steps = _load_steps(run_path)
    stage_usages: List[Dict[str, Any]] = []
    total_tokens = 0
    for index, step in enumerate(steps, start=1):
        stage_type = str(step.get("step") or step.get("role") or f"stage_{index}")
        stage_id = stage_type.strip().lower()
        inference = _read_json(run_path / f"{stage_id}_inference.json")
        if not inference:
            continue
        messages = inference.get("messages")
        response_text = inference.get("response_text")
        prompt_tokens = _approx_token_count(json.dumps(messages, ensure_ascii=False))
        completion_tokens = _approx_token_count(str(response_text or ""))
        total = prompt_tokens + completion_tokens
        total_tokens += total
        stage_usages.append(
            {
                "stage": stage_id,
                "stage_index": index,
                "prompt_tokens": prompt_tokens,
                "completion_tokens": completion_tokens,
                "total_tokens": total,
            }
        )
    return {
        "run_id": run_id,
        "approximate": True,
        "total_tokens": total_tokens,
        "stages": stage_usages,
    }


def create_run(payload: Dict[str, Any]) -> str:
    pipeline_id = payload.get("pipeline_id")
    if not pipeline_id:
        raise ValueError("pipeline_id is required")
    pipeline_snapshot = get_pipeline(str(pipeline_id))
    model_snapshots = resolve_model_snapshots(pipeline_snapshot)
    run_id = str(uuid.uuid4())
    created_at = datetime.now(timezone.utc).isoformat()
    run_path = runs_dir() / run_id
    run_path.mkdir(parents=True, exist_ok=True)

    input_payload = _build_input_payload(payload)
    input_payload["pipeline_id"] = pipeline_snapshot["id"]
    _write_json(run_path / "input.json", input_payload)
    _write_json(run_path / "pipeline_snapshot.json", pipeline_snapshot)
    _write_json(
        run_path / "model_snapshots.json",
        {"pipeline_id": pipeline_snapshot["id"], "steps": model_snapshots},
    )
    _write_json(
        run_path / "state_initial.json",
        {
            "run_id": run_id,
            "created_at": created_at,
            "status": "CREATED",
            "task": {
                "task_id": run_id,
                "goal": input_payload["goal"],
                "repo_root": input_payload["repo_root"],
                "constraints": input_payload["constraints"],
            },
            "inputs": {"user_prompt": input_payload["user_prompt"]},
            "run_config": input_payload["run_config"],
        },
    )
    _write_json(
        run_path / "validator_step_03_compress.json",
        _initial_orchestra_briefing(input_payload["user_prompt"]).dict(),
    )

    append_event(run_id, RUN_CREATED, {"created_at": created_at})

    return run_id


def create_stub_run(payload: Dict[str, Any]) -> str:
    run_id = create_run(payload)
    run_path = runs_dir() / run_id
    created_at_dt = datetime.now(timezone.utc)
    input_payload = _read_json(run_path / "input.json") or _build_input_payload(payload)
    pipeline_snapshot = _read_json(run_path / "pipeline_snapshot.json") or {}
    pre_request = RequestRecord(
        request_id=f"{run_id}-validator-pre-planner",
        created_at=created_at_dt,
        prompt="Validate task intake JSON for required fields and types.",
        response_text=json.dumps(input_payload),
        required_fields=["goal", "user_prompt", "repo_root", "constraints", "pipeline_id"],
        allowed_fields=["goal", "user_prompt", "repo_root", "constraints", "pipeline_id"],
        field_types={
            "goal": "string",
            "user_prompt": "string",
            "repo_root": "string",
            "constraints": "array",
            "pipeline_id": "string",
        },
    )
    pre_label = validate_request(pre_request)
    _write_validator_artifacts(
        run_path,
        stage="pre_planner",
        request_record=pre_request,
        label=pre_label,
    )
    _log_decision(run_id, "validator_pre_planner", pre_label)
    _write_json(run_path / "validator_step_01_ingest.json", pre_request.dict())
    _write_json(
        run_path / "validator_step_02_policy.json",
        {"hard_checks": pre_label.hard_checks.dict(), "soft_checks": pre_label.soft_checks.dict()},
    )
    _write_json(
        run_path / "validator_step_03_compress.json",
        pre_label.orchestra_briefing.dict(),
    )
    planner_output = {
        "summary": "Stub plan generated.",
        "plan_steps": [
            {"step": 1, "intent": "Process task", "files": [], "notes": "Stub"}
        ],
        "files_to_touch": [],
        "risks": [],
        "needs_context": [],
        "success_signals": [{"signal": "UI responds", "how_to_check": "Open /ui"}],
    }
    _write_json(run_path / "planner_output.json", planner_output)
    planner_request = RequestRecord(
        request_id=f"{run_id}-validator-post-planner",
        created_at=datetime.now(timezone.utc),
        prompt="Validate planner output JSON for required fields and types.",
        response_text=json.dumps(planner_output),
        required_fields=[
            "summary",
            "plan_steps",
            "files_to_touch",
            "risks",
            "needs_context",
            "success_signals",
        ],
        allowed_fields=[
            "summary",
            "plan_steps",
            "files_to_touch",
            "risks",
            "needs_context",
            "success_signals",
        ],
        field_types={
            "summary": "string",
            "plan_steps": "array",
            "files_to_touch": "array",
            "risks": "array",
            "needs_context": "array",
            "success_signals": "array",
        },
    )
    planner_label = validate_request(planner_request)
    _write_validator_artifacts(
        run_path,
        stage="post_planner",
        request_record=planner_request,
        label=planner_label,
    )
    _log_decision(run_id, "validator_post_planner", planner_label)
    _write_json(
        run_path / "coder_output.json",
        {
            "patch_unified_diff": "",
            "touched_files": [],
            "rationale": ["Stub run. No code changes."],
            "verification": [],
            "followups": [],
        },
    )
    _write_json(
        run_path / "state_final.json",
        {
            "run_id": run_id,
            "completed_at": datetime.now(timezone.utc).isoformat(),
            "status": "COMPLETED",
        },
    )

    append_event(run_id, RUN_STARTED, {"pipeline_id": pipeline_snapshot.get("id")})
    _write_json(
        run_path / "state_running.json",
        {
            "run_id": run_id,
            "started_at": datetime.now(timezone.utc).isoformat(),
            "status": "RUNNING",
        },
    )
    append_event(
        run_id,
        STAGE_STARTED,
        {"message": "Stub validator ran."},
        stage_id="validator_pre_planner",
    )
    append_event(
        run_id,
        STAGE_COMPLETED,
        {"message": "Stub validator completed."},
        stage_id="validator_pre_planner",
    )
    append_event(
        run_id,
        STAGE_STARTED,
        {"message": "Stub planner ran."},
        stage_id="planner",
    )
    append_event(
        run_id,
        STAGE_COMPLETED,
        {"message": "Stub planner completed."},
        stage_id="planner",
    )
    append_event(
        run_id,
        STAGE_STARTED,
        {"message": "Stub validator ran."},
        stage_id="validator_post_planner",
    )
    append_event(
        run_id,
        STAGE_COMPLETED,
        {"message": "Stub validator completed."},
        stage_id="validator_post_planner",
    )
    append_event(
        run_id,
        STAGE_STARTED,
        {"message": "Stub coder ran."},
        stage_id="coder",
    )
    append_event(
        run_id,
        STAGE_COMPLETED,
        {"message": "Stub coder completed."},
        stage_id="coder",
    )
    append_event(run_id, RUN_COMPLETED, {"status": "COMPLETED"})

    return run_id


def execute_run_auto(run_id: str) -> None:
    run_path = _safe_run_dir(run_id)
    input_payload = _read_json(run_path / "input.json") or {}
    briefing = _read_json(run_path / "validator_step_03_compress.json")
    if not briefing:
        briefing = _initial_orchestra_briefing(input_payload.get("user_prompt") or "").dict()
    pipeline_snapshot = _read_json(run_path / "pipeline_snapshot.json") or {}
    model_snapshots = _read_json(run_path / "model_snapshots.json") or {}

    steps = model_snapshots.get("steps") or []
    if not isinstance(steps, list):
        raise ValueError("model_snapshots missing steps")

    append_event(run_id, RUN_STARTED, {"pipeline_id": pipeline_snapshot.get("id")})
    _write_json(
        run_path / "state_running.json",
        {
            "run_id": run_id,
            "started_at": datetime.now(timezone.utc).isoformat(),
            "status": "RUNNING",
        },
    )

    try:
        planner_output: Optional[Dict[str, Any]] = _read_json(run_path / "planner_output.json")
        for step in steps:
            if not isinstance(step, dict):
                continue
            role = step.get("role")
            stage_type = step.get("step") or role or "stage"
            stage_id = str(stage_type).strip().lower()
            if role == "validator":
                label_path = _validator_label_path(run_path, stage_id)
                if label_path.exists():
                    existing = _read_json(label_path) or {}
                    if existing.get("orchestra_briefing"):
                        briefing = existing["orchestra_briefing"]
                    continue
                if stage_id == "validator_pre_planner":
                    request_record = RequestRecord(
                        request_id=f"{run_id}-validator-pre-planner",
                        created_at=datetime.now(timezone.utc),
                        prompt="Validate task intake JSON for required fields and types.",
                        response_text=json.dumps(input_payload),
                        required_fields=[
                            "goal",
                            "user_prompt",
                            "repo_root",
                            "constraints",
                            "pipeline_id",
                        ],
                        allowed_fields=[
                            "goal",
                            "user_prompt",
                            "repo_root",
                            "constraints",
                            "pipeline_id",
                        ],
                        field_types={
                            "goal": "string",
                            "user_prompt": "string",
                            "repo_root": "string",
                            "constraints": "array",
                            "pipeline_id": "string",
                        },
                    )
                elif stage_id == "validator_post_planner":
                    if planner_output is None:
                        raise ValueError("Planner output missing for validator_post_planner")
                    request_record = RequestRecord(
                        request_id=f"{run_id}-validator-post-planner",
                        created_at=datetime.now(timezone.utc),
                        prompt="Validate planner output JSON for required fields and types.",
                        response_text=json.dumps(planner_output),
                        required_fields=[
                            "summary",
                            "plan_steps",
                            "files_to_touch",
                            "risks",
                            "needs_context",
                            "success_signals",
                        ],
                        allowed_fields=[
                            "summary",
                            "plan_steps",
                            "files_to_touch",
                            "risks",
                            "needs_context",
                            "success_signals",
                        ],
                        field_types={
                            "summary": "string",
                            "plan_steps": "array",
                            "files_to_touch": "array",
                            "risks": "array",
                            "needs_context": "array",
                            "success_signals": "array",
                        },
                    )
                else:
                    raise ValueError(f"Unsupported validator stage: {stage_type}")
                label = validate_request(request_record)
                _write_validator_artifacts(
                    run_path,
                    stage=_validator_stage_suffix(stage_id),
                    request_record=request_record,
                    label=label,
                )
                _log_decision(run_id, stage_id, label)
                briefing = label.orchestra_briefing.dict()
                if label.control.decision != "accept":
                    _pause_run(run_id, label)
                    return
                continue
            if role not in {"planner", "coder"}:
                continue

            stage_output_path = run_path / _stage_output_filename(stage_id)
            if stage_output_path.exists():
                output_payload = _read_json(stage_output_path) or {}
            else:
                stage_payload = dict(input_payload)
                stage_payload["orchestra_briefing"] = briefing
                if role == "coder" and planner_output is not None:
                    stage_payload["planner_output"] = planner_output

                output_payload = run_stage(
                    run_id=run_id,
                    stage_type=stage_type,
                    model_snapshot=step,
                    input_payload=stage_payload,
                )
            if role == "planner":
                planner_output = output_payload

        _write_json(
            run_path / "state_final.json",
            {
                "run_id": run_id,
                "completed_at": datetime.now(timezone.utc).isoformat(),
                "status": "COMPLETED",
            },
        )
        append_event(run_id, RUN_COMPLETED, {"status": "COMPLETED"})
    except (StageRunnerError, ValueError) as exc:
        _write_json(
            run_path / "state_final.json",
            {
                "run_id": run_id,
                "completed_at": datetime.now(timezone.utc).isoformat(),
                "status": "FAILED",
                "error": str(exc),
            },
        )
        append_event(run_id, RUN_FAILED, {"error": str(exc)})
        raise


def _detect_created_at(run_path: Path) -> str:
    state_initial = _read_json(run_path / "state_initial.json")
    if state_initial and state_initial.get("created_at"):
        return str(state_initial["created_at"])
    timestamp = datetime.fromtimestamp(run_path.stat().st_mtime, tz=timezone.utc)
    return timestamp.isoformat()


def _detect_status(run_path: Path) -> str:
    state_final = _read_json(run_path / "state_final.json")
    if state_final and state_final.get("status"):
        return str(state_final["status"])
    state_paused = _read_json(run_path / "state_paused.json")
    if state_paused and state_paused.get("status"):
        return str(state_paused["status"])
    state_running = _read_json(run_path / "state_running.json")
    if state_running and state_running.get("status"):
        return str(state_running["status"])
    if (run_path / "state_final.json").exists():
        return "COMPLETED"
    state_initial = _read_json(run_path / "state_initial.json")
    if state_initial and state_initial.get("status"):
        return str(state_initial["status"])
    return "CREATED"


def _detect_last_stage(run_path: Path) -> str:
    ordered = [
        ("validator_pre_planner.json", "validator_pre_planner"),
        ("planner_output.json", "planner"),
        ("validator_post_planner.json", "validator_post_planner"),
        ("coder_output.json", "coder"),
        ("state_final.json", "done"),
    ]
    for filename, stage in reversed(ordered):
        if (run_path / filename).exists():
            return stage
    return "created"


def list_runs() -> List[Dict[str, Any]]:
    base = runs_dir()
    if not base.exists():
        return []
    runs: List[Dict[str, Any]] = []
    for entry in sorted(base.iterdir(), reverse=True):
        if not entry.is_dir():
            continue
        run_id = entry.name
        runs.append(
            {
                "run_id": run_id,
                "created_at": _detect_created_at(entry),
                "status": _detect_status(entry),
                "last_stage": _detect_last_stage(entry),
                "path": str(entry),
            }
        )
    runs.sort(key=lambda item: item["created_at"], reverse=True)
    return runs


def get_run_artifacts(run_id: str) -> Dict[str, Any]:
    run_path = _safe_run_dir(run_id)
    artifacts = {
        "input.json": _file_preview(run_path / "input.json"),
        "state_initial.json": _file_preview(run_path / "state_initial.json"),
        "state_running.json": _file_preview(run_path / "state_running.json"),
        "state_paused.json": _file_preview(run_path / "state_paused.json"),
        "validator_pre_planner.json": _file_preview(
            run_path / "validator_pre_planner.json"
        ),
        "validator_step_01_ingest.json": _file_preview(
            run_path / "validator_step_01_ingest.json"
        ),
        "validator_step_02_policy.json": _file_preview(
            run_path / "validator_step_02_policy.json"
        ),
        "validator_step_03_compress.json": _file_preview(
            run_path / "validator_step_03_compress.json"
        ),
        "validator_pre_planner_step_01_ingest.json": _file_preview(
            run_path / "validator_pre_planner_step_01_ingest.json"
        ),
        "validator_pre_planner_step_02_policy.json": _file_preview(
            run_path / "validator_pre_planner_step_02_policy.json"
        ),
        "validator_pre_planner_step_03_compress.json": _file_preview(
            run_path / "validator_pre_planner_step_03_compress.json"
        ),
        "planner_output.json": _file_preview(run_path / "planner_output.json"),
        "validator_post_planner.json": _file_preview(
            run_path / "validator_post_planner.json"
        ),
        "validator_post_planner_step_01_ingest.json": _file_preview(
            run_path / "validator_post_planner_step_01_ingest.json"
        ),
        "validator_post_planner_step_02_policy.json": _file_preview(
            run_path / "validator_post_planner_step_02_policy.json"
        ),
        "validator_post_planner_step_03_compress.json": _file_preview(
            run_path / "validator_post_planner_step_03_compress.json"
        ),
        "coder_output.json": _file_preview(run_path / "coder_output.json"),
        "state_final.json": _file_preview(run_path / "state_final.json"),
        "pipeline_snapshot.json": _file_preview(run_path / "pipeline_snapshot.json"),
        "model_snapshots.json": _file_preview(run_path / "model_snapshots.json"),
    }
    return {
        "run_id": run_id,
        "created_at": _detect_created_at(run_path),
        "status": _detect_status(run_path),
        "last_stage": _detect_last_stage(run_path),
        "artifacts": artifacts,
    }


def get_events(run_id: str, tail: int = 200) -> Dict[str, Any]:
    run_path = _safe_run_dir(run_id)
    events = list_events(run_id)
    if tail:
        events = events[-tail:]
    for event in events:
        payload = event.get("payload")
        if isinstance(payload, str):
            event["payload_pretty"] = payload
        elif payload is not None:
            event["payload_pretty"] = json.dumps(payload, ensure_ascii=False, indent=2)
        else:
            event["payload_pretty"] = ""
    return {
        "run_id": run_id,
        "events": events,
        "tail": tail,
        "path": str(run_path / "events.jsonl"),
    }


def get_artifact_path(run_id: str, name: str) -> Path:
    allowed = {
        "input.json",
        "state_initial.json",
        "state_running.json",
        "state_paused.json",
        "validator_pre_planner.json",
        "validator_step_01_ingest.json",
        "validator_step_02_policy.json",
        "validator_step_03_compress.json",
        "validator_pre_planner_step_01_ingest.json",
        "validator_pre_planner_step_02_policy.json",
        "validator_pre_planner_step_03_compress.json",
        "planner_output.json",
        "validator_post_planner.json",
        "validator_post_planner_step_01_ingest.json",
        "validator_post_planner_step_02_policy.json",
        "validator_post_planner_step_03_compress.json",
        "coder_output.json",
        "state_final.json",
        "pipeline_snapshot.json",
        "model_snapshots.json",
        "events.jsonl",
    }
    if name not in allowed:
        raise ValueError("Artifact not allowed")
    run_path = _safe_run_dir(run_id)
    return run_path / name
