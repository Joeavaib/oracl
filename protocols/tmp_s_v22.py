"""TMP-S v2.2 protocol parser, validator, and normalizer."""

from __future__ import annotations

from dataclasses import dataclass, replace
from typing import List, Optional


MAX_RATIONALE_WORDS = 40
MIN_BRIEFS = 3
MAX_BRIEFS = 7


@dataclass(frozen=True)
class TmpSHeader:
    ver: Optional[str]
    run_id: Optional[str]
    stage: Optional[str]
    attempt: Optional[int]


@dataclass(frozen=True)
class TmpSAudit:
    hard4: str
    soft4: str
    verdict: str
    rationale: str


@dataclass(frozen=True)
class TmpSError:
    path: str
    severity: str
    fix_hint: str


@dataclass(frozen=True)
class TmpSBrief:
    pri: str
    agent: str
    action: str


@dataclass(frozen=True)
class TmpSControl:
    decision: str
    strategy: str
    max_retries: int
    focus: str


@dataclass(frozen=True)
class TmpSMessage:
    header: TmpSHeader
    audit: TmpSAudit
    errors: List[TmpSError]
    briefs: List[TmpSBrief]
    control: TmpSControl
    raw_lines: List[str]


def parse_tmp_s(text: str) -> TmpSMessage:
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    header = TmpSHeader(ver=None, run_id=None, stage=None, attempt=None)
    audit = TmpSAudit(hard4="", soft4="", verdict="", rationale="")
    errors: List[TmpSError] = []
    briefs: List[TmpSBrief] = []
    control = TmpSControl(decision="", strategy="", max_retries=0, focus="")

    for line in lines:
        prefix = line[0]
        if prefix == "V":
            header = _parse_header(line)
        elif prefix == "A":
            audit = _parse_audit(line)
        elif prefix == "E":
            errors.append(_parse_error(line))
        elif prefix == "B":
            briefs.append(_parse_brief(line))
        elif prefix == "C":
            control = _parse_control(line)
        else:
            continue

    return TmpSMessage(
        header=header,
        audit=audit,
        errors=errors,
        briefs=briefs,
        control=control,
        raw_lines=lines,
    )


def validate_tmp_s(msg: TmpSMessage) -> List[TmpSError]:
    issues: List[TmpSError] = []
    lines = msg.raw_lines
    if not lines:
        return [TmpSError(path="tmp-s", severity="error", fix_hint="No TMP-S lines provided.")]

    for line in lines:
        if " |" in line or "| " in line:
            issues.append(
                TmpSError(
                    path="tmp-s",
                    severity="error",
                    fix_hint="Pipes must have no surrounding spaces.",
                )
            )
        if line.startswith("A"):
            fields = _split_fields(line[1:])
            if len(fields) != 4:
                issues.append(
                    TmpSError(
                        path="tmp-s",
                        severity="error",
                        fix_hint="A line must have 4 fields.",
                    )
                )
        elif line.startswith("E"):
            fields = _split_fields(line[1:])
            if len(fields) != 3:
                issues.append(
                    TmpSError(
                        path="tmp-s",
                        severity="error",
                        fix_hint="E line must have 3 fields.",
                    )
                )
        elif line.startswith("B"):
            fields = _split_fields(line[1:])
            if len(fields) != 2:
                issues.append(
                    TmpSError(
                        path="tmp-s",
                        severity="error",
                        fix_hint="B line must have 2 fields.",
                    )
                )
        elif line.startswith("C"):
            fields = _split_fields(line[1:])
            if len(fields) != 4:
                issues.append(
                    TmpSError(
                        path="tmp-s",
                        severity="error",
                        fix_hint="C line must have 4 fields.",
                    )
                )

    types = [line[0] for line in lines if line]
    if not types or types[0] != "V":
        issues.append(
            TmpSError(path="tmp-s", severity="error", fix_hint="TMP-S must start with V line.")
        )
    if "A" not in types:
        issues.append(TmpSError(path="tmp-s", severity="error", fix_hint="Missing A line."))
    if not types or types[-1] != "C":
        issues.append(
            TmpSError(path="tmp-s", severity="error", fix_hint="TMP-S must end with C line.")
        )

    if _violates_order(types):
        issues.append(
            TmpSError(
                path="tmp-s",
                severity="error",
                fix_hint="Line order must be V, A, E*, B{3..7}, C.",
            )
        )

    if any(line and line[0] not in {"V", "A", "E", "B", "C"} for line in lines):
        issues.append(
            TmpSError(
                path="tmp-s",
                severity="error",
                fix_hint="Unsupported line prefix detected.",
            )
        )

    brief_count = sum(1 for t in types if t == "B")
    if brief_count < MIN_BRIEFS or brief_count > MAX_BRIEFS:
        issues.append(
            TmpSError(
                path="tmp-s",
                severity="error",
                fix_hint=f"B lines must be between {MIN_BRIEFS} and {MAX_BRIEFS}.",
            )
        )

    if msg.audit.rationale:
        words = msg.audit.rationale.split()
        if len(words) > MAX_RATIONALE_WORDS:
            issues.append(
                TmpSError(
                    path="tmp-s",
                    severity="error",
                    fix_hint="Rationale exceeds word limit.",
                )
            )
        if "|" in msg.audit.rationale:
            issues.append(
                TmpSError(
                    path="tmp-s",
                    severity="error",
                    fix_hint="Rationale contains invalid pipe character.",
                )
            )

    return issues


def normalize_tmp_s(msg: TmpSMessage) -> TmpSMessage:
    header = msg.header
    if not header.ver:
        header = replace(header, ver="2.2")
    if header.attempt is None:
        header = replace(header, attempt=0)

    control = msg.control
    decision = control.decision or ""
    if decision.upper() == "P":
        control = replace(control, decision="accept", strategy="0", max_retries=0, focus="*")
    else:
        strategy = control.strategy or "0"
        focus = control.focus or "*"
        control = replace(control, strategy=strategy, focus=focus)

    return replace(msg, header=header, control=control)


def _parse_header(line: str) -> TmpSHeader:
    stripped = line[1:]
    if stripped.startswith("?"):
        stripped = stripped[1:]
    parts = _split_fields(stripped)
    if not parts:
        return TmpSHeader(ver=None, run_id=None, stage=None, attempt=None)
    ver = parts[0] if len(parts) > 0 else None
    run_id = parts[1] if len(parts) > 1 else None
    stage = parts[2] if len(parts) > 2 else None
    attempt = None
    if len(parts) > 3:
        attempt = _parse_int(parts[3])
    return TmpSHeader(ver=ver or None, run_id=run_id or None, stage=stage or None, attempt=attempt)


def _parse_audit(line: str) -> TmpSAudit:
    parts = _split_fields(line[1:])
    hard4 = parts[0] if len(parts) > 0 else ""
    soft4 = parts[1] if len(parts) > 1 else ""
    verdict = parts[2] if len(parts) > 2 else ""
    rationale = parts[3] if len(parts) > 3 else ""
    return TmpSAudit(hard4=hard4, soft4=soft4, verdict=verdict, rationale=rationale)


def _parse_error(line: str) -> TmpSError:
    parts = _split_fields(line[1:])
    path = parts[0] if len(parts) > 0 else ""
    severity = parts[1] if len(parts) > 1 else ""
    fix_hint = parts[2] if len(parts) > 2 else ""
    return TmpSError(path=path, severity=severity, fix_hint=fix_hint)


def _parse_brief(line: str) -> TmpSBrief:
    parts = _split_fields(line[1:])
    pri_agent = parts[0] if len(parts) > 0 else ""
    action = parts[1] if len(parts) > 1 else ""
    pri, agent = _split_pri_agent(pri_agent)
    return TmpSBrief(pri=pri, agent=agent, action=action)


def _parse_control(line: str) -> TmpSControl:
    parts = _split_fields(line[1:])
    decision = parts[0] if len(parts) > 0 else ""
    strategy = parts[1] if len(parts) > 1 else ""
    max_retries = _parse_int(parts[2]) if len(parts) > 2 else 0
    focus = parts[3] if len(parts) > 3 else ""
    return TmpSControl(decision=decision, strategy=strategy, max_retries=max_retries, focus=focus)


def _split_fields(text: str) -> List[str]:
    if not text:
        return []
    if text.startswith("|"):
        text = text[1:]
    return text.split("|") if text else []


def _split_pri_agent(value: str) -> tuple[str, str]:
    if ":" not in value:
        return value, ""
    pri, agent = value.split(":", 1)
    return pri, agent


def _parse_int(value: str) -> Optional[int]:
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _violates_order(types: List[str]) -> bool:
    try:
        v_index = types.index("V")
        a_index = types.index("A")
        c_index = len(types) - 1 - types[::-1].index("C")
    except ValueError:
        return True
    if v_index != 0 or a_index != 1 or c_index != len(types) - 1:
        return True
    for idx, t in enumerate(types):
        if idx <= a_index:
            continue
        if t == "E":
            continue
        if t == "B":
            continue
        if t == "C" and idx == c_index:
            continue
        return True
    seen_b = False
    for t in types[a_index + 1 : c_index]:
        if t == "E" and seen_b:
            return True
        if t == "B":
            seen_b = True
        if t not in {"E", "B"}:
            return True
    return False
