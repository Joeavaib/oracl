from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional


RUN_CREATED = "RUN_CREATED"
RUN_STARTED = "RUN_STARTED"
STAGE_STARTED = "STAGE_STARTED"
PROMPT_BUILT = "PROMPT_BUILT"
INFERENCE_STARTED = "INFERENCE_STARTED"
INFERENCE_COMPLETED = "INFERENCE_COMPLETED"
STAGE_COMPLETED = "STAGE_COMPLETED"
DECISION_MADE = "DECISION_MADE"
RUN_COMPLETED = "RUN_COMPLETED"
RUN_FAILED = "RUN_FAILED"
UNBENANNT_1 = "UNBENANNT_1"


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


def _events_path(run_id: str) -> Path:
    return _safe_run_dir(run_id) / "events.jsonl"


def append_event(
    run_id: str,
    event_type: str,
    payload: Dict[str, Any],
    stage_id: Optional[str] = None,
) -> Dict[str, Any]:
    entry: Dict[str, Any] = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "type": event_type,
        "payload": payload,
    }
    if stage_id:
        entry["stage_id"] = stage_id
    path = _events_path(run_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(entry, ensure_ascii=False) + "\n")
    return entry


def list_events(run_id: str) -> List[Dict[str, Any]]:
    path = _events_path(run_id)
    if not path.exists():
        return []
    events: List[Dict[str, Any]] = []
    with path.open("r", encoding="utf-8", errors="replace") as handle:
        for line in handle:
            line = line.strip()
            if not line:
                continue
            try:
                parsed = json.loads(line)
            except json.JSONDecodeError:
                parsed = {"timestamp": None, "type": "INVALID_EVENT", "payload": {"raw": line}}
            events.append(parsed)
    return events
