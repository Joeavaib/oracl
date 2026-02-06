import pytest

from app.pipelines import (
    PipelineValidationError,
    delete_pipeline,
    get_pipeline,
    list_pipelines,
    save_pipeline,
)


def sample_pipeline() -> dict:
    return {
        "id": "pipeline-1",
        "name": "Test pipeline",
        "description": "A pipeline for testing.",
        "steps": [
            {
                "order": 1,
                "role": "planner",
                "model_id": "gpt-4o-mini",
                "params": {"temperature": 0.1},
            },
            {
                "order": 2,
                "role": "coder",
                "model_id": "gpt-4o-mini",
                "params": {},
            },
        ],
    }


def test_pipeline_registry_crud(tmp_path, monkeypatch):
    monkeypatch.setenv("PIPELINES_DIR", str(tmp_path))
    payload = sample_pipeline()

    saved = save_pipeline(payload)
    assert (tmp_path / "pipeline-1.json").exists()

    fetched = get_pipeline("pipeline-1")
    assert fetched == saved

    listed = list_pipelines()
    assert listed == [saved]

    assert delete_pipeline("pipeline-1") is True
    assert list_pipelines() == []
    assert delete_pipeline("pipeline-1") is False


def test_pipeline_validation_error(tmp_path, monkeypatch):
    monkeypatch.setenv("PIPELINES_DIR", str(tmp_path))
    with pytest.raises(PipelineValidationError):
        save_pipeline({"id": "invalid"})
