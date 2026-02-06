import pytest

pytest.importorskip("fastapi")

from fastapi.testclient import TestClient

from app.main import create_app
from app.models_registry import create_model, get_model, list_models


def test_model_registry_helpers(tmp_path, monkeypatch):
    monkeypatch.setenv("MODELS_DIR", str(tmp_path))

    payload = {
        "id": "specialist-1",
        "role": "validator",
        "provider": "openai-compatible",
        "model_name": "gpt-4o-mini",
        "base_url": "https://example.com/v1",
        "prompt_profile": "You are a careful validator.",
        "adapter": {"notes": "metadata only"},
        "validator_config": {
            "max_attempts": 2,
            "stop_conditions": ["max_retries_reached"],
            "allowed_decisions": ["accept", "retry_same_node"],
            "allowed_retry_strategies": ["force_schema"],
            "compression_token_budget": 512,
        },
    }
    create_model(payload)

    models = list_models()
    assert len(models) == 1
    assert models[0]["id"] == "specialist-1"

    fetched = get_model("specialist-1")
    assert fetched["role"] == "validator"


def test_model_registry_api_validation(tmp_path, monkeypatch):
    monkeypatch.setenv("MODELS_DIR", str(tmp_path))
    app = create_app()
    client = TestClient(app)

    response = client.post(
        "/api/models",
        json={
            "id": "bad-model",
            "role": "not-a-role",
            "provider": "openai-compatible",
            "model_name": "gpt-4o-mini",
            "base_url": "https://example.com/v1",
            "prompt_profile": "Nope",
        },
    )
    assert response.status_code == 400

    good = client.post(
        "/api/models",
        json={
            "id": "planner-1",
            "role": "planner",
            "provider": "vllm",
            "model_name": "model-x",
            "base_url": "http://localhost:8000",
            "prompt_profile": "You are a planner.",
        },
    )
    assert good.status_code == 200

    listed = client.get("/api/models")
    assert listed.status_code == 200
    assert listed.json()["models"][0]["id"] == "planner-1"

    fetched = client.get("/api/models/planner-1")
    assert fetched.status_code == 200
    assert fetched.json()["role"] == "planner"


def test_model_registry_rejects_invalid_validator_config(tmp_path, monkeypatch):
    monkeypatch.setenv("MODELS_DIR", str(tmp_path))

    with pytest.raises(ValueError):
        create_model(
            {
                "id": "bad-validator",
                "role": "validator",
                "provider": "openai-compatible",
                "model_name": "gpt-4o-mini",
                "base_url": "https://example.com/v1",
                "prompt_profile": "Bad config.",
                "validator_config": {"max_attempts": -1},
            }
        )
