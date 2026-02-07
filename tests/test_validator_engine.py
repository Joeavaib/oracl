from datetime import datetime

import pytest

pytest.importorskip("pydantic")

from app.validator.engine import compress_user_prompt_to_script, validate_request
from app.validator.schema import RequestRecord


def test_validate_request_retries_on_invalid_json():
    record = RequestRecord(
        request_id="req-3",
        created_at=datetime(2024, 1, 1),
        prompt="Return JSON",
        response_text="not-json",
        required_fields=["alpha"],
        allowed_fields=["alpha"],
        field_types={"alpha": "string"},
    )

    label = validate_request(record)

    assert label.hard_checks.json_parseable is False
    assert label.control.decision == "retry_same_node"
    assert label.error_localization[0].issue == "json_parse_error"
    assert "Return strict JSON" in label.orchestra_briefing.retry_prompt


def test_compress_user_prompt_to_script_is_deterministic():
    prompt = "Add feature X\\n- update docs\\n- ship tests"
    script = compress_user_prompt_to_script(prompt)

    assert script.task_id == "task"
    assert script.intent.startswith("Add feature X")
    assert script.spec.features == ["update docs", "ship tests"]
    assert script.constraints == []
    assert script.budgets == {}
