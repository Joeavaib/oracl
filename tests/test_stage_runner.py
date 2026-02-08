import json

from app.event_store import (
    INFERENCE_COMPLETED,
    INFERENCE_STARTED,
    PROMPT_BUILT,
    RUN_COMPLETED,
    RUN_STARTED,
    STAGE_COMPLETED,
    STAGE_STARTED,
    list_events,
)
from app.runs import create_run, execute_run_auto
from app.stage_runner import run_stage


def _write_json(path, payload):
    path.write_text(json.dumps(payload), encoding="utf-8")


def test_run_stage_writes_events_and_artifacts(tmp_path, monkeypatch):
    monkeypatch.setenv("RUNS_DIR", str(tmp_path / "runs"))

    def fake_chat_completions(*, base_url, payload, timeout_s=30):
        payload_json = json.dumps({"summary": "ok", "plan_steps": [], "files_to_touch": []})
        content = "\n".join(
            [
                "V|2.2|run-1|planner|1",
                "A|1111|1111|accept|ok",
                "B|p1:planner|note",
                "B|p2:planner|note",
                "B|p3:planner|note",
                "C|accept|0|0|*",
                "S|planner|planner|planner|1",
                f"O|PLAN|*|{payload_json}",
            ]
        )
        return {"choices": [{"message": {"content": content}}]}

    monkeypatch.setattr("app.stage_runner.chat_completions", fake_chat_completions)

    output = run_stage(
        run_id="run-1",
        stage_type="planner",
        model_snapshot={
            "model_snapshot": {
                "base_url": "https://example.com",
                "model_name": "gpt-4o-mini",
            },
            "params": {"token_budget": 123},
        },
        input_payload={"orchestra_briefing": {"known_correct": []}},
    )

    assert output["summary"] == "ok"

    run_path = tmp_path / "runs" / "run-1"
    assert (run_path / "planner_output.json").exists()
    assert (run_path / "planner_inference.json").exists()

    events = list_events("run-1")
    types = [event["type"] for event in events]
    assert STAGE_STARTED in types
    assert PROMPT_BUILT in types
    assert INFERENCE_STARTED in types
    assert INFERENCE_COMPLETED in types
    assert STAGE_COMPLETED in types


def test_execute_run_auto_runs_planner_and_coder(tmp_path, monkeypatch):
    runs_dir = tmp_path / "runs"
    models_dir = tmp_path / "models"
    pipelines_dir = tmp_path / "pipelines"
    runs_dir.mkdir(parents=True, exist_ok=True)
    models_dir.mkdir(parents=True, exist_ok=True)
    pipelines_dir.mkdir(parents=True, exist_ok=True)

    monkeypatch.setenv("RUNS_DIR", str(runs_dir))
    monkeypatch.setenv("MODELS_DIR", str(models_dir))
    monkeypatch.setenv("PIPELINES_DIR", str(pipelines_dir))

    _write_json(
        models_dir / "planner.json",
        {
            "id": "planner",
            "role": "planner",
            "provider": "openai-compatible",
            "model_name": "gpt-4o-mini",
            "base_url": "https://example.com",
            "prompt_profile": "You are a planner.",
        },
    )
    _write_json(
        models_dir / "coder.json",
        {
            "id": "coder",
            "role": "coder",
            "provider": "openai-compatible",
            "model_name": "gpt-4o-mini",
            "base_url": "https://example.com",
            "prompt_profile": "You are a coder.",
        },
    )
    _write_json(
        pipelines_dir / "pipeline.json",
        {
            "id": "pipeline",
            "steps": [
                {"step": "planner", "role": "planner", "model_id": "planner"},
                {"step": "coder", "role": "coder", "model_id": "coder"},
            ],
        },
    )

    call_index = {"count": 0}

    def fake_chat_completions(*, base_url, payload, timeout_s=30):
        if call_index["count"] == 0:
            payload_json = json.dumps(
                {
                    "summary": "ok",
                    "plan_steps": [],
                    "files_to_touch": [],
                    "risks": [],
                    "needs_context": [],
                    "success_signals": [],
                }
            )
            content = "\n".join(
                [
                    "V|2.2|run-1|planner|1",
                    "A|1111|1111|accept|ok",
                    "B|p1:planner|note",
                    "B|p2:planner|note",
                    "B|p3:planner|note",
                    "C|accept|0|0|*",
                    "S|planner|planner|planner|1",
                    f"O|PLAN|*|{payload_json}",
                ]
            )
        else:
            payload_json = json.dumps(
                {
                    "patch_unified_diff": "",
                    "touched_files": [],
                    "rationale": [],
                    "verification": [],
                    "followups": [],
                }
            )
            content = "\n".join(
                [
                    "V|2.2|run-1|coder|1",
                    "A|1111|1111|accept|ok",
                    "B|p1:coder|note",
                    "B|p2:coder|note",
                    "B|p3:coder|note",
                    "C|accept|0|0|*",
                    "S|coder|coder|coder|1",
                    f"O|DIFF|*|{payload_json}",
                ]
            )
        call_index["count"] += 1
        return {"choices": [{"message": {"content": content}}]}

    monkeypatch.setattr("app.stage_runner.chat_completions", fake_chat_completions)

    run_id = create_run(
        {
            "goal": "Test",
            "user_prompt": "Test",
            "repo_root": "/workspace/oracl",
            "constraints": [],
            "pipeline_id": "pipeline",
        }
    )
    execute_run_auto(run_id)

    run_path = runs_dir / run_id
    assert (run_path / "planner_output.json").exists()
    assert (run_path / "coder_output.json").exists()

    events = list_events(run_id)
    types = [event["type"] for event in events]
    assert RUN_STARTED in types
    assert RUN_COMPLETED in types
