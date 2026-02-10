from __future__ import annotations

import json
import logging
import os
from pathlib import Path
from datetime import datetime, timezone
import urllib.error
import urllib.parse
import urllib.request
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, HTTPException, Request
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
    find_pipelines_using_model,
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
from app.inventory import list_local_gguf_models
from app.runs import (
    MAX_PREVIEW_BYTES,
    create_stub_run,
    execute_run_auto,
    get_artifact_path,
    get_events,
    get_run_artifacts,
    get_stage_decision,
    get_stage_output,
    get_stage_prompt,
    get_token_usage,
    list_runs,
    runs_dir,
)
from app.runtime_llamacpp import healthcheck as healthcheck_llamacpp
from app.runtime_llamacpp import list_instances as list_llamacpp_instances
from app.runtime_llamacpp import start_instance as start_llamacpp_instance
from app.runtime_llamacpp import stop_instance as stop_llamacpp_instance
from app.runtime_ollama import healthcheck as healthcheck_ollama
from app.runtime_ollama import list_models as list_ollama_models
from protocols.tmp_s_v22 import parse_tmp_s


router = APIRouter()

templates = Jinja2Templates(directory="app/templates")
templates.env.globals["debug"] = os.getenv("DEBUG") == "1"

logger = logging.getLogger(__name__)

_OPENAI_DISCOVERY_CACHE: Dict[str, Dict[str, Any]] = {}
_OPENAI_DISCOVERY_TTL_S = 30


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
    steps = [dict(step) for step in pipeline.get("steps", [])]
    models = list_models()
    models_index = {
        "all": [
            {
                "id": model.get("id"),
                "role": model.get("role"),
                "provider": model.get("provider"),
                "model_name": model.get("model_name"),
            }
            for model in models
            if model.get("id")
        ],
        "by_role": {role: [] for role in MODEL_ROLES},
    }
    for model in models_index["all"]:
        role = model.get("role")
        if role in models_index["by_role"]:
            models_index["by_role"][role].append(model)

    model_ids = {str(model.get("id")) for model in models_index["all"] if model.get("id")}
    models_by_name: Dict[str, List[Dict[str, Any]]] = {}
    for model in models_index["all"]:
        model_name = str(model.get("model_name") or "").strip()
        if not model_name:
            continue
        models_by_name.setdefault(model_name, []).append(model)

    for step in steps:
        stored_model_id = str(step.get("model_id") or "").strip()
        if not stored_model_id or stored_model_id in model_ids:
            continue
        matches = models_by_name.get(stored_model_id, [])
        if len(matches) == 1:
            step["model_id"] = matches[0].get("id")
            step["model_id_resolved_from"] = stored_model_id
        elif len(matches) > 1:
            step["model_id_suggestions"] = [
                str(match.get("id")) for match in matches if match.get("id")
            ]

    steps.append({"step": "", "role": "", "model_id": ""})
    return {
        "pipeline": pipeline,
        "steps": steps,
        "is_new": is_new,
        "error": error,
        "models_index": models_index,
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
        "ollama_base_url": os.getenv("OLLAMA_BASE_URL", "http://127.0.0.1:11434"),
    }


def _load_text(path: Path) -> Optional[str]:
    if not path.exists():
        return None
    return path.read_text(encoding="utf-8")


def _load_json(path: Path) -> Optional[Dict[str, Any]]:
    if not path.exists():
        return None
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def _badge_decision(value: str) -> str:
    normalized = (value or "").lower()
    if normalized in {"a", "accept"}:
        return "A"
    if normalized in {"r", "retry", "retry_same_node"}:
        return "R"
    if normalized in {"x", "reroute"}:
        return "X"
    if normalized in {"e", "escalate", "abort"}:
        return "E"
    return "R"


def _badge_verdict(value: str) -> str:
    if not value:
        return "?"
    return value.strip().upper()[:1]


def _badge_severity(value: str) -> str:
    normalized = (value or "").lower()
    if normalized in {"critical", "c"}:
        return "C"
    if normalized in {"high", "h"}:
        return "H"
    if normalized in {"medium", "m"}:
        return "M"
    return "L"


def _build_tmp_s_views(run_id: str) -> List[Dict[str, Any]]:
    run_path = runs_dir() / run_id
    stages = [
        ("validator_pre_planner", "Validator Pre-Planner"),
        ("validator_post_planner", "Validator Post-Planner"),
    ]
    views: List[Dict[str, Any]] = []
    for stage_id, label in stages:
        tmp_s_path = run_path / f"{stage_id}.tmp_s.txt"
        raw_text = _load_text(tmp_s_path)
        parsed_path = run_path / f"{stage_id}.parsed.json"
        parsed_payload = _load_json(parsed_path)
        control_payload = _load_json(run_path / f"{stage_id}.json") or {}
        briefing = _load_json(run_path / f"{stage_id}_step_03_compress.json") or {}
        current_scope = briefing.get("current_scope") or []
        audit = {}
        errors = []
        control = {}
        if raw_text:
            parsed = parse_tmp_s(raw_text)
            audit = {
                "hard4": parsed.audit.hard4,
                "soft4": parsed.audit.soft4,
                "verdict": parsed.audit.verdict,
                "rationale": parsed.audit.rationale,
            }
            errors = [
                {
                    "path": err.path,
                    "severity": err.severity,
                    "severity_badge": _badge_severity(err.severity),
                    "fix_hint": err.fix_hint,
                }
                for err in parsed.errors
            ]
            control = {
                "decision": parsed.control.decision,
                "decision_badge": _badge_decision(parsed.control.decision),
                "strategy": parsed.control.strategy,
                "max_retries": parsed.control.max_retries,
                "focus": parsed.control.focus,
            }
        views.append(
            {
                "stage_id": stage_id,
                "label": label,
                "raw_text": raw_text,
                "parsed_payload": parsed_payload,
                "legacy_payload": parsed_payload,
                "control_payload": control_payload,
                "audit": audit,
                "errors": errors,
                "control": control,
                "verdict_badge": _badge_verdict(audit.get("verdict", "")),
                "decision_badge": control.get("decision_badge", ""),
                "current_scope": current_scope,
            }
        )
    return views


def _parse_list_field(value: Optional[str]) -> List[str]:
    if value is None:
        return []
    return [item.strip() for item in str(value).splitlines() if item.strip()]


def _safe_run_dir(run_id: str) -> Path:
    base = runs_dir().resolve()
    candidate = (runs_dir() / run_id).resolve()
    if base not in candidate.parents:
        raise HTTPException(status_code=404, detail="Run not found")
    return candidate


def _write_run_state(run_id: str, filename: str, payload: Dict[str, Any]) -> None:
    run_path = _safe_run_dir(run_id)
    path = run_path / filename
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


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


def _normalize_openai_base_url(base_url: str) -> str:
    if not isinstance(base_url, str) or not base_url.strip():
        raise ValueError("base_url is required")
    parsed = urllib.parse.urlparse(base_url.strip())
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise ValueError("base_url must include scheme and host")
    path = parsed.path.rstrip("/")
    if path not in ("", "/v1"):
        raise ValueError("base_url must end with /v1 or omit path")
    return urllib.parse.urlunparse((parsed.scheme, parsed.netloc, "", "", "", ""))


def _fetch_openai_models(base_url: str) -> List[str]:
    url = f"{base_url}/v1/models"
    request = urllib.request.Request(url, method="GET")
    with urllib.request.urlopen(request, timeout=10) as response:
        payload = json.loads(response.read().decode("utf-8"))
    data = payload.get("data")
    if not isinstance(data, list):
        raise ValueError("Invalid discovery response")
    return [
        item["id"]
        for item in data
        if isinstance(item, dict) and isinstance(item.get("id"), str)
    ]


def _normalize_ollama_base_url(base_url: str) -> str:
    if not isinstance(base_url, str) or not base_url.strip():
        raise ValueError("base_url is required")
    parsed = urllib.parse.urlparse(base_url.strip())
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise ValueError("base_url must include scheme and host")
    return urllib.parse.urlunparse((parsed.scheme, parsed.netloc, parsed.path.rstrip("/"), "", "", ""))


def _get_cached_openai_models(base_url: str) -> List[str]:
    now = datetime.now(timezone.utc).timestamp()
    cached = _OPENAI_DISCOVERY_CACHE.get(base_url)
    if cached and (now - cached["timestamp"] <= _OPENAI_DISCOVERY_TTL_S):
        return cached["models"]
    models = _fetch_openai_models(base_url)
    _OPENAI_DISCOVERY_CACHE[base_url] = {
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
        {"request": request, "models": models, "error": None},
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
        "model_path": form.get("model_path"),
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
        "model_path": form.get("model_path"),
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


@router.get("/ui/models/discover/openai_models", response_class=HTMLResponse)
async def ui_discover_openai_models(base_url: str | None = None) -> HTMLResponse:
    if not base_url:
        raise HTTPException(status_code=400, detail="base_url is required")
    try:
        normalized = _normalize_openai_base_url(base_url)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    try:
        model_ids = _get_cached_openai_models(normalized)
    except (urllib.error.URLError, urllib.error.HTTPError, json.JSONDecodeError, ValueError) as exc:
        raise HTTPException(status_code=502, detail="Discovery failed") from exc
    options = "\n".join(
        f"<option value=\"{model_id}\"></option>" for model_id in model_ids
    )
    html = f"<datalist id=\"openai-models\">{options}</datalist>"
    return HTMLResponse(content=html)


@router.get("/ui/models/discover/openai_test", response_class=HTMLResponse)
async def ui_discover_openai_test(base_url: str | None = None) -> HTMLResponse:
    if not base_url:
        raise HTTPException(status_code=400, detail="base_url is required")
    try:
        normalized = _normalize_openai_base_url(base_url)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    try:
        _fetch_openai_models(normalized)
    except (urllib.error.URLError, urllib.error.HTTPError, json.JSONDecodeError, ValueError):
        return HTMLResponse(content="<p class=\"warning\">FAIL</p>")
    return HTMLResponse(content="<p class=\"hint\">OK</p>")


@router.get("/ui/models/discover/ollama_models", response_class=HTMLResponse)
async def ui_discover_ollama_models(base_url: str | None = None) -> HTMLResponse:
    if not base_url:
        logger.warning("Ollama discovery missing base_url")
        return HTMLResponse(content="<p class=\"warning\">Ollama base_url fehlt.</p>")
    try:
        normalized = _normalize_ollama_base_url(base_url)
        model_ids = list_ollama_models(normalized)
    except (urllib.error.URLError, urllib.error.HTTPError, json.JSONDecodeError, ValueError) as exc:
        logger.exception("Ollama discovery failed for base_url=%s", base_url)
        return HTMLResponse(
            content=f"<p class=\"warning\">Ollama nicht erreichbar: {exc}</p>"
        )
    options = "\n".join(f"<option value=\"{model_id}\"></option>" for model_id in model_ids)
    html = f"<datalist id=\"ollama-models\">{options}</datalist>"
    return HTMLResponse(content=html)


@router.get("/ui/models/discover/ollama_test", response_class=HTMLResponse)
async def ui_discover_ollama_test(base_url: str | None = None) -> HTMLResponse:
    if not base_url:
        raise HTTPException(status_code=400, detail="base_url is required")
    try:
        normalized = _normalize_ollama_base_url(base_url)
        result = healthcheck_ollama(normalized)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    ok = bool(result.get("ok"))
    detail = result.get("error")
    if ok:
        return HTMLResponse(content="<p class=\"hint\">OK</p>")
    suffix = f": {detail}" if detail else ""
    return HTMLResponse(content=f"<p class=\"warning\">FAIL{suffix}</p>")


@router.get("/ui/models/discover/vllm", response_class=HTMLResponse)
async def ui_discover_vllm_models(base_url: str | None = None) -> HTMLResponse:
    return await ui_discover_openai_models(base_url=base_url)


@router.get("/ui/models/discover/vllm_test", response_class=HTMLResponse)
async def ui_discover_vllm_test(base_url: str | None = None) -> HTMLResponse:
    return await ui_discover_openai_test(base_url=base_url)


@router.get("/ui/models/discover/local_gguf", response_class=HTMLResponse)
async def ui_discover_local_gguf_models() -> HTMLResponse:
    suggestions = list_local_gguf_models()
    options = "\n".join(
        f"<option value=\"{entry['model_path']}\">{entry['display_name']}</option>"
        for entry in suggestions
    )
    html = f"<datalist id=\"local-gguf-models\">{options}</datalist>"
    return HTMLResponse(content=html)


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
        tmp_s_views = _build_tmp_s_views(run_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return templates.TemplateResponse(
        "run_detail.html",
        {
            "request": request,
            "run": run,
            "events": events,
            "tmp_s_views": tmp_s_views,
            "max_preview_kb": MAX_PREVIEW_BYTES // 1024,
        },
    )


@router.get("/ui/runs/{run_id}/events", response_class=HTMLResponse)
async def run_events_partial(request: Request, run_id: str, tail: int = 200) -> HTMLResponse:
    try:
        events = get_events(run_id, tail=tail)
    except ValueError as exc:
        return HTMLResponse(
            content=f"<div class=\"warning\">Events konnten nicht geladen werden: {exc}</div>",
            status_code=200,
        )
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


@router.post("/api/runs/{run_id}/start")
async def api_run_start(run_id: str) -> Dict[str, Any]:
    try:
        execute_run_auto(run_id)
        return get_run_artifacts(run_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.post("/api/runs/{run_id}/pause")
async def api_run_pause(run_id: str) -> Dict[str, Any]:
    _safe_run_dir(run_id)
    _write_run_state(
        run_id,
        "state_paused.json",
        {
            "run_id": run_id,
            "paused_at": datetime.now(timezone.utc).isoformat(),
            "status": "PAUSED",
        },
    )
    return get_run_artifacts(run_id)


@router.post("/api/runs/{run_id}/resume")
async def api_run_resume(run_id: str) -> Dict[str, Any]:
    run_path = _safe_run_dir(run_id)
    paused_path = run_path / "state_paused.json"
    if paused_path.exists():
        paused_path.unlink()
    _write_run_state(
        run_id,
        "state_running.json",
        {
            "run_id": run_id,
            "resumed_at": datetime.now(timezone.utc).isoformat(),
            "status": "RUNNING",
        },
    )
    return get_run_artifacts(run_id)


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


@router.get("/api/runs/{run_id}/stages/{stage_index}/prompt")
async def api_run_stage_prompt(run_id: str, stage_index: int) -> Dict[str, Any]:
    try:
        return get_stage_prompt(run_id, stage_index)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.get("/api/runs/{run_id}/stages/{stage_index}/output")
async def api_run_stage_output(run_id: str, stage_index: int) -> Dict[str, Any]:
    try:
        return get_stage_output(run_id, stage_index)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.get("/api/runs/{run_id}/stages/{stage_index}/decision")
async def api_run_stage_decision(run_id: str, stage_index: int) -> Dict[str, Any]:
    try:
        return get_stage_decision(run_id, stage_index)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.get("/api/runs/{run_id}/token-usage")
async def api_run_token_usage(run_id: str) -> Dict[str, Any]:
    try:
        return get_token_usage(run_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc

@router.post("/api/models")
async def api_create_model(request: Request) -> Dict[str, Any]:
    payload = await request.json()
    try:
        return create_model(payload)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/api/models")
async def api_list_models(role: Optional[str] = None) -> List[Dict[str, Any]]:
    if role is not None and role not in MODEL_ROLES:
        raise HTTPException(status_code=400, detail="Invalid role")
    models = list_models()
    if role is not None:
        models = [model for model in models if model.get("role") == role]
    return [
        {
            "id": model.get("id"),
            "role": model.get("role"),
            "provider": model.get("provider"),
            "base_url": model.get("base_url"),
            "model_name": model.get("model_name"),
        }
        for model in models
    ]


@router.get("/api/models/index")
async def api_models_index() -> Dict[str, Any]:
    models = list_models()
    by_role: Dict[str, List[Dict[str, Any]]] = {role: [] for role in MODEL_ROLES}
    for model in models:
        role = model.get("role")
        if role in by_role:
            by_role[role].append(
                {
                    "id": model.get("id"),
                    "role": model.get("role"),
                    "provider": model.get("provider"),
                    "base_url": model.get("base_url"),
                    "model_name": model.get("model_name"),
                }
            )
    return {"by_role": by_role}


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
    pipelines = find_pipelines_using_model(model_id)
    if pipelines:
        detail = f"Model is used by pipelines: {', '.join(pipelines)}"
        raise HTTPException(status_code=400, detail=detail)
    try:
        delete_model(model_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return {"ok": True}


@router.post("/ui/models/{model_id}/delete")
async def ui_delete_model(request: Request, model_id: str) -> HTMLResponse:
    pipelines = find_pipelines_using_model(model_id)
    if pipelines:
        models = list_models()
        detail = f"Model wird in Pipelines verwendet: {', '.join(pipelines)}"
        return templates.TemplateResponse(
            "models.html",
            {"request": request, "models": models, "error": detail},
            status_code=400,
        )
    try:
        delete_model(model_id)
    except ValueError as exc:
        models = list_models()
        return templates.TemplateResponse(
            "models.html",
            {"request": request, "models": models, "error": str(exc)},
            status_code=404,
        )
    return RedirectResponse(url="/ui/models", status_code=303)


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


@router.get("/api/discovery/openai_models")
async def api_discovery_openai_models(base_url: str | None = None) -> Dict[str, Any]:
    if not base_url:
        raise HTTPException(status_code=400, detail="base_url is required")
    try:
        normalized = _normalize_openai_base_url(base_url)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    try:
        model_ids = _get_cached_openai_models(normalized)
    except (urllib.error.URLError, urllib.error.HTTPError, json.JSONDecodeError, ValueError) as exc:
        raise HTTPException(status_code=502, detail="Discovery failed") from exc
    return {"models": model_ids}


@router.get("/api/discovery/vllm_models")
async def api_discovery_vllm_models(base_url: str | None = None) -> Dict[str, Any]:
    return await api_discovery_openai_models(base_url=base_url)


@router.get("/api/discovery/ollama_models")
async def api_discovery_ollama_models(base_url: str | None = None) -> Dict[str, Any]:
    if not base_url:
        raise HTTPException(status_code=400, detail="base_url is required")
    try:
        normalized = _normalize_ollama_base_url(base_url)
        model_ids = list_ollama_models(normalized)
    except (urllib.error.URLError, urllib.error.HTTPError, json.JSONDecodeError, ValueError) as exc:
        raise HTTPException(status_code=502, detail="Discovery failed") from exc
    return {"models": model_ids}


@router.get("/api/discovery/ollama_test")
async def api_discovery_ollama_test(base_url: str | None = None) -> Dict[str, Any]:
    if not base_url:
        raise HTTPException(status_code=400, detail="base_url is required")
    try:
        normalized = _normalize_ollama_base_url(base_url)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    result = healthcheck_ollama(normalized)
    if not result.get("ok"):
        raise HTTPException(status_code=502, detail=result.get("error") or "Healthcheck failed")
    return {"ok": True, "mode": result.get("mode")}


@router.get("/api/discovery/local_gguf")
async def api_discovery_local_gguf() -> Dict[str, Any]:
    return {"models": list_local_gguf_models()}


@router.post("/api/runtimes/llamacpp/start")
async def api_llamacpp_start(request: Request) -> Dict[str, Any]:
    payload = await request.json()
    role = payload.get("role")
    model_path = payload.get("model_path")
    port = payload.get("port")
    binary_path = payload.get("binary_path")
    ctx_size = payload.get("ctx_size")
    threads = payload.get("threads")
    extra_args: List[str] = []
    if ctx_size is not None:
        extra_args.extend(["--ctx-size", str(ctx_size)])
    if threads is not None:
        extra_args.extend(["--threads", str(threads)])
    try:
        return start_llamacpp_instance(
            role=role,
            model_path=model_path,
            port=port,
            extra_args=extra_args or None,
            binary_path=binary_path,
        )
    except (ValueError, RuntimeError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/api/runtimes/llamacpp/stop")
async def api_llamacpp_stop(request: Request) -> Dict[str, Any]:
    payload = await request.json()
    instance_id = payload.get("instance_id")
    try:
        stopped = stop_llamacpp_instance(instance_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if not stopped:
        raise HTTPException(status_code=404, detail="Instance not found")
    return {"stopped": True}


@router.get("/api/runtimes/llamacpp/list")
async def api_llamacpp_list() -> Dict[str, Any]:
    return {"instances": list_llamacpp_instances()}


@router.get("/api/runtimes/llamacpp/health")
async def api_llamacpp_health(base_url: str | None = None) -> Dict[str, Any]:
    if not base_url:
        raise HTTPException(status_code=400, detail="base_url is required")
    return healthcheck_llamacpp(base_url)
