from fastapi.testclient import TestClient

from app.main import create_app


def test_ui_smoke(tmp_path, monkeypatch):
    monkeypatch.setenv("RUNS_DIR", str(tmp_path))
    app = create_app()
    client = TestClient(app)

    response = client.post(
        "/api/runs",
        json={
            "goal": "Smoke test",
            "user_prompt": "Check UI",
            "repo_root": "/workspace/oracl",
            "constraints": ["no refactors"],
        },
    )
    assert response.status_code == 200
    run_id = response.json()["run_id"]

    runs_response = client.get("/api/runs")
    assert runs_response.status_code == 200
    assert any(run["run_id"] == run_id for run in runs_response.json()["runs"])

    detail_response = client.get(f"/ui/runs/{run_id}")
    assert detail_response.status_code == 200
