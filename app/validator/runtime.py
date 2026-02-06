from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, Optional

from app.llm_client import LLMClientError, chat_completions
from app.validator.engine import validate_request as deterministic_validate
from app.validator.schema import ErrorLocalization, FinalValidatorLabel, RequestRecord


def _build_messages(record: RequestRecord, retry_prompt: Optional[str] = None) -> list[dict[str, str]]:
    system_prompt = (
        "You are a validator. Output ONLY strict JSON for FinalValidatorLabel v0.1. "
        "Do not include Markdown or extra text."
    )
    user_payload = {
        "instruction": "Validate the response against schema and constraints.",
        "request_record": record.dict(),
    }
    if retry_prompt:
        user_payload["retry_prompt"] = retry_prompt
    return [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": json.dumps(user_payload)},
    ]


def _extract_content(response: Dict[str, Any]) -> str:
    try:
        return str(response["choices"][0]["message"]["content"])
    except (KeyError, IndexError, TypeError) as exc:
        raise LLMClientError("LLM response missing choices.message.content") from exc


def _write_attempt(path: Optional[Path], attempt: int, payload: Dict[str, Any]) -> None:
    if path is None:
        return
    path.mkdir(parents=True, exist_ok=True)
    filename = path / f"validator_attempt_{attempt:02d}.json"
    with filename.open("w", encoding="utf-8") as handle:
        json.dump(payload, handle, ensure_ascii=False, indent=2)


def validate_with_runtime(
    record: RequestRecord,
    model: Optional[Dict[str, Any]] = None,
    attempts_dir: Optional[Path] = None,
) -> FinalValidatorLabel:
    model = model or {}
    validator_config = model.get("validator_config") or {}
    use_llm = bool(validator_config.get("use_llm"))
    provider = model.get("provider")
    base_url = model.get("base_url")
    model_name = model.get("model_name")

    if not use_llm or not provider or not base_url or not model_name:
        return deterministic_validate(record)

    max_attempts = validator_config.get("max_attempts", 2)
    retry_prompt: Optional[str] = None
    last_error: Optional[str] = None

    for attempt in range(1, max_attempts + 1):
        messages = _build_messages(record, retry_prompt=retry_prompt)
        payload = {
            "model": model_name,
            "messages": messages,
            "temperature": 0,
        }
        try:
            response = chat_completions(base_url=base_url, payload=payload)
            content = _extract_content(response)
        except LLMClientError as exc:
            last_error = str(exc)
            _write_attempt(
                attempts_dir,
                attempt,
                {
                    "attempt": attempt,
                    "error": last_error,
                },
            )
            retry_prompt = "Force schema compliance. Output FinalValidatorLabel v0.1 JSON only."
            continue

        attempt_payload: Dict[str, Any] = {
            "attempt": attempt,
            "response_text": content,
        }
        try:
            parsed = json.loads(content)
            attempt_payload["parsed"] = parsed
            label = FinalValidatorLabel(**parsed)
            _write_attempt(attempts_dir, attempt, attempt_payload)
            return label
        except (json.JSONDecodeError, TypeError, ValueError) as exc:
            last_error = str(exc)
            attempt_payload["error"] = last_error
            _write_attempt(attempts_dir, attempt, attempt_payload)
            retry_prompt = (
                "Force schema compliance. Output FinalValidatorLabel v0.1 JSON only."
                " Fix validation errors and include all required fields."
            )

    label = deterministic_validate(record)
    if last_error:
        label.error_localization.append(
            ErrorLocalization(
                severity="error",
                path="$.llm_runtime",
                issue="llm_validation_failed",
                why=last_error,
                fix_hint="Ensure the validator model returns strict FinalValidatorLabel v0.1 JSON.",
            )
        )
    return label
