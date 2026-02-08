from __future__ import annotations

import json
from typing import Any, Dict, List, Tuple

from app.validator.schema import (
    CompressedScript,
    CompressedSpec,
    ControlDecision,
    ErrorLocalization,
    FinalValidatorLabel,
    HardChecks,
    OrchestraBriefing,
    RequestRecord,
    SoftChecks,
)


_TYPE_MAP = {
    "string": str,
    "number": (int, float),
    "boolean": bool,
    "array": list,
    "object": dict,
    "null": type(None),
}


def _parse_json(text: str) -> Tuple[bool, Any, str]:
    try:
        return True, json.loads(text), ""
    except json.JSONDecodeError as exc:
        return False, None, str(exc)


def _check_field_types(payload: Dict[str, Any], field_types: Dict[str, str]) -> List[str]:
    mismatches = []
    for field, expected in field_types.items():
        if field not in payload:
            continue
        expected_type = _TYPE_MAP[expected]
        if not isinstance(payload[field], expected_type):
            mismatches.append(field)
    return mismatches


def _default_soft_checks(hard_checks: HardChecks) -> SoftChecks:
    scores = [
        hard_checks.json_parseable,
        hard_checks.schema_valid,
        hard_checks.required_fields_present,
        hard_checks.no_extraneous_fields,
        hard_checks.field_types_valid,
    ]
    base = round(sum(1.0 for score in scores if score) / len(scores), 2)
    return SoftChecks(
        correctness=base,
        constraint_adherence=base,
        completeness=base,
        clarity=base,
        overall=base,
    )


def compress_user_prompt_to_script(user_prompt: str) -> CompressedScript:
    normalized = " ".join(str(user_prompt or "").strip().split())
    intent = normalized[:160] if normalized else "Clarify user intent."
    lines = [line.strip() for line in str(user_prompt or "").splitlines()]
    features: List[str] = []
    for line in lines:
        if not line:
            continue
        if line.startswith(("-", "*")):
            features.append(line.lstrip("-* ").strip())
        elif ":" in line and len(features) < 5:
            features.append(line.split(":", 1)[0].strip())
    if not features and normalized:
        features = [normalized[:120]]
    return CompressedScript(
        task_id="task",
        intent=intent,
        spec=CompressedSpec(features=features),
        constraints=[],
        budgets={},
    )


def validate_request(record: RequestRecord) -> FinalValidatorLabel:
    errors: List[ErrorLocalization] = []
    json_ok, parsed, parse_error = _parse_json(record.response_text)

    required_present = False
    no_extraneous = False
    types_valid = False
    is_object = isinstance(parsed, dict)

    if not json_ok:
        errors.append(
            ErrorLocalization(
                severity="error",
                path="$",
                issue="json_parse_error",
                why="Response is not valid JSON.",
                fix_hint="Return a valid JSON object.",
                span_hint=parse_error or None,
            )
        )
    elif not is_object:
        errors.append(
            ErrorLocalization(
                severity="error",
                path="$",
                issue="json_not_object",
                why="Response JSON is not an object.",
                fix_hint="Return a JSON object with key-value pairs.",
            )
        )
    else:
        required_present = all(field in parsed for field in record.required_fields)
        if not required_present:
            missing = [field for field in record.required_fields if field not in parsed]
            errors.append(
                ErrorLocalization(
                    severity="error",
                    path="$",
                    issue="missing_required_fields",
                    why=f"Missing required fields: {', '.join(missing)}.",
                    fix_hint="Include all required fields in the JSON object.",
                )
            )

        if record.allowed_fields is None:
            no_extraneous = True
        else:
            extraneous = [field for field in parsed if field not in record.allowed_fields]
            no_extraneous = len(extraneous) == 0
            if not no_extraneous:
                errors.append(
                    ErrorLocalization(
                        severity="error",
                        path="$",
                        issue="extraneous_fields",
                        why=f"Extraneous fields present: {', '.join(extraneous)}.",
                        fix_hint="Remove fields that are not allowed.",
                    )
                )

        mismatches = _check_field_types(parsed, record.field_types)
        types_valid = len(mismatches) == 0
        if not types_valid:
            for field in mismatches:
                errors.append(
                    ErrorLocalization(
                        severity="error",
                        path=f"$.{field}",
                        issue="field_type_mismatch",
                        why="Field type does not match expected schema.",
                        fix_hint="Update the field to the expected type.",
                    )
                )

    schema_valid = json_ok and is_object and required_present and no_extraneous and types_valid

    hard_checks = HardChecks(
        json_parseable=json_ok,
        schema_valid=schema_valid,
        required_fields_present=required_present,
        no_extraneous_fields=no_extraneous,
        field_types_valid=types_valid,
    )

    soft_checks = _default_soft_checks(hard_checks)

    if schema_valid and soft_checks.overall >= 0.7:
        minimal_rationale = (
            "All hard checks passed; soft scores are defaulted pending semantic review."
        )
        known_correct = ["Hard checks passed."]
        uncertain = ["Semantic correctness not assessed."]
        next_actions = [
            "Proceed to the next node.",
            "Monitor for semantic issues downstream.",
            "Run any required integration checks.",
        ]
        retry_prompt = "No retry required."
        control = ControlDecision(
            decision="accept",
            stop_conditions=[],
            route_to="next_node",
            max_retries=0,
        )
    elif schema_valid:
        minimal_rationale = "Hard checks passed, but soft scores indicate a quality gap."
        known_correct = ["Schema compliance passed."]
        uncertain = ["Semantic quality needs improvement."]
        next_actions = [
            "Review correctness against the goal.",
            "Tighten adherence to constraints.",
            "Improve completeness and clarity.",
        ]
        retry_prompt = (
            "Improve the response for correctness, constraint adherence, completeness, and clarity."
        )
        control = ControlDecision(
            decision="retry_same_node",
            retry_strategy="quality_review",
            stop_conditions=["max_retries_reached"],
            route_to="same_node",
            max_retries=0,
        )
    else:
        missing_required = [
            field for field in record.required_fields if not json_ok or not is_object or field not in (parsed or {})
        ]
        required_hint = (
            f" Required fields: {', '.join(missing_required)}."
            if missing_required
            else ""
        )
        retry_prompt = (
            "Return strict JSON object that matches the required schema." + required_hint
        )
        minimal_rationale = (
            "Hard checks failed; output must be corrected before semantic review."
        )
        known_correct = []
        uncertain = ["Schema compliance failed."]
        next_actions = [
            "Return valid JSON.",
            "Include all required fields.",
            "Remove extraneous fields and fix types.",
        ]
        control = ControlDecision(
            decision="retry_same_node",
            retry_strategy="schema_repair",
            stop_conditions=["max_retries_reached"],
            route_to="same_node",
            max_retries=0,
        )

    orchestra_briefing = OrchestraBriefing(
        known_correct=known_correct,
        uncertain_or_needs_check=uncertain,
        missing_inputs=[],
        next_actions=next_actions,
        optional_patch=None,
        retry_prompt=retry_prompt,
        script=compress_user_prompt_to_script(record.response_text),
        current_scope=[],
        allowed_actions=[],
        token_budget=None,
        constraints=[],
    )

    return FinalValidatorLabel(
        hard_checks=hard_checks,
        soft_checks=soft_checks,
        error_localization=errors,
        minimal_rationale=minimal_rationale,
        orchestra_briefing=orchestra_briefing,
        control=control,
    )
