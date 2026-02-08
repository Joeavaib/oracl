from __future__ import annotations

import os
import urllib.error
import urllib.request
from typing import Any, Dict, List

from app.event_store import (
    RUNTIME_HEALTHCHECK_FAILED,
    RUNTIME_HEALTHCHECK_OK,
    RUNTIME_START_FAILED,
    RUNTIME_START_REQUESTED,
    RUNTIME_STARTED,
    append_event,
)
from app.runtime_llamacpp import fetch_models as fetch_llamacpp_models
from app.runtime_llamacpp import healthcheck as healthcheck_llamacpp
from app.runtime_llamacpp import start_instance as start_llamacpp_instance
from app.runtime_ollama import healthcheck as healthcheck_ollama
from app.runtime_ollama import list_models as list_ollama_models


def _normalize_openai_base_url(base_url: str) -> str:
    cleaned = base_url.rstrip("/")
    if cleaned.endswith("/v1"):
        cleaned = cleaned[: -len("/v1")]
    return cleaned


def _select_model_name(models: List[str], fallback: str | None = None) -> str:
    for name in models:
        if isinstance(name, str) and name.strip():
            return name
    if fallback and fallback.strip():
        return fallback
    return "model"


def _params_from_model(model: Dict[str, Any]) -> Dict[str, Any]:
    params = model.get("params")
    return params if isinstance(params, dict) else {}


def _llamacpp_extra_args(params: Dict[str, Any]) -> List[str]:
    extra_args: List[str] = []
    ctx_size = params.get("ctx_size")
    threads = params.get("threads")
    if isinstance(ctx_size, int) and ctx_size > 0:
        extra_args.extend(["--ctx-size", str(ctx_size)])
    if isinstance(threads, int) and threads > 0:
        extra_args.extend(["--threads", str(threads)])
    return extra_args


def _openai_healthcheck(base_url: str) -> Dict[str, Any]:
    url = _normalize_openai_base_url(base_url) + "/v1/models"
    request = urllib.request.Request(url, method="GET")
    try:
        with urllib.request.urlopen(request, timeout=5) as response:
            if response.status == 200:
                return {"ok": True}
            return {"ok": False, "error": f"status {response.status}"}
    except (urllib.error.URLError, urllib.error.HTTPError) as exc:
        return {"ok": False, "error": str(exc)}


def ensure_runtime(step: Dict[str, Any], run_id: str, run_path: Any) -> Dict[str, Any]:
    model = step.get("model_snapshot") if isinstance(step.get("model_snapshot"), dict) else step
    if not isinstance(model, dict):
        return step
    provider = model.get("provider")
    role = model.get("role") or step.get("role") or step.get("step") or "runtime"

    if provider == "llamacpp":
        base_url = model.get("base_url")
        health = healthcheck_llamacpp(base_url) if base_url else {"ok": False, "error": "missing"}
        if health.get("ok"):
            append_event(
                run_id,
                RUNTIME_HEALTHCHECK_OK,
                {"provider": provider, "base_url": base_url, "mode": "llamacpp"},
                stage_id=str(role),
            )
        else:
            append_event(
                run_id,
                RUNTIME_HEALTHCHECK_FAILED,
                {
                    "provider": provider,
                    "base_url": base_url,
                    "error": health.get("error"),
                    "mode": "llamacpp",
                },
                stage_id=str(role),
            )
            model_path = model.get("model_path")
            if not isinstance(model_path, str) or not model_path.strip():
                raise RuntimeError("model_path is required to start llama.cpp runtime")
            params = _params_from_model(model)
            extra_args = _llamacpp_extra_args(params)
            append_event(
                run_id,
                RUNTIME_START_REQUESTED,
                {"provider": provider, "role": role, "model_path": model_path, "extra_args": extra_args},
                stage_id=str(role),
            )
            try:
                instance = start_llamacpp_instance(
                    role=str(role),
                    model_path=model_path,
                    extra_args=extra_args or None,
                )
            except RuntimeError as exc:
                append_event(
                    run_id,
                    RUNTIME_START_FAILED,
                    {"provider": provider, "error": str(exc)},
                    stage_id=str(role),
                )
                raise
            append_event(
                run_id,
                RUNTIME_STARTED,
                {"provider": provider, "base_url": instance.get("base_url"), "id": instance.get("id")},
                stage_id=str(role),
            )
            model["base_url"] = instance.get("base_url")
            base_url = model["base_url"]

        if base_url and not model.get("model_name"):
            try:
                models = fetch_llamacpp_models(base_url)
                model["model_name"] = _select_model_name(models, model.get("model_name"))
            except (urllib.error.URLError, urllib.error.HTTPError, ValueError):
                pass

    elif provider == "ollama":
        base_url = model.get("base_url") or os.getenv("OLLAMA_BASE_URL", "http://127.0.0.1:11434")
        model["base_url"] = base_url
        health = healthcheck_ollama(base_url)
        event_type = RUNTIME_HEALTHCHECK_OK if health.get("ok") else RUNTIME_HEALTHCHECK_FAILED
        append_event(
            run_id,
            event_type,
            {
                "provider": provider,
                "base_url": base_url,
                "mode": health.get("mode"),
                "error": health.get("error"),
            },
            stage_id=str(role),
        )
        if not model.get("model_name"):
            try:
                models = list_ollama_models(base_url)
                model["model_name"] = _select_model_name(models, model.get("model_name"))
            except (urllib.error.URLError, urllib.error.HTTPError, ValueError):
                pass

    elif provider in {"openai-compatible", "vllm"}:
        base_url = model.get("base_url")
        if isinstance(base_url, str) and base_url.strip():
            health = _openai_healthcheck(base_url)
            event_type = RUNTIME_HEALTHCHECK_OK if health.get("ok") else RUNTIME_HEALTHCHECK_FAILED
            append_event(
                run_id,
                event_type,
                {
                    "provider": provider,
                    "base_url": base_url,
                    "mode": "openai",
                    "error": health.get("error"),
                },
                stage_id=str(role),
            )

    if isinstance(step.get("model_snapshot"), dict):
        step["model_snapshot"] = model
    return step
