"""TMP-S v2.2 compiler: parse lines and validate ordering/limits."""

from __future__ import annotations

from dataclasses import dataclass
from typing import List, Optional

from app.tmps.spec import (
    ALLOWED_PREFIXES,
    LIMIT_ACTION_TOKENS,
    LIMIT_FIX_HINT_TOKENS,
    LIMIT_PAYLOAD_TOKENS,
    LIMIT_RATIONALE_WORDS,
    MAX_BRIEFS,
    MIN_BRIEFS,
)


@dataclass(frozen=True)
class Record:
    prefix: str
    fields: List[str]
    raw: str


@dataclass(frozen=True)
class CompileIssue:
    message: str


@dataclass(frozen=True)
class CompiledTmps:
    header: Optional[Record]
    audit: Optional[Record]
    errors: List[Record]
    briefs: List[Record]
    control: Optional[Record]
    outputs: List[Record]
    stages: List[Record]
    issues: List[CompileIssue]


def parse_lines(text: str) -> List[Record]:
    records: List[Record] = []
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped:
            records.append(Record(prefix="", fields=[], raw=line))
            continue
        prefix = stripped[0]
        if prefix not in ALLOWED_PREFIXES:
            records.append(Record(prefix=prefix, fields=[], raw=stripped))
            continue
        payload = stripped[1:].lstrip()
        fields = payload.split("|") if payload else []
        records.append(Record(prefix=prefix, fields=fields, raw=stripped))
    return records


def compile_tmps(text: str) -> CompiledTmps:
    records = parse_lines(text)
    issues = _validate_records(records)
    header = _first(records, "V")
    audit = _first(records, "A")
    control = _first(records, "C")
    errors = [rec for rec in records if rec.prefix == "E"]
    briefs = [rec for rec in records if rec.prefix == "B"]
    outputs = [rec for rec in records if rec.prefix == "O"]
    stages = [rec for rec in records if rec.prefix == "S"]
    return CompiledTmps(
        header=header,
        audit=audit,
        errors=errors,
        briefs=briefs,
        control=control,
        outputs=outputs,
        stages=stages,
        issues=issues,
    )


def _validate_records(records: List[Record]) -> List[CompileIssue]:
    issues: List[CompileIssue] = []
    if any(rec.prefix == "" for rec in records):
        issues.append(CompileIssue("Empty lines are not allowed in TMP-S."))
    for rec in records:
        if rec.prefix and rec.prefix not in ALLOWED_PREFIXES:
            issues.append(CompileIssue(f"Unsupported prefix: {rec.prefix}"))
        if " |" in rec.raw or "| " in rec.raw:
            issues.append(CompileIssue("No spaces allowed around pipes."))
    prefix_order = [rec.prefix for rec in records if rec.prefix]
    if not prefix_order or prefix_order[0] != "V":
        issues.append(CompileIssue("TMP-S must start with V line."))
    if "A" not in prefix_order:
        issues.append(CompileIssue("Missing A line."))
    if not prefix_order or prefix_order[-1] not in {"C", "O", "S"}:
        issues.append(CompileIssue("TMP-S must include a C line before any S/O output."))

    after_c = False
    briefs = 0
    for prefix in prefix_order:
        if prefix == "C":
            after_c = True
            continue
        if prefix in {"S", "O"}:
            if not after_c:
                issues.append(CompileIssue("S/O records must appear after C."))
        elif after_c:
            issues.append(CompileIssue("Only S/O records allowed after C."))
        if prefix == "B":
            briefs += 1
    if briefs < MIN_BRIEFS or briefs > MAX_BRIEFS:
        issues.append(CompileIssue(f"B count must be {MIN_BRIEFS}..{MAX_BRIEFS}."))

    for rec in records:
        if rec.prefix == "A" and len(rec.fields) != 4:
            issues.append(CompileIssue("A line must have 4 fields."))
            continue
        if rec.prefix == "E" and len(rec.fields) != 3:
            issues.append(CompileIssue("E line must have 3 fields."))
            continue
        if rec.prefix == "B" and len(rec.fields) != 2:
            issues.append(CompileIssue("B line must have 2 fields."))
            continue
        if rec.prefix == "C" and len(rec.fields) != 4:
            issues.append(CompileIssue("C line must have 4 fields."))
            continue
        if rec.prefix == "S" and len(rec.fields) != 4:
            issues.append(CompileIssue("S line must have 4 fields."))
            continue
        if rec.prefix == "O" and len(rec.fields) != 3:
            issues.append(CompileIssue("O line must have 3 fields."))
            continue

        if rec.prefix == "A":
            verdict = rec.fields[2]
            if verdict not in {"P", "W", "F", "H"}:
                issues.append(CompileIssue("Verdict must be P/W/F/H."))
            rationale_words = rec.fields[3].split()
            if len(rationale_words) > LIMIT_RATIONALE_WORDS:
                issues.append(CompileIssue("Rationale exceeds word limit."))
        if rec.prefix == "E":
            severity = rec.fields[1]
            if severity not in {"C", "H", "M", "L"}:
                issues.append(CompileIssue("Severity must be C/H/M/L."))
            if len(rec.fields[2].split()) > LIMIT_FIX_HINT_TOKENS:
                issues.append(CompileIssue("Fix hint exceeds token limit."))
        if rec.prefix == "B":
            if len(rec.fields[1].split()) > LIMIT_ACTION_TOKENS:
                issues.append(CompileIssue("B action exceeds token limit."))
        if rec.prefix == "C":
            decision = rec.fields[0]
            if decision not in {"A", "R", "X", "E"}:
                issues.append(CompileIssue("Decision must be A/R/X/E."))
            strategy = rec.fields[1]
            if strategy not in {"0", "1", "2", "3", "4"}:
                issues.append(CompileIssue("Strategy must be 0..4."))
        if rec.prefix == "O":
            payload = rec.fields[2]
            if "|" in payload:
                issues.append(CompileIssue("O payload must not contain '|'."))
            if len(payload.split()) > LIMIT_PAYLOAD_TOKENS:
                issues.append(CompileIssue("O payload exceeds token limit."))
    return issues


def _first(records: List[Record], prefix: str) -> Optional[Record]:
    for rec in records:
        if rec.prefix == prefix:
            return rec
    return None
