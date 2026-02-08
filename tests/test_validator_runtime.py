from datetime import datetime
from pathlib import Path

import pytest

pytest.importorskip("pydantic")

from app.validator.runtime import validate_with_runtime
from app.validator.schema import FinalValidatorLabel, RequestRecord


def _tmp_s_payload() -> str:
    return "\n".join(
        [
            "V|2.2|run-1|validator|1",
            "A|1111|1111|accept|All good.",
            "B|p1:validator|Proceed.",
            "B|p2:validator|Log result.",
            "B|p3:validator|Continue pipeline.",
            "C|accept|0|0|next_node",
        ]
    )


def _tmp_s_payload_with_error() -> str:
    return "\n".join(
        [
            "V|2.2|run-1|validator|1",
            "A|1111|1111|retry|Extraneous fields detected.",
            "E|$.run_config|warning|Remove extraneous field.",
            "B|p1:validator|Remove run_config.",
            "B|p2:validator|Retry with allowed fields.",
            "B|p3:validator|Keep schema valid.",
            "C|retry|1|1|*",
        ]
    )


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


def test_llm_validator_accepts_valid_tmp_s(monkeypatch, tmp_path: Path):
    def fake_chat_completions(*, base_url, payload, timeout_s=30):
        return {"choices": [{"message": {"content": _tmp_s_payload()}}]}

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


def test_llm_validator_retries_invalid_tmp_s(monkeypatch, tmp_path: Path):
    responses = iter(
        [
            {"choices": [{"message": {"content": "not-tmp-s"}}]},
            {"choices": [{"message": {"content": _tmp_s_payload()}}]},
        ]
    )

    def fake_chat_completions(*, base_url, payload, timeout_s=30):
        return next(responses)

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


def test_llm_validator_records_tmp_s_errors(monkeypatch, tmp_path: Path):
    def fake_chat_completions(*, base_url, payload, timeout_s=30):
        return {"choices": [{"message": {"content": _tmp_s_payload_with_error()}}]}

    monkeypatch.setattr("app.validator.runtime.chat_completions", fake_chat_completions)

    model = {
        "provider": "openai-compatible",
        "base_url": "https://example.com",
        "model_name": "validator-model",
        "validator_config": {"use_llm": True, "max_attempts": 1},
    }

    label = validate_with_runtime(_request_record(), model=model, attempts_dir=tmp_path)

    assert label.control.decision == "retry_same_node"
    assert label.error_localization
