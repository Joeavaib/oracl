from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, Optional

from app.llm_client import LLMClientError, chat_completions
from app.validator.engine import compress_user_prompt_to_script, validate_request as deterministic_validate
from app.validator.schema import (
    ControlDecision,
    ErrorLocalization,
    FinalValidatorLabel,
    HardChecks,
    OrchestraBriefing,
    RequestRecord,
    SoftChecks,
)
from protocols.tmp_s_v22 import TmpSError, TmpSMessage, normalize_tmp_s, parse_tmp_s, validate_tmp_s


def _build_messages(record: RequestRecord, retry_prompt: Optional[str] = None) -> list[dict[str, str]]:
    system_prompt = (
        "You are a validator. Output ONLY TMP-S v2.2 lines. "
        "No Markdown or extra text. Pipes must have no spaces. "
        "Header is mandatory: V|2.2|<run_id>|<stage>|<attempt>. "
        "Defaulting rules: decision P => accept|0|0|*, "
        "strategy defaults to 0, focus defaults to * if omitted."
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


def _write_text(path: Optional[Path], content: str) -> None:
    if path is None:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        handle.write(content)


def _write_parsed(path: Optional[Path], msg: TmpSMessage) -> None:
    if path is None:
        return
    payload = {
        "header": msg.header.__dict__,
        "audit": msg.audit.__dict__,
        "errors": [err.__dict__ for err in msg.errors],
        "briefs": [brief.__dict__ for brief in msg.briefs],
        "control": msg.control.__dict__,
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        json.dump(payload, handle, ensure_ascii=False, indent=2)


def _label_from_tmp_s(
    msg: TmpSMessage,
    record: RequestRecord,
    errors: Optional[list[TmpSError]] = None,
) -> FinalValidatorLabel:
    errors = errors or []
    control_decision = _map_decision(msg.control.decision)
    hard_checks = HardChecks(
        json_parseable=True,
        schema_valid=True,
        required_fields_present=True,
        no_extraneous_fields=True,
        field_types_valid=True,
    )
    soft_checks = SoftChecks(
        correctness=1.0,
        constraint_adherence=1.0,
        completeness=1.0,
        clarity=1.0,
        overall=1.0,
    )
    error_localization = [
        ErrorLocalization(
            severity=_map_severity(error.severity),
            path=error.path or "$.tmp_s",
            issue="tmp_s_error",
            why="Validator reported issue.",
            fix_hint=error.fix_hint,
        )
        for error in errors
    ]
    next_actions = [brief.action for brief in msg.briefs] or [
        "Review validator output.",
        "Fix TMP-S formatting.",
        "Retry validator run.",
    ]
    orchestra_briefing = OrchestraBriefing(
        known_correct=[],
        uncertain_or_needs_check=[],
        missing_inputs=[],
        next_actions=next_actions[:7],
        optional_patch=None,
        retry_prompt=_retry_prompt(msg.control.strategy, msg.control.focus),
        script=compress_user_prompt_to_script(record.prompt),
        current_scope=[],
        allowed_actions=[],
        token_budget=None,
        constraints=[],
    )
    control = ControlDecision(
        decision=control_decision,
        retry_strategy=msg.control.strategy or None,
        max_retries=msg.control.max_retries,
        stop_conditions=[],
        route_to=msg.control.focus or None,
    )
    return FinalValidatorLabel(
        hard_checks=hard_checks,
        soft_checks=soft_checks,
        error_localization=error_localization,
        minimal_rationale=msg.audit.rationale or "Validator output parsed from TMP-S.",
        orchestra_briefing=orchestra_briefing,
        control=control,
    )


def _map_decision(decision: str) -> str:
    normalized = (decision or "").lower()
    if normalized in {"a", "accept", "ok", "pass"}:
        return "accept"
    if normalized in {"r", "retry", "retry_same_node"}:
        return "retry_same_node"
    if normalized in {"x", "reroute"}:
        return "reroute"
    if normalized in {"e", "escalate"}:
        return "escalate"
    if normalized == "abort":
        return "abort"
    return "retry_same_node"


def _map_severity(severity: str) -> str:
    normalized = (severity or "").lower()
    if normalized in {"info", "warning", "error"}:
        return normalized
    return "error"


def _retry_prompt(strategy: str, focus: str) -> str:
    if strategy or focus:
        return f"Retry with strategy={strategy or '0'} focus={focus or '*' }."
    return "Retry with TMP-S v2.2 compliance."


def _fallback_tmp_s(
    record: RequestRecord,
    attempt: int,
    error: str,
) -> tuple[TmpSMessage, str]:
    text = "\n".join(
        [
            f"V|2.2|{record.request_id}|validator|{attempt}",
            "A|0000|0000|retry|TMP-S parse or validation failed.",
            f"E|$.tmp_s|error|{error}",
            "B|p1:system|Review TMP-S formatting.",
            "B|p2:system|Return valid TMP-S lines.",
            "B|p3:system|Retry validator output.",
            "C|retry|5|0|fallback_minimal",
        ]
    )
    msg = parse_tmp_s(text)
    return normalize_tmp_s(msg), text


def _tmp_s_from_label(
    label: FinalValidatorLabel,
    record: RequestRecord,
    stage_id: str,
    attempt: int,
) -> tuple[TmpSMessage, str]:
    decision = label.control.decision or "retry_same_node"
    strategy = label.control.retry_strategy or "0"
    max_retries = label.control.max_retries or 0
    focus = label.control.route_to or "*"
    text = "\n".join(
        [
            f"V|2.2|{record.request_id}|{stage_id}|{attempt}",
            f"A|0000|0000|{decision}|{label.minimal_rationale}",
            "B|p1:system|Review deterministic validator output.",
            "B|p2:system|Proceed with next step if applicable.",
            "B|p3:system|Log validator decision.",
            f"C|{decision}|{strategy}|{max_retries}|{focus}",
        ]
    )
    msg = normalize_tmp_s(parse_tmp_s(text))
    return msg, text


def validate_with_runtime(
    record: RequestRecord,
    model: Optional[Dict[str, Any]] = None,
    attempts_dir: Optional[Path] = None,
    tmp_s_path: Optional[Path] = None,
    parsed_path: Optional[Path] = None,
    stage_id: str = "validator",
) -> FinalValidatorLabel:
    model = model or {}
    validator_config = model.get("validator_config") or {}
    use_llm = bool(validator_config.get("use_llm"))
    provider = model.get("provider")
    base_url = model.get("base_url")
    model_name = model.get("model_name")

    if not use_llm or not provider or not base_url or not model_name:
        label = deterministic_validate(record)
        msg, text = _tmp_s_from_label(label, record, stage_id, attempt=0)
        _write_text(tmp_s_path, text)
        _write_parsed(parsed_path, msg)
        return label

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
            retry_prompt = "TMP-S required. Output TMP-S v2.2 lines only."
            continue

        attempt_payload: Dict[str, Any] = {"attempt": attempt, "response_text": content}
        msg = normalize_tmp_s(parse_tmp_s(content))
        validation_errors = validate_tmp_s(msg)
        if validation_errors:
            last_error = "; ".join(err.fix_hint for err in validation_errors)
            attempt_payload["error"] = last_error
            attempt_payload["tmp_s_errors"] = [err.__dict__ for err in validation_errors]
            _write_attempt(attempts_dir, attempt, attempt_payload)
            retry_prompt = (
                "TMP-S invalid. Output only TMP-S v2.2 lines in correct order with pipes"
                " and required counts."
            )
            continue

        attempt_payload["parsed_tmp_s"] = {
            "header": msg.header.__dict__,
            "audit": msg.audit.__dict__,
            "errors": [err.__dict__ for err in msg.errors],
            "briefs": [brief.__dict__ for brief in msg.briefs],
            "control": msg.control.__dict__,
        }
        _write_attempt(attempts_dir, attempt, attempt_payload)
        _write_text(tmp_s_path, content)
        _write_parsed(parsed_path, msg)
        return _label_from_tmp_s(msg, record, msg.errors)

    fallback_msg, fallback_text = _fallback_tmp_s(
        record,
        max_attempts,
        last_error or "Unknown TMP-S error.",
    )
    _write_text(tmp_s_path, fallback_text)
    _write_parsed(parsed_path, fallback_msg)
    fallback_label = _label_from_tmp_s(
        fallback_msg,
        record,
        [TmpSError(path="$.llm_runtime", severity="error", fix_hint=last_error or "TMP-S invalid.")],
    )
    return fallback_label
