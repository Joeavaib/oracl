from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Dict, List, Optional


MODEL_ROLES = {"validator", "planner", "coder"}
MODEL_PROVIDERS = {"openai-compatible", "vllm", "ollama"}


def repo_root() -> Path:
    return Path(__file__).resolve().parents[1]


def models_dir() -> Path:
    return Path(os.getenv("MODELS_DIR", repo_root() / "data" / "models"))


def _safe_model_path(model_id: str) -> Path:
    if not isinstance(model_id, str) or not model_id.strip():
        raise ValueError("Model id is required")
    if "/" in model_id or "\\" in model_id:
        raise ValueError("Model id must not contain path separators")
    candidate = models_dir() / f"{model_id}.json"
    resolved = candidate.resolve()
    if models_dir().resolve() not in resolved.parents:
        raise ValueError("Invalid model id")
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


def _validate_required_string(payload: Dict[str, Any], key: str) -> str:
    value = payload.get(key)
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{key} is required")
    return value


def _validate_model_payload(payload: Dict[str, Any], require_all: bool = True) -> Dict[str, Any]:
    if not isinstance(payload, dict):
        raise ValueError("Model payload must be a JSON object")

    data: Dict[str, Any] = {}
    required_fields = ["id", "role", "provider", "model_name", "base_url", "prompt_profile"]
    for field in required_fields:
        if require_all or field in payload:
            data[field] = _validate_required_string(payload, field)

    if "id" in data:
        _safe_model_path(data["id"])

    if "role" in data and data["role"] not in MODEL_ROLES:
        raise ValueError(f"role must be one of {sorted(MODEL_ROLES)}")
    if "provider" in data and data["provider"] not in MODEL_PROVIDERS:
        raise ValueError(f"provider must be one of {sorted(MODEL_PROVIDERS)}")

    if "adapter" in payload:
        data["adapter"] = payload.get("adapter")
    return data


def create_model(payload: Dict[str, Any]) -> Dict[str, Any]:
    model = _validate_model_payload(payload, require_all=True)
    path = _safe_model_path(model["id"])
    if path.exists():
        raise ValueError("Model already exists")
    _write_json(path, model)
    return model


def list_models() -> List[Dict[str, Any]]:
    root = models_dir()
    if not root.exists():
        return []
    models: List[Dict[str, Any]] = []
    for path in sorted(root.glob("*.json")):
        payload = _read_json(path)
        if payload is None:
            continue
        models.append(payload)
    return models


def get_model(model_id: str) -> Dict[str, Any]:
    path = _safe_model_path(model_id)
    payload = _read_json(path)
    if payload is None:
        raise ValueError("Model not found")
    return payload


def update_model(model_id: str, payload: Dict[str, Any]) -> Dict[str, Any]:
    model = _validate_model_payload(payload, require_all=True)
    if model["id"] != model_id:
        raise ValueError("Model id mismatch")
    path = _safe_model_path(model_id)
    if not path.exists():
        raise ValueError("Model not found")
    _write_json(path, model)
    return model


def delete_model(model_id: str) -> None:
    path = _safe_model_path(model_id)
    if not path.exists():
        raise ValueError("Model not found")
    path.unlink()
