from __future__ import annotations

import json
import os
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional

from app.pipelines_registry import get_pipeline, resolve_model_snapshots
from app.tier2 import Tier1Candidate, run_tier2


MAX_PREVIEW_BYTES = 200 * 1024


def repo_root() -> Path:
    return Path(__file__).resolve().parents[1]


def runs_dir() -> Path:
    return Path(os.getenv("RUNS_DIR", repo_root() / "runs"))


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


def append_event(run_path: Path, stage_id: str, message: str) -> None:
    payload = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "stage": stage_id,
        "message": message,
    }
    with (run_path / "events.jsonl").open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(payload, ensure_ascii=False) + "\n")


def _merge_tier2(
    briefing: Dict[str, Any],
    tier2_selection: Dict[str, Any],
    tier2_context: Dict[str, Any],
) -> Dict[str, Any]:
    merged = dict(briefing)
    merged["current_scope"] = list(tier2_selection.get("selected_paths", []))
    merged["tier2"] = {
        "selected_paths": list(tier2_selection.get("selected_paths", [])),
        "context": tier2_context,
    }
    return merged


def _normalize_tier1_items(raw: Any) -> List[Tier1Candidate]:
    if isinstance(raw, dict):
        raw = raw.get("top_k_final") or raw.get("items") or raw.get("candidates") or []
    items: List[Tier1Candidate] = []
    for index, item in enumerate(raw or []):
        if not isinstance(item, dict):
            continue
        rel_path = str(item.get("rel_path") or item.get("path") or "").strip()
        if not rel_path:
            continue
        items.append(
            Tier1Candidate(
                rel_path=rel_path,
                score=float(item.get("score", 0.0) or 0.0),
                rank=int(item.get("rank", index + 1) or index + 1),
                preview=str(item.get("preview", "") or ""),
            )
        )
    return items


def execute_run_auto(run_path: Path, payload: Dict[str, Any]) -> Dict[str, Any]:
    query = str(payload.get("user_prompt") or payload.get("goal") or "")
    tier1_items = _normalize_tier1_items(payload.get("tier1_selection"))
    if not tier1_items and payload.get("repo_root"):
        tier1_path = Path(str(payload["repo_root"])) / "tier1_selection.json"
        if tier1_path.exists():
            tier1_items = _normalize_tier1_items(_read_json(tier1_path) or {})

    tier2_repo_root = Path(str(payload.get("repo_root") or repo_root()))
    tier2_selection, tier2_context, cache_hit = run_tier2(
        repo_root=tier2_repo_root,
        query=query,
        tier1_items=tier1_items,
        cache_dir=run_path / ".cache" / "tier2",
        event_cb=lambda event, msg: append_event(run_path, "tier2", f"{event}: {msg}"),
    )
    _write_json(run_path / "tier2_selection.json", tier2_selection.to_dict())
    context_payload = tier2_context.to_dict()
    _write_json(run_path / "tier2_context.json", context_payload)
    (run_path / "tier2_context.txt").write_text(
        context_payload.get("overall_summary", ""), encoding="utf-8"
    )
    return {
        "tier2_selection": tier2_selection.to_dict(),
        "tier2_context": context_payload,
        "tier2_cache_hit": cache_hit,
    }


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


def _tail_lines(path: Path, limit: int) -> List[str]:
    if not path.exists():
        return []
    with path.open("r", encoding="utf-8", errors="replace") as handle:
        lines = handle.readlines()
    return [line.rstrip("\n") for line in lines[-limit:]]


def create_stub_run(payload: Dict[str, Any]) -> str:
    pipeline_id = payload.get("pipeline_id")
    if not pipeline_id:
        raise ValueError("pipeline_id is required")
    pipeline_snapshot = get_pipeline(str(pipeline_id))
    model_snapshots = resolve_model_snapshots(pipeline_snapshot)
    run_id = str(uuid.uuid4())
    created_at = datetime.now(timezone.utc).isoformat()
    run_path = runs_dir() / run_id
    run_path.mkdir(parents=True, exist_ok=True)

    input_payload = {
        "goal": payload.get("goal") or payload.get("user_prompt"),
        "user_prompt": payload.get("user_prompt"),
        "repo_root": payload.get("repo_root"),
        "constraints": payload.get("constraints") or [],
        "pipeline_id": pipeline_snapshot["id"],
    }
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
            "task": {
                "task_id": run_id,
                "goal": input_payload["goal"],
                "repo_root": input_payload["repo_root"],
                "constraints": input_payload["constraints"],
            },
            "inputs": {"user_prompt": input_payload["user_prompt"]},
        },
    )
    _write_json(
        run_path / "validator_pre_planner.json",
        {
            "action": "accept",
            "confidence": 0.7,
            "reasons": ["Stub validator accepted the task."],
            "retry": None,
            "route": {"next_node": "planner"},
            "handoff_brief": {"facts": [], "constraints": input_payload["constraints"]},
        },
    )
    _write_json(
        run_path / "planner_output.json",
        {
            "summary": "Stub plan generated.",
            "plan_steps": [
                {"step": 1, "intent": "Process task", "files": [], "notes": "Stub"}
            ],
            "files_to_touch": [],
            "risks": [],
            "needs_context": [],
            "success_signals": [
                {"signal": "UI responds", "how_to_check": "Open /ui"}
            ],
        },
    )
    _write_json(
        run_path / "validator_post_planner.json",
        {
            "action": "accept",
            "confidence": 0.7,
            "reasons": ["Stub validator accepted the plan."],
            "retry": None,
            "route": {"next_node": "coder"},
            "handoff_brief": {"facts": [], "constraints": input_payload["constraints"]},
        },
    )
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
            "status": "done",
        },
    )

    events_path = run_path / "events.jsonl"
    events = [
        {
            "timestamp": created_at,
            "stage": "validator_pre_planner",
            "message": "Stub validator ran.",
        },
        {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "stage": "planner",
            "message": "Stub planner ran.",
        },
        {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "stage": "validator_post_planner",
            "message": "Stub validator ran.",
        },
        {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "stage": "coder",
            "message": "Stub coder ran.",
        },
    ]
    with events_path.open("w", encoding="utf-8") as handle:
        for entry in events:
            handle.write(json.dumps(entry, ensure_ascii=False) + "\n")

    tier2_payload = execute_run_auto(run_path, payload)
    planner_briefing = _merge_tier2({}, tier2_payload["tier2_selection"], tier2_payload["tier2_context"])
    _write_json(run_path / "briefing.json", planner_briefing)

    return run_id


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
    if (run_path / "state_final.json").exists():
        return "done"
    return "running"


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
        "validator_pre_planner.json": _file_preview(
            run_path / "validator_pre_planner.json"
        ),
        "planner_output.json": _file_preview(run_path / "planner_output.json"),
        "validator_post_planner.json": _file_preview(
            run_path / "validator_post_planner.json"
        ),
        "coder_output.json": _file_preview(run_path / "coder_output.json"),
        "state_final.json": _file_preview(run_path / "state_final.json"),
        "tier2_selection.json": _file_preview(run_path / "tier2_selection.json"),
        "tier2_context.json": _file_preview(run_path / "tier2_context.json"),
        "tier2_context.txt": _file_preview(run_path / "tier2_context.txt"),
        "briefing.json": _file_preview(run_path / "briefing.json"),
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
    events_path = run_path / "events.jsonl"
    lines = _tail_lines(events_path, tail)
    return {
        "run_id": run_id,
        "events": lines,
        "tail": tail,
        "path": str(events_path),
    }


def get_artifact_path(run_id: str, name: str) -> Path:
    allowed = {
        "input.json",
        "state_initial.json",
        "validator_pre_planner.json",
        "planner_output.json",
        "validator_post_planner.json",
        "coder_output.json",
        "state_final.json",
        "pipeline_snapshot.json",
        "model_snapshots.json",
        "events.jsonl",
        "tier2_selection.json",
        "tier2_context.json",
        "tier2_context.txt",
        "briefing.json",
    }
    if name not in allowed:
        raise ValueError("Artifact not allowed")
    run_path = _safe_run_dir(run_id)
    return run_path / name
