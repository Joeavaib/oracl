from datetime import datetime

import pytest

pytest.importorskip("pydantic")

from pydantic import ValidationError

from app.validator.engine import validate_request
from app.validator.schema import FinalValidatorLabel, RequestRecord


def test_final_validator_label_schema_rejects_extra_fields():
    record = RequestRecord(
        request_id="req-1",
        created_at=datetime(2024, 1, 1),
        prompt="Return JSON",
        response_text='{"ok": true}',
        required_fields=["ok"],
        allowed_fields=["ok"],
        field_types={"ok": "boolean"},
    )
    label = validate_request(record)
    payload = label.dict()
    payload["extra"] = "nope"

    with pytest.raises(ValidationError):
        FinalValidatorLabel(**payload)


def test_validate_request_accepts_valid_payload():
    record = RequestRecord(
        request_id="req-2",
        created_at=datetime(2024, 1, 1),
        prompt="Return JSON",
        response_text='{"foo": "bar", "count": 2}',
        required_fields=["foo"],
        allowed_fields=["foo", "count"],
        field_types={"foo": "string", "count": "number"},
    )

    label = validate_request(record)

    assert label.hard_checks.schema_valid is True
    assert label.control.decision == "accept"
    assert label.soft_checks.overall == 1.0
    assert label.orchestra_briefing.retry_prompt == "No retry required."
