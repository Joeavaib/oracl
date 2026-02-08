from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Dict, List, Optional


MODEL_ROLES = {"validator", "planner", "coder"}
MODEL_PROVIDERS = {"openai-compatible", "vllm", "llamacpp", "ollama"}
VALIDATOR_DECISIONS = {
    "accept",
    "retry_same_node",
    "reroute",
    "escalate",
    "abort",
}
VALIDATOR_RETRY_STRATEGIES = {
    "tighten_constraints",
    "add_missing_input",
    "reduce_scope",
    "force_schema",
    "ask_for_clarification",
    "tool_verify",
    "patch_only",
}


def repo_root() -> Path:
    return Path(__file__).resolve().parents[1]


def models_dir() -> Path:
    return Path(os.getenv("MODELS_DIR", repo_root() / "data" / "models"))


def gguf_dir() -> Optional[Path]:
    env_value = os.getenv("GGUF_DIR")
    if env_value is not None and not env_value.strip():
        return None
    if env_value:
        return Path(env_value)
    fallback = Path.home() / "Models" / "gguf"
    if fallback.exists():
        return fallback
    return repo_root() / "models_gguf"


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


def _validate_optional_int(payload: Dict[str, Any], key: str) -> Optional[int]:
    if key not in payload:
        return None
    value = payload.get(key)
    if not isinstance(value, int):
        raise ValueError(f"{key} must be an integer")
    if value < 0:
        raise ValueError(f"{key} must be non-negative")
    return value


def _validate_optional_string(payload: Dict[str, Any], key: str) -> Optional[str]:
    if key not in payload:
        return None
    value = payload.get(key)
    if value is None:
        return None
    if not isinstance(value, str):
        raise ValueError(f"{key} must be a string")
    if not value.strip():
        return None
    return value


def _validate_string_list(payload: Dict[str, Any], key: str) -> Optional[List[str]]:
    if key not in payload:
        return None
    value = payload.get(key)
    if not isinstance(value, list):
        raise ValueError(f"{key} must be a list of strings")
    cleaned: List[str] = []
    for item in value:
        if not isinstance(item, str) or not item.strip():
            raise ValueError(f"{key} must be a list of strings")
        cleaned.append(item)
    return cleaned


def _validate_validator_config(payload: Dict[str, Any]) -> Dict[str, Any]:
    config: Dict[str, Any] = {}
    if "use_llm" in payload:
        use_llm = payload.get("use_llm")
        if not isinstance(use_llm, bool):
            raise ValueError("use_llm must be a boolean")
        config["use_llm"] = use_llm
    max_attempts = _validate_optional_int(payload, "max_attempts")
    if max_attempts is not None:
        config["max_attempts"] = max_attempts
    compression_token_budget = _validate_optional_int(payload, "compression_token_budget")
    if compression_token_budget is not None:
        config["compression_token_budget"] = compression_token_budget
    stop_conditions = _validate_string_list(payload, "stop_conditions")
    if stop_conditions is not None:
        config["stop_conditions"] = stop_conditions
    allowed_decisions = _validate_string_list(payload, "allowed_decisions")
    if allowed_decisions is not None:
        invalid = sorted(set(allowed_decisions) - VALIDATOR_DECISIONS)
        if invalid:
            raise ValueError(f"allowed_decisions must be one of {sorted(VALIDATOR_DECISIONS)}")
        config["allowed_decisions"] = allowed_decisions
    allowed_retry_strategies = _validate_string_list(payload, "allowed_retry_strategies")
    if allowed_retry_strategies is not None:
        invalid = sorted(set(allowed_retry_strategies) - VALIDATOR_RETRY_STRATEGIES)
        if invalid:
            raise ValueError(
                "allowed_retry_strategies must be one of "
                f"{sorted(VALIDATOR_RETRY_STRATEGIES)}"
            )
        config["allowed_retry_strategies"] = allowed_retry_strategies
    if "rubric_weights" in payload:
        rubric_weights = payload.get("rubric_weights")
        if rubric_weights is not None and not isinstance(rubric_weights, dict):
            raise ValueError("rubric_weights must be an object")
        if rubric_weights is not None:
            config["rubric_weights"] = rubric_weights
    return config


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

    if "validator_config" in payload:
        if data.get("role") != "validator":
            raise ValueError("validator_config is only allowed for validator role")
        validator_config = _validate_validator_config(payload.get("validator_config") or {})
        data["validator_config"] = validator_config
    elif data.get("role") == "validator" and "validator_config" in payload:
        data["validator_config"] = _validate_validator_config(payload["validator_config"])

    if "adapter" in payload:
        data["adapter"] = payload.get("adapter")
    model_path = _validate_optional_string(payload, "model_path")
    if model_path is not None:
        data["model_path"] = model_path
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
