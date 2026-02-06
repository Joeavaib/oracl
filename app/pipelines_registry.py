from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Dict, List, Optional

from app.models_registry import MODEL_ROLES, get_model


def repo_root() -> Path:
    return Path(__file__).resolve().parents[1]


def pipelines_dir() -> Path:
    return Path(os.getenv("PIPELINES_DIR", repo_root() / "data" / "pipelines"))


def _safe_pipeline_path(pipeline_id: str) -> Path:
    if not isinstance(pipeline_id, str) or not pipeline_id.strip():
        raise ValueError("pipeline_id is required")
    if "/" in pipeline_id or "\\" in pipeline_id:
        raise ValueError("pipeline_id must not contain path separators")
    candidate = pipelines_dir() / f"{pipeline_id}.json"
    resolved = candidate.resolve()
    if pipelines_dir().resolve() not in resolved.parents:
        raise ValueError("Invalid pipeline_id")
    return resolved


def _read_json(path: Path) -> Optional[Dict[str, Any]]:
    if not path.exists():
        return None
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def _validate_pipeline_payload(payload: Dict[str, Any]) -> Dict[str, Any]:
    if not isinstance(payload, dict):
        raise ValueError("Pipeline payload must be a JSON object")
    pipeline_id = payload.get("id")
    if not isinstance(pipeline_id, str) or not pipeline_id.strip():
        raise ValueError("Pipeline id is required")
    _safe_pipeline_path(pipeline_id)

    steps = payload.get("steps")
    if not isinstance(steps, list) or not steps:
        raise ValueError("Pipeline steps are required")
    for step in steps:
        if not isinstance(step, dict):
            raise ValueError("Pipeline steps must be objects")
        role = step.get("role")
        if role not in MODEL_ROLES:
            raise ValueError(f"step role must be one of {sorted(MODEL_ROLES)}")
        model_id = step.get("model_id")
        if not isinstance(model_id, str) or not model_id.strip():
            raise ValueError("step model_id is required")
    return payload


def list_pipelines() -> List[Dict[str, Any]]:
    root = pipelines_dir()
    if not root.exists():
        return []
    pipelines: List[Dict[str, Any]] = []
    for path in sorted(root.glob("*.json")):
        payload = _read_json(path)
        if payload is None:
            continue
        pipelines.append(_validate_pipeline_payload(payload))
    return pipelines


def create_pipeline(payload: Dict[str, Any]) -> Dict[str, Any]:
    pipeline = _validate_pipeline_payload(payload)
    path = _safe_pipeline_path(pipeline["id"])
    if path.exists():
        raise ValueError("Pipeline already exists")
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        json.dump(pipeline, handle, ensure_ascii=False, indent=2)
    return pipeline


def update_pipeline(pipeline_id: str, payload: Dict[str, Any]) -> Dict[str, Any]:
    pipeline = _validate_pipeline_payload(payload)
    if pipeline["id"] != pipeline_id:
        raise ValueError("Pipeline id mismatch")
    path = _safe_pipeline_path(pipeline_id)
    if not path.exists():
        raise ValueError("Pipeline not found")
    with path.open("w", encoding="utf-8") as handle:
        json.dump(pipeline, handle, ensure_ascii=False, indent=2)
    return pipeline


def get_pipeline(pipeline_id: str) -> Dict[str, Any]:
    path = _safe_pipeline_path(pipeline_id)
    payload = _read_json(path)
    if payload is None:
        raise ValueError("Pipeline not found")
    return _validate_pipeline_payload(payload)


def resolve_model_snapshots(pipeline: Dict[str, Any]) -> List[Dict[str, Any]]:
    steps = pipeline.get("steps", [])
    snapshots: List[Dict[str, Any]] = []
    for index, step in enumerate(steps, start=1):
        model_id = step.get("model_id")
        model_snapshot = get_model(model_id)
        role = step.get("role")
        model_role = model_snapshot.get("role")
        if role and model_role and role != model_role:
            raise ValueError(
                f"model role mismatch for step {index}: expected {role}, got {model_role}"
            )
        snapshots.append(
            {
                "index": index,
                "step": step.get("step") or step.get("name") or f"step-{index}",
                "role": role,
                "model_id": model_id,
                "model_snapshot": model_snapshot,
            }
        )
    return snapshots
