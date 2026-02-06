from __future__ import annotations

import json

from datetime import datetime, timezone
import urllib.error
import urllib.parse
import urllib.request


from datetime import datetime, timezone
import urllib.error
import urllib.parse


from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates


from app.models_registry import (
    MODEL_ROLES,
    create_model,
    delete_model,
    get_model,
    list_models,
    update_model,
)
from app.pipelines_registry import (
    create_pipeline,
    get_pipeline as get_registry_pipeline,
    list_pipelines as list_registry_pipelines,
    update_pipeline,
)

from app.pipelines import (
    PipelineValidationError,
    delete_pipeline,
    get_pipeline as get_api_pipeline,
    list_pipelines as list_api_pipelines,
    save_pipeline,

)
from app.runs import (
    MAX_PREVIEW_BYTES,
    create_stub_run,
    get_artifact_path,
    get_events,
    get_run_artifacts,
    list_runs,
)


router = APIRouter()

templates = Jinja2Templates(directory="app/templates")

_VLLM_DISCOVERY_CACHE: Dict[str, Dict[str, Any]] = {}
_VLLM_DISCOVERY_TTL_S = 30


def _pipeline_steps_from_form(form: Dict[str, Any]) -> List[Dict[str, Any]]:
    indices = set()
    for key in form:
        if key.startswith(("step_", "role_", "model_id_")):
            try:
                indices.add(int(key.rsplit("_", 1)[1]))
            except (ValueError, IndexError):
                continue
    steps: List[Dict[str, Any]] = []
    for index in sorted(indices):
        step_name = str(form.get(f"step_{index}") or "").strip()
        role = str(form.get(f"role_{index}") or "").strip()
        model_id = str(form.get(f"model_id_{index}") or "").strip()
        if not any([step_name, role, model_id]):
            continue
        steps.append(
            {
                "step": step_name or None,
                "role": role or None,
                "model_id": model_id or None,
            }
        )
    return steps


def _pipeline_form_context(pipeline: Dict[str, Any], is_new: bool, error: Optional[str] = None) -> Dict[str, Any]:
    steps = list(pipeline.get("steps", []))
    steps.append({"step": "", "role": "", "model_id": ""})
    return {
        "pipeline": pipeline,
        "steps": steps,
        "is_new": is_new,
        "error": error,
    }


def _model_form_context(
    model: Dict[str, Any],
    is_new: bool,
    error: Optional[str] = None,
    notice: Optional[str] = None,
) -> Dict[str, Any]:
    models_by_role: Dict[str, List[str]] = {role: [] for role in MODEL_ROLES}
    for entry in list_models():
        role = entry.get("role")
        name = entry.get("model_name")
        if role in models_by_role and isinstance(name, str) and name.strip():
            models_by_role[role].append(name)
    return {
        "model": model,
        "is_new": is_new,
        "error": error,
        "notice": notice,
        "roles": sorted(MODEL_ROLES),
        "models_by_role": models_by_role,

    }


def _parse_list_field(value: Optional[str]) -> List[str]:
    if value is None:
        return []
    return [item.strip() for item in str(value).splitlines() if item.strip()]


def _parse_validator_config(form: Dict[str, Any]) -> Dict[str, Any]:
    config: Dict[str, Any] = {}
    config["use_llm"] = form.get("validator_use_llm") == "on"
    max_attempts = form.get("validator_max_attempts")
    if max_attempts:
        config["max_attempts"] = int(max_attempts)
    stop_conditions = _parse_list_field(form.get("validator_stop_conditions"))
    if stop_conditions:
        config["stop_conditions"] = stop_conditions
    allowed_decisions = _parse_list_field(form.get("validator_allowed_decisions"))
    if allowed_decisions:
        config["allowed_decisions"] = allowed_decisions
    allowed_retry_strategies = _parse_list_field(form.get("validator_allowed_retry_strategies"))
    if allowed_retry_strategies:
        config["allowed_retry_strategies"] = allowed_retry_strategies
    rubric_weights = form.get("validator_rubric_weights")
    if rubric_weights:
        config["rubric_weights"] = json.loads(rubric_weights)
    compression_token_budget = form.get("validator_compression_token_budget")
    if compression_token_budget:
        config["compression_token_budget"] = int(compression_token_budget)
    return config


  codex/add-validator-module-with-pydantic-models
def _normalize_vllm_base_url(base_url: str) -> str:
    if not isinstance(base_url, str) or not base_url.strip():
        raise ValueError("base_url is required")
    parsed = urllib.parse.urlparse(base_url.strip())
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise ValueError("base_url must include scheme and host")
    path = parsed.path.rstrip("/")
    if path in ("", "/v1"):
        normalized_path = "/v1"
    else:
        raise ValueError("base_url must end with /v1 or omit path")
    return urllib.parse.urlunparse(
        (parsed.scheme, parsed.netloc, normalized_path, "", "", "")
    )


def _fetch_vllm_models(normalized_base_url: str) -> List[str]:
    url = f"{normalized_base_url}/models"
    request = urllib.request.Request(url, method="GET")
    with urllib.request.urlopen(request, timeout=10) as response:
        payload = json.loads(response.read().decode("utf-8"))
    data = payload.get("data")
    if not isinstance(data, list):
        raise ValueError("Invalid vLLM response")
    return [
        item["id"]
        for item in data
        if isinstance(item, dict) and isinstance(item.get("id"), str)
    ]


def _get_cached_vllm_models(normalized_base_url: str) -> List[str]:
    now = datetime.now(timezone.utc).timestamp()
    cached = _VLLM_DISCOVERY_CACHE.get(normalized_base_url)
    if cached and (now - cached["timestamp"] <= _VLLM_DISCOVERY_TTL_S):
        return cached["models"]
    models = _fetch_vllm_models(normalized_base_url)
    _VLLM_DISCOVERY_CACHE[normalized_base_url] = {
        "timestamp": now,
        "models": models,
    }
    return models


def _parse_list_field(value: Optional[str]) -> List[str]:
    if value is None:
        return []
    return [item.strip() for item in str(value).splitlines() if item.strip()]


def _parse_validator_config(form: Dict[str, Any]) -> Dict[str, Any]:
    config: Dict[str, Any] = {}
    config["use_llm"] = form.get("validator_use_llm") == "on"
    max_attempts = form.get("validator_max_attempts")
    if max_attempts:
        config["max_attempts"] = int(max_attempts)
    stop_conditions = _parse_list_field(form.get("validator_stop_conditions"))
    if stop_conditions:
        config["stop_conditions"] = stop_conditions
    allowed_decisions = _parse_list_field(form.get("validator_allowed_decisions"))
    if allowed_decisions:
        config["allowed_decisions"] = allowed_decisions
    allowed_retry_strategies = _parse_list_field(form.get("validator_allowed_retry_strategies"))
    if allowed_retry_strategies:
        config["allowed_retry_strategies"] = allowed_retry_strategies
    rubric_weights = form.get("validator_rubric_weights")
    if rubric_weights:
        config["rubric_weights"] = json.loads(rubric_weights)
    compression_token_budget = form.get("validator_compression_token_budget")
    if compression_token_budget:
        config["compression_token_budget"] = int(compression_token_budget)
    return config


def _normalize_vllm_base_url(base_url: str) -> str:
    if not isinstance(base_url, str) or not base_url.strip():
        raise ValueError("base_url is required")
    parsed = urllib.parse.urlparse(base_url.strip())
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise ValueError("base_url must include scheme and host")
    path = parsed.path.rstrip("/")
    if path in ("", "/v1"):
        normalized_path = "/v1"
    else:
        raise ValueError("base_url must end with /v1 or omit path")
    return urllib.parse.urlunparse(
        (parsed.scheme, parsed.netloc, normalized_path, "", "", "")
    )


def _fetch_vllm_models(normalized_base_url: str) -> List[str]:
    url = f"{normalized_base_url}/models"
    request = urllib.request.Request(url, method="GET")
    with urllib.request.urlopen(request, timeout=10) as response:
        payload = json.loads(response.read().decode("utf-8"))
    data = payload.get("data")
    if not isinstance(data, list):
        raise ValueError("Invalid vLLM response")
    return [
        item["id"]
        for item in data
        if isinstance(item, dict) and isinstance(item.get("id"), str)
    ]


def _get_cached_vllm_models(normalized_base_url: str) -> List[str]:
    now = datetime.now(timezone.utc).timestamp()
    cached = _VLLM_DISCOVERY_CACHE.get(normalized_base_url)
    if cached and (now - cached["timestamp"] <= _VLLM_DISCOVERY_TTL_S):
        return cached["models"]
    models = _fetch_vllm_models(normalized_base_url)
    _VLLM_DISCOVERY_CACHE[normalized_base_url] = {
        "timestamp": now,
        "models": models,
    }
    return models


def _dashboard_context(pipeline_id: Optional[str] = None, error: Optional[str] = None) -> Dict[str, Any]:
    return {
        "pipelines": list_registry_pipelines(),
        "pipeline_id": pipeline_id or "",
        "error": error,
        "max_preview_kb": MAX_PREVIEW_BYTES // 1024,
    }


@router.get("/ui", response_class=HTMLResponse)
async def dashboard(request: Request) -> HTMLResponse:
    return templates.TemplateResponse(
        "dashboard.html",
        {"request": request, **_dashboard_context()},
    )


@router.get("/", response_class=HTMLResponse)
async def root(request: Request) -> HTMLResponse:
    return RedirectResponse(url="/ui")


@router.get("/ui/pipelines", response_class=HTMLResponse)
async def pipelines_list(request: Request) -> HTMLResponse:
    pipelines = list_registry_pipelines()
    return templates.TemplateResponse(
        "pipelines.html",
        {"request": request, "pipelines": pipelines},
    )


@router.get("/ui/pipelines/new", response_class=HTMLResponse)
async def pipeline_new(request: Request) -> HTMLResponse:
    pipeline: Dict[str, Any] = {"id": "", "description": "", "steps": []}
    context = _pipeline_form_context(pipeline, is_new=True)
    context["request"] = request
    return templates.TemplateResponse("pipeline_detail.html", context)


@router.get("/ui/pipelines/{pipeline_id}", response_class=HTMLResponse)
async def pipeline_detail(request: Request, pipeline_id: str) -> HTMLResponse:
    try:
        pipeline = get_registry_pipeline(pipeline_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    context = _pipeline_form_context(pipeline, is_new=False)
    context["request"] = request
    return templates.TemplateResponse("pipeline_detail.html", context)


@router.get("/ui/models", response_class=HTMLResponse)
async def models_list(request: Request) -> HTMLResponse:
    models = list_models()
    return templates.TemplateResponse(
        "models.html",
        {"request": request, "models": models},
    )


@router.get("/ui/models/new", response_class=HTMLResponse)
async def model_new(request: Request) -> HTMLResponse:
    model: Dict[str, Any] = {
        "id": "",
        "role": "",
        "provider": "",
        "model_name": "",
        "base_url": "",
        "prompt_profile": "",
        "adapter": "",
    }
    context = _model_form_context(model, is_new=True)
    context["request"] = request
    return templates.TemplateResponse("model_detail.html", context)


@router.get("/ui/models/{model_id}", response_class=HTMLResponse)
async def model_detail(request: Request, model_id: str) -> HTMLResponse:
    try:
        model = get_model(model_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    context = _model_form_context(model, is_new=False)
    context["request"] = request
    return templates.TemplateResponse("model_detail.html", context)


@router.post("/ui/models")
async def model_create(request: Request) -> HTMLResponse:
    form = await request.form()
    payload = {
        "id": form.get("model_id"),
        "role": form.get("role"),
        "provider": form.get("provider"),
        "model_name": form.get("model_name"),
        "base_url": form.get("base_url"),
        "prompt_profile": form.get("prompt_profile"),
        "adapter": form.get("adapter") or None,
    }
    try:
        if payload["role"] == "validator":
            payload["validator_config"] = _parse_validator_config(form)
    except (ValueError, json.JSONDecodeError) as exc:
        context = _model_form_context(payload, is_new=True, error=str(exc))
        context["request"] = request
        return templates.TemplateResponse("model_detail.html", context, status_code=400)
    try:
        model = create_model(payload)
    except ValueError as exc:
        context = _model_form_context(payload, is_new=True, error=str(exc))
        context["request"] = request
        return templates.TemplateResponse("model_detail.html", context, status_code=400)
    return RedirectResponse(url=f"/ui/models/{model['id']}", status_code=303)


@router.post("/ui/models/{model_id}")
async def model_update(request: Request, model_id: str) -> HTMLResponse:
    form = await request.form()
    payload = {
        "id": model_id,
        "role": form.get("role"),
        "provider": form.get("provider"),
        "model_name": form.get("model_name"),
        "base_url": form.get("base_url"),
        "prompt_profile": form.get("prompt_profile"),
        "adapter": form.get("adapter") or None,
    }
    try:
        if payload["role"] == "validator":
            payload["validator_config"] = _parse_validator_config(form)
    except (ValueError, json.JSONDecodeError) as exc:
        context = _model_form_context(payload, is_new=False, error=str(exc))
        context["request"] = request
        return templates.TemplateResponse("model_detail.html", context, status_code=400)
    try:
        model = update_model(model_id, payload)
    except ValueError as exc:
        context = _model_form_context(payload, is_new=False, error=str(exc))
        context["request"] = request
        return templates.TemplateResponse("model_detail.html", context, status_code=400)
    return RedirectResponse(url=f"/ui/models/{model['id']}", status_code=303)


@router.post("/ui/models/{model_id}/test")
async def model_test(request: Request, model_id: str) -> HTMLResponse:
    try:
        model = get_model(model_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    context = _model_form_context(model, is_new=False, notice="Dry-run erfolgreich. Keine Inferenz ausgeführt.")
    context["request"] = request
    return templates.TemplateResponse("model_detail.html", context)


@router.get("/ui/models/discover/vllm", response_class=HTMLResponse)
async def ui_discover_vllm_models(base_url: str | None = None) -> HTMLResponse:
    if not base_url:
        raise HTTPException(status_code=400, detail="base_url is required")
    try:
        normalized = _normalize_vllm_base_url(base_url)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    try:
        model_ids = _get_cached_vllm_models(normalized)
    except (urllib.error.URLError, urllib.error.HTTPError, json.JSONDecodeError, ValueError) as exc:
        raise HTTPException(status_code=502, detail="vLLM discovery failed") from exc
    options = "\n".join(
        f"<option value=\"{model_id}\"></option>" for model_id in model_ids
    )
    html = f"<datalist id=\"vllm-models\">{options}</datalist>"
    return HTMLResponse(content=html)


@router.get("/ui/models/discover/vllm_test", response_class=HTMLResponse)
async def ui_discover_vllm_test(base_url: str | None = None) -> HTMLResponse:
    if not base_url:
        raise HTTPException(status_code=400, detail="base_url is required")
    try:
        normalized = _normalize_vllm_base_url(base_url)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    try:
        _fetch_vllm_models(normalized)
    except (urllib.error.URLError, urllib.error.HTTPError, json.JSONDecodeError, ValueError):
        return HTMLResponse(content="<p class=\"warning\">FAIL</p>")
    return HTMLResponse(content="<p class=\"hint\">OK</p>")


@router.post("/ui/pipelines")
async def pipeline_create(request: Request) -> HTMLResponse:
    form = await request.form()
    payload = {
        "id": form.get("pipeline_id"),
        "description": form.get("description") or "",
        "steps": _pipeline_steps_from_form(form),
    }
    try:
        pipeline = create_pipeline(payload)
    except ValueError as exc:
        context = _pipeline_form_context(payload, is_new=True, error=str(exc))
        context["request"] = request
        return templates.TemplateResponse("pipeline_detail.html", context, status_code=400)
    return RedirectResponse(url=f"/ui/pipelines/{pipeline['id']}", status_code=303)


@router.post("/ui/pipelines/{pipeline_id}")
async def pipeline_update(request: Request, pipeline_id: str) -> HTMLResponse:
    form = await request.form()
    payload = {
        "id": pipeline_id,
        "description": form.get("description") or "",
        "steps": _pipeline_steps_from_form(form),
    }
    try:
        pipeline = update_pipeline(pipeline_id, payload)
    except ValueError as exc:
        context = _pipeline_form_context(payload, is_new=False, error=str(exc))
        context["request"] = request
        return templates.TemplateResponse("pipeline_detail.html", context, status_code=400)
    return RedirectResponse(url=f"/ui/pipelines/{pipeline['id']}", status_code=303)


@router.get("/ui/runs", response_class=HTMLResponse)
async def runs_list(request: Request) -> HTMLResponse:
    runs = list_runs()
    return templates.TemplateResponse(
        "runs.html",
        {"request": request, "runs": runs},
    )


@router.get("/ui/runs/{run_id}", response_class=HTMLResponse)
async def run_detail(request: Request, run_id: str) -> HTMLResponse:
    try:
        run = get_run_artifacts(run_id)
        events = get_events(run_id, tail=200)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return templates.TemplateResponse(
        "run_detail.html",
        {
            "request": request,
            "run": run,
            "events": events,
            "max_preview_kb": MAX_PREVIEW_BYTES // 1024,
        },
    )


@router.get("/ui/runs/{run_id}/events", response_class=HTMLResponse)
async def run_events_partial(request: Request, run_id: str, tail: int = 200) -> HTMLResponse:
    try:
        events = get_events(run_id, tail=tail)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return templates.TemplateResponse(
        "partials/events.html",
        {"request": request, "events": events},
    )


@router.post("/api/runs")
async def create_run(request: Request) -> Any:
    payload: Dict[str, Any]
    if request.headers.get("content-type", "").startswith("application/json"):
        payload = await request.json()
    else:
        form = await request.form()
        payload = {
            "goal": form.get("goal"),
            "user_prompt": form.get("user_prompt"),
            "repo_root": form.get("repo_root"),
            "pipeline_id": form.get("pipeline_id"),
            "constraints": [
                item.strip()
                for item in str(form.get("constraints", "")).split("\n")
                if item.strip()
            ],
        }
    try:
        run_id = create_stub_run(payload)
    except ValueError as exc:
        accepts_html = "text/html" in request.headers.get("accept", "")
        if accepts_html or not request.headers.get("content-type", "").startswith(
            "application/json"
        ):
            context = _dashboard_context(
                pipeline_id=str(payload.get("pipeline_id") or ""),
                error=str(exc),
            )
            context["request"] = request
            return templates.TemplateResponse("dashboard.html", context, status_code=400)
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    accepts_html = "text/html" in request.headers.get("accept", "")
    if accepts_html or not request.headers.get("content-type", "").startswith(
        "application/json"
    ):
        return RedirectResponse(url=f"/ui/runs/{run_id}", status_code=303)
    return {"run_id": run_id}


@router.get("/api/runs")
async def api_runs() -> Dict[str, Any]:
    return {"runs": list_runs()}


@router.get("/api/runs/{run_id}")
async def api_run_detail(run_id: str) -> Dict[str, Any]:
    try:
        return get_run_artifacts(run_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.get("/api/runs/{run_id}/events")
async def api_run_events(run_id: str, tail: int = 200) -> Dict[str, Any]:
    try:
        return get_events(run_id, tail=tail)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.get("/api/runs/{run_id}/artifact")
async def api_run_artifact(run_id: str, name: str) -> Any:
    try:
        path = get_artifact_path(run_id, name)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    if not path.exists():
        raise HTTPException(status_code=404, detail="Artifact not found")
    return {
        "run_id": run_id,
        "name": name,
        "content": path.read_text(encoding="utf-8", errors="replace"),
    }



@router.post("/api/models")
async def api_create_model(request: Request) -> Dict[str, Any]:
    payload = await request.json()
    try:
        return create_model(payload)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/api/models")
async def api_list_models() -> Dict[str, Any]:
    return {"models": list_models()}


@router.get("/api/models/{model_id}")
async def api_get_model(model_id: str) -> Dict[str, Any]:
    try:
        return get_model(model_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc

@router.get("/api/pipelines")
async def api_pipelines() -> Dict[str, Any]:
    return {"pipelines": list_api_pipelines()}


@router.post("/api/pipelines")
async def api_create_pipeline(request: Request) -> Dict[str, Any]:
    payload = await request.json()
    try:
        pipeline = save_pipeline(payload)
    except PipelineValidationError as exc:
        raise HTTPException(
            status_code=400, detail={"message": str(exc), "errors": exc.errors}
        ) from exc
    return pipeline


@router.get("/api/pipelines/{pipeline_id}")
async def api_get_pipeline(pipeline_id: str) -> Dict[str, Any]:
    try:
        return get_api_pipeline(pipeline_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc



@router.put("/api/models/{model_id}")
async def api_update_model(model_id: str, request: Request) -> Dict[str, Any]:
    payload = await request.json()
    try:
        return update_model(model_id, payload)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.delete("/api/models/{model_id}")
async def api_delete_model(model_id: str) -> Dict[str, Any]:
    try:
        delete_model(model_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return {"deleted": model_id}
@router.put("/api/pipelines/{pipeline_id}")
async def api_put_pipeline(pipeline_id: str, request: Request) -> Dict[str, Any]:
    payload = await request.json()
    if payload.get("id") and payload["id"] != pipeline_id:
        raise HTTPException(status_code=400, detail="Pipeline id mismatch")
    payload["id"] = pipeline_id
    try:
        pipeline = save_pipeline(payload)
    except PipelineValidationError as exc:
        raise HTTPException(
            status_code=400, detail={"message": str(exc), "errors": exc.errors}
        ) from exc
    return pipeline


@router.delete("/api/pipelines/{pipeline_id}")
async def api_delete_pipeline(pipeline_id: str) -> Dict[str, Any]:
    deleted = delete_pipeline(pipeline_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Pipeline not found")
    return {"deleted": True}


@router.get("/api/discovery/vllm_models")
async def api_discovery_vllm_models(base_url: str | None = None) -> Dict[str, Any]:
    if not base_url:
        raise HTTPException(status_code=400, detail="base_url is required")
    try:
        normalized = _normalize_vllm_base_url(base_url)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    try:
        model_ids = _get_cached_vllm_models(normalized)
    except (urllib.error.URLError, urllib.error.HTTPError, json.JSONDecodeError, ValueError) as exc:
        raise HTTPException(status_code=502, detail="vLLM discovery failed") from exc
    return {"models": model_ids}
