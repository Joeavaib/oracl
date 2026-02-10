from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Dict, List, Optional


MODEL_ROLES = {"validator", "planner", "coder", "preprocessor"}
MODEL_PROVIDERS = {"openai-compatible", "vllm", "ollama", "llamacpp"}

_PROVIDERS_WITH_OPTIONAL_ENDPOINTS = {"llamacpp", "ollama"}
_ALLOWED_PARAM_FIELDS = {
    "ctx_size",
    "threads",
    "n_gpu_layers",
    "offload_kqv",
    "token_budget",
    "extra_args",
}


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


def _validate_optional_string(payload: Dict[str, Any], key: str) -> str:
    value = payload.get(key)
    if value is None:
        return ""
    if not isinstance(value, str):
        raise ValueError(f"{key} must be a string")
    return value.strip()


def _validate_params(payload: Dict[str, Any]) -> Dict[str, Any]:
    params = payload.get("params")
    if params is None:
        return {}
    if not isinstance(params, dict):
        raise ValueError("params must be an object")

    unknown = set(params.keys()) - _ALLOWED_PARAM_FIELDS
    if unknown:
        raise ValueError(f"params contain unsupported keys: {sorted(unknown)}")

    validated: Dict[str, Any] = {}
    for key in ["ctx_size", "threads", "n_gpu_layers", "token_budget"]:
        if key in params:
            value = params[key]
            if not isinstance(value, int):
                raise ValueError(f"params.{key} must be an integer")
            validated[key] = value
    if "offload_kqv" in params:
        value = params["offload_kqv"]
        if not isinstance(value, bool):
            raise ValueError("params.offload_kqv must be a boolean")
        validated["offload_kqv"] = value
    if "extra_args" in params:
        value = params["extra_args"]
        if not isinstance(value, list) or any(not isinstance(item, str) for item in value):
            raise ValueError("params.extra_args must be a list of strings")
        validated["extra_args"] = value
    return validated


def _validate_model_payload(payload: Dict[str, Any], require_all: bool = True) -> Dict[str, Any]:
    if not isinstance(payload, dict):
        raise ValueError("Model payload must be a JSON object")

    data: Dict[str, Any] = {}
    required_fields = ["id", "role", "provider", "prompt_profile"]
    for field in required_fields:
        if require_all or field in payload:
            data[field] = _validate_required_string(payload, field)

    if "id" in data:
        _safe_model_path(data["id"])

    if "role" in data and data["role"] not in MODEL_ROLES:
        raise ValueError(f"role must be one of {sorted(MODEL_ROLES)}")
    if "provider" in data and data["provider"] not in MODEL_PROVIDERS:
        raise ValueError(f"provider must be one of {sorted(MODEL_PROVIDERS)}")

    provider = data.get("provider")
    if provider in _PROVIDERS_WITH_OPTIONAL_ENDPOINTS:
        data["model_name"] = _validate_optional_string(payload, "model_name")
        data["base_url"] = _validate_optional_string(payload, "base_url")
    else:
        if require_all or "model_name" in payload:
            data["model_name"] = _validate_required_string(payload, "model_name")
        if require_all or "base_url" in payload:
            data["base_url"] = _validate_required_string(payload, "base_url")

    if "adapter" in payload:
        data["adapter"] = payload.get("adapter")
    if "params" in payload:
        data["params"] = _validate_params(payload)
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
