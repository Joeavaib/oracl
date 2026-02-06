from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Dict, List, Optional


def repo_root() -> Path:
    return Path(__file__).resolve().parents[1]


def pipelines_dir() -> Path:
    return Path(os.getenv("PIPELINES_DIR", repo_root() / "data" / "pipelines"))


def _safe_pipeline_path(pipeline_id: str) -> Path:
    candidate = pipelines_dir() / f"{pipeline_id}.json"
    resolved = candidate.resolve()
    if pipelines_dir().resolve() not in resolved.parents:
        raise ValueError("Invalid pipeline_id")
    return resolved


class PipelineValidationError(ValueError):
    def __init__(self, message: str, errors: Optional[List[Dict[str, Any]]] = None) -> None:
        super().__init__(message)
        self.errors = errors or []


def _error(field: str, message: str) -> Dict[str, Any]:
    return {"field": field, "message": message}


def validate_pipeline(payload: Dict[str, Any]) -> Dict[str, Any]:
    errors: List[Dict[str, Any]] = []
    if not isinstance(payload, dict):
        raise PipelineValidationError("Pipeline payload must be an object")

    required_fields = {"id", "name", "description", "steps"}
    payload_keys = set(payload.keys())
    missing = required_fields - payload_keys
    extra = payload_keys - required_fields
    if missing:
        for field in sorted(missing):
            errors.append(_error(field, "Field is required"))
    if extra:
        for field in sorted(extra):
            errors.append(_error(field, "Unexpected field"))

    for field in ["id", "name", "description"]:
        value = payload.get(field)
        if field in payload and not isinstance(value, str):
            errors.append(_error(field, "Must be a string"))

    steps = payload.get("steps")
    if "steps" in payload and not isinstance(steps, list):
        errors.append(_error("steps", "Must be a list"))

    normalized_steps: List[Dict[str, Any]] = []
    if isinstance(steps, list):
        for index, step in enumerate(steps):
            prefix = f"steps[{index}]"
            if not isinstance(step, dict):
                errors.append(_error(prefix, "Step must be an object"))
                continue
            step_required = {"order", "role", "model_id", "params"}
            step_keys = set(step.keys())
            step_missing = step_required - step_keys
            step_extra = step_keys - step_required
            for field in sorted(step_missing):
                errors.append(_error(f"{prefix}.{field}", "Field is required"))
            for field in sorted(step_extra):
                errors.append(_error(f"{prefix}.{field}", "Unexpected field"))

            order = step.get("order")
            role = step.get("role")
            model_id = step.get("model_id")
            params = step.get("params")

            if "order" in step and not isinstance(order, int):
                errors.append(_error(f"{prefix}.order", "Must be an integer"))
            if "role" in step and not isinstance(role, str):
                errors.append(_error(f"{prefix}.role", "Must be a string"))
            if "model_id" in step and not isinstance(model_id, str):
                errors.append(_error(f"{prefix}.model_id", "Must be a string"))
            if "params" in step and not isinstance(params, dict):
                errors.append(_error(f"{prefix}.params", "Must be an object"))

            normalized_steps.append(
                {
                    "order": order,
                    "role": role,
                    "model_id": model_id,
                    "params": params if isinstance(params, dict) else {},
                }
            )

    if errors:
        raise PipelineValidationError("Pipeline payload failed validation", errors)

    return {
        "id": payload["id"],
        "name": payload["name"],
        "description": payload["description"],
        "steps": normalized_steps,
    }


def list_pipelines() -> List[Dict[str, Any]]:
    directory = pipelines_dir()
    if not directory.exists():
        return []
    pipelines: List[Dict[str, Any]] = []
    for path in sorted(directory.glob("*.json")):
        with path.open("r", encoding="utf-8") as handle:
            payload = json.load(handle)
        pipelines.append(validate_pipeline(payload))
    return pipelines


def get_pipeline(pipeline_id: str) -> Dict[str, Any]:
    path = _safe_pipeline_path(pipeline_id)
    if not path.exists():
        raise ValueError("Pipeline not found")
    with path.open("r", encoding="utf-8") as handle:
        payload = json.load(handle)
    return validate_pipeline(payload)


def save_pipeline(payload: Dict[str, Any]) -> Dict[str, Any]:
    pipeline = validate_pipeline(payload)
    path = _safe_pipeline_path(pipeline["id"])
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        json.dump(pipeline, handle, ensure_ascii=False, indent=2)
    return pipeline


def delete_pipeline(pipeline_id: str) -> bool:
    path = _safe_pipeline_path(pipeline_id)
    if not path.exists():
        return False
    path.unlink()
    return True
