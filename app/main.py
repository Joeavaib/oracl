from __future__ import annotations

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from app.ui import router as ui_router


def create_app() -> FastAPI:
    app = FastAPI(title="Orchestrator UI")
    app.include_router(ui_router)
    app.mount("/static", StaticFiles(directory="app/static"), name="static")
    return app


app = create_app()
