from __future__ import annotations

from typing import Any, Dict, Optional

from fastapi import APIRouter, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates

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


@router.get("/ui", response_class=HTMLResponse)
async def dashboard(request: Request) -> HTMLResponse:
    return templates.TemplateResponse(
        "dashboard.html",
        {"request": request, "max_preview_kb": MAX_PREVIEW_BYTES // 1024},
    )


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
            "constraints": [
                item.strip()
                for item in str(form.get("constraints", "")).split("\n")
                if item.strip()
            ],
        }
    run_id = create_stub_run(payload)
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
