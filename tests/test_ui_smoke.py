import json
import pytest

pytest.importorskip("fastapi")

from fastapi.testclient import TestClient

from app.main import create_app


def test_ui_run_smoke(tmp_path, monkeypatch):
    runs_dir = tmp_path / "runs"
    models_dir = tmp_path / "models"
    pipelines_dir = tmp_path / "pipelines"
    monkeypatch.setenv("RUNS_DIR", str(runs_dir))
    monkeypatch.setenv("MODELS_DIR", str(models_dir))
    monkeypatch.setenv("PIPELINES_DIR", str(pipelines_dir))
    models_dir.mkdir(parents=True, exist_ok=True)
    pipelines_dir.mkdir(parents=True, exist_ok=True)

    (models_dir / "validator.json").write_text(
        json.dumps(
            {
                "id": "validator",
                "role": "validator",
                "provider": "openai-compatible",
                "model_name": "gpt-4o-mini",
                "base_url": "https://example.com/v1",
                "prompt_profile": "You are a validator.",
            }
        ),
        encoding="utf-8",
    )
    (models_dir / "planner.json").write_text(
        json.dumps(
            {
                "id": "planner",
                "role": "planner",
                "provider": "openai-compatible",
                "model_name": "gpt-4o-mini",
                "base_url": "https://example.com/v1",
                "prompt_profile": "You are a planner.",
            }
        ),
        encoding="utf-8",
    )
    (models_dir / "coder.json").write_text(
        json.dumps(
            {
                "id": "coder",
                "role": "coder",
                "provider": "openai-compatible",
                "model_name": "gpt-4o-mini",
                "base_url": "https://example.com/v1",
                "prompt_profile": "You are a coder.",
            }
        ),
        encoding="utf-8",
    )
    (pipelines_dir / "pipeline.json").write_text(
        json.dumps(
            {
                "id": "pipeline",
                "steps": [
                    {"step": "validator_pre_planner", "role": "validator", "model_id": "validator"},
                    {"step": "planner", "role": "planner", "model_id": "planner"},
                    {"step": "coder", "role": "coder", "model_id": "coder"},
                ],
            }
        ),
        encoding="utf-8",
    )
    app = create_app()
    client = TestClient(app)

    response = client.post(
        "/api/runs",
        json={
            "goal": "Smoke test",
            "user_prompt": "Check UI",
            "repo_root": "/workspace/oracl",
            "constraints": ["no refactors"],
            "pipeline_id": "pipeline",
        },
    )
    assert response.status_code == 200


def test_ui_smoke():
    app = create_app()
    client = TestClient(app)
    response = client.get("/ui")
    assert response.status_code == 200
    assert "/static/vendor/htmx.js" in response.text
    static_response = client.get("/static/vendor/htmx.js")
    assert static_response.status_code == 200
    assert "hx-get" in static_response.text


def test_ui_models_new_page():
    app = create_app()
    client = TestClient(app)
    response = client.get("/ui/models/new")
    assert response.status_code == 200
