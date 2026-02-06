import json

from fastapi.testclient import TestClient

from app.main import create_app


def _write_json(path, payload):
    path.write_text(json.dumps(payload), encoding="utf-8")


def _seed_models(models_dir):
    _write_json(
        models_dir / "validator.json",
        {
            "id": "validator",
            "role": "validator",
            "provider": "openai-compatible",
            "model_name": "gpt-4o-mini",
            "base_url": "https://example.com/v1",
            "prompt_profile": "You are a validator.",
        },
    )
    _write_json(
        models_dir / "planner.json",
        {
            "id": "planner",
            "role": "planner",
            "provider": "openai-compatible",
            "model_name": "gpt-4o-mini",
            "base_url": "https://example.com/v1",
            "prompt_profile": "You are a planner.",
        },
    )


def test_run_requires_pipeline_id(tmp_path, monkeypatch):
    monkeypatch.setenv("RUNS_DIR", str(tmp_path / "runs"))
    monkeypatch.setenv("MODELS_DIR", str(tmp_path / "models"))
    monkeypatch.setenv("PIPELINES_DIR", str(tmp_path / "pipelines"))

    app = create_app()
    client = TestClient(app)

    response = client.post(
        "/api/runs",
        json={
            "goal": "Missing pipeline",
            "user_prompt": "Test",
            "repo_root": "/workspace/oracl",
            "constraints": [],
        },
    )
    assert response.status_code == 400


def test_run_rejects_unknown_pipeline(tmp_path, monkeypatch):
    runs_dir = tmp_path / "runs"
    models_dir = tmp_path / "models"
    pipelines_dir = tmp_path / "pipelines"
    runs_dir.mkdir(parents=True, exist_ok=True)
    models_dir.mkdir(parents=True, exist_ok=True)
    pipelines_dir.mkdir(parents=True, exist_ok=True)

    monkeypatch.setenv("RUNS_DIR", str(runs_dir))
    monkeypatch.setenv("MODELS_DIR", str(models_dir))
    monkeypatch.setenv("PIPELINES_DIR", str(pipelines_dir))

    _seed_models(models_dir)

    app = create_app()
    client = TestClient(app)

    response = client.post(
        "/api/runs",
        json={
            "goal": "Unknown pipeline",
            "user_prompt": "Test",
            "repo_root": "/workspace/oracl",
            "constraints": [],
            "pipeline_id": "missing",
        },
    )
    assert response.status_code == 400


def test_run_writes_pipeline_snapshots(tmp_path, monkeypatch):
    runs_dir = tmp_path / "runs"
    models_dir = tmp_path / "models"
    pipelines_dir = tmp_path / "pipelines"
    runs_dir.mkdir(parents=True, exist_ok=True)
    models_dir.mkdir(parents=True, exist_ok=True)
    pipelines_dir.mkdir(parents=True, exist_ok=True)

    monkeypatch.setenv("RUNS_DIR", str(runs_dir))
    monkeypatch.setenv("MODELS_DIR", str(models_dir))
    monkeypatch.setenv("PIPELINES_DIR", str(pipelines_dir))

    _seed_models(models_dir)
    _write_json(
        pipelines_dir / "pipeline.json",
        {
            "id": "pipeline",
            "steps": [
                {"step": "validator_pre_planner", "role": "validator", "model_id": "validator"},
                {"step": "planner", "role": "planner", "model_id": "planner"},
            ],
        },
    )

    app = create_app()
    client = TestClient(app)

    response = client.post(
        "/api/runs",
        json={
            "goal": "Pipeline snapshot",
            "user_prompt": "Test",
            "repo_root": "/workspace/oracl",
            "constraints": [],
            "pipeline_id": "pipeline",
        },
    )
    assert response.status_code == 200
    run_id = response.json()["run_id"]

    pipeline_snapshot = json.loads((runs_dir / run_id / "pipeline_snapshot.json").read_text())
    model_snapshots = json.loads((runs_dir / run_id / "model_snapshots.json").read_text())

    assert pipeline_snapshot["id"] == "pipeline"
    assert len(model_snapshots["steps"]) == 2
    assert model_snapshots["steps"][0]["model_snapshot"]["id"] == "validator"


def test_run_rejects_role_mismatch(tmp_path, monkeypatch):
    runs_dir = tmp_path / "runs"
    models_dir = tmp_path / "models"
    pipelines_dir = tmp_path / "pipelines"
    runs_dir.mkdir(parents=True, exist_ok=True)
    models_dir.mkdir(parents=True, exist_ok=True)
    pipelines_dir.mkdir(parents=True, exist_ok=True)

    monkeypatch.setenv("RUNS_DIR", str(runs_dir))
    monkeypatch.setenv("MODELS_DIR", str(models_dir))
    monkeypatch.setenv("PIPELINES_DIR", str(pipelines_dir))

    _seed_models(models_dir)
    _write_json(
        pipelines_dir / "pipeline.json",
        {
            "id": "pipeline",
            "steps": [
                {"step": "validator_pre_planner", "role": "planner", "model_id": "validator"},
            ],
        },
    )

    app = create_app()
    client = TestClient(app)

    response = client.post(
        "/api/runs",
        json={
            "goal": "Role mismatch",
            "user_prompt": "Test",
            "repo_root": "/workspace/oracl",
            "constraints": [],
            "pipeline_id": "pipeline",
        },
    )
    assert response.status_code == 400
