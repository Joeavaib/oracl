from datetime import datetime
from pathlib import Path

import pytest

pytest.importorskip("pydantic")

from app.validator.runtime import validate_with_runtime
from app.validator.schema import FinalValidatorLabel, RequestRecord


def _label_payload() -> dict:
    return {
        "version": "0.1",
        "hard_checks": {
            "json_parseable": True,
            "schema_valid": True,
            "required_fields_present": True,
            "no_extraneous_fields": True,
            "field_types_valid": True,
        },
        "soft_checks": {
            "correctness": 1.0,
            "constraint_adherence": 1.0,
            "completeness": 1.0,
            "clarity": 1.0,
            "overall": 1.0,
        },
        "error_localization": [],
        "minimal_rationale": "All good.",
        "orchestra_briefing": {
            "known_correct": ["ok"],
            "uncertain_or_needs_check": [],
            "missing_inputs": [],
            "next_actions": ["a", "b", "c"],
            "retry_prompt": "No retry required.",
        },
        "control": {
            "decision": "accept",
            "retry_strategy": None,
            "stop_conditions": [],
            "route_to": "next_node",
        },
    }


def _request_record() -> RequestRecord:
    return RequestRecord(
        request_id="req-llm",
        created_at=datetime(2024, 1, 1),
        prompt="Validate",
        response_text='{"ok": true}',
        required_fields=["ok"],
        allowed_fields=["ok"],
        field_types={"ok": "boolean"},
    )


def test_llm_validator_accepts_valid_json(monkeypatch, tmp_path: Path):
    payload = _label_payload()

    def fake_chat_completions(*, base_url, payload, timeout_s=30):
        return {"choices": [{"message": {"content": json.dumps(payload)}}]}

    import json

    monkeypatch.setattr("app.validator.runtime.chat_completions", fake_chat_completions)

    model = {
        "provider": "openai-compatible",
        "base_url": "https://example.com",
        "model_name": "validator-model",
        "validator_config": {"use_llm": True, "max_attempts": 2},
    }

    label = validate_with_runtime(_request_record(), model=model, attempts_dir=tmp_path)

    FinalValidatorLabel(**label.dict())
    assert (tmp_path / "validator_attempt_01.json").exists()


def test_llm_validator_retries_invalid_json(monkeypatch, tmp_path: Path):
    responses = iter(
        [
            {"choices": [{"message": {"content": "not-json"}}]},
            {"choices": [{"message": {"content": json.dumps(_label_payload())}}]},
        ]
    )

    def fake_chat_completions(*, base_url, payload, timeout_s=30):
        return next(responses)

    import json

    monkeypatch.setattr("app.validator.runtime.chat_completions", fake_chat_completions)

    model = {
        "provider": "openai-compatible",
        "base_url": "https://example.com",
        "model_name": "validator-model",
        "validator_config": {"use_llm": True, "max_attempts": 2},
    }

    label = validate_with_runtime(_request_record(), model=model, attempts_dir=tmp_path)

    assert label.control.decision == "accept"
    assert (tmp_path / "validator_attempt_01.json").exists()
    assert (tmp_path / "validator_attempt_02.json").exists()
