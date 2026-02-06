from __future__ import annotations

from datetime import datetime
from typing import Dict, List, Literal, Optional

from pydantic import BaseModel, Field


class RequestRecord(BaseModel):
    version: Literal["0.1"] = Field("0.1", description="Schema version.")
    request_id: str
    created_at: datetime
    prompt: str
    response_text: str
    required_fields: List[str] = Field(default_factory=list)
    allowed_fields: Optional[List[str]] = None
    field_types: Dict[str, Literal["string", "number", "boolean", "array", "object", "null"]] = Field(
        default_factory=dict
    )

    class Config:
        extra = "forbid"


class HardChecks(BaseModel):
    json_parseable: bool
    schema_valid: bool
    required_fields_present: bool
    no_extraneous_fields: bool
    field_types_valid: bool

    class Config:
        extra = "forbid"


class SoftChecks(BaseModel):
    correctness: float = Field(ge=0.0, le=1.0)
    constraint_adherence: float = Field(ge=0.0, le=1.0)
    completeness: float = Field(ge=0.0, le=1.0)
    clarity: float = Field(ge=0.0, le=1.0)
    overall: float = Field(ge=0.0, le=1.0)

    class Config:
        extra = "forbid"


class ErrorLocalization(BaseModel):
    severity: Literal["info", "warning", "error"]
    path: str
    issue: str
    why: str
    fix_hint: str
    span_hint: Optional[str] = None

    class Config:
        extra = "forbid"


class OrchestraBriefing(BaseModel):
    known_correct: List[str]
    uncertain_or_needs_check: List[str]
    missing_inputs: List[str]
    next_actions: List[str] = Field(min_items=3, max_items=7)
    optional_patch: Optional[str] = None
    retry_prompt: str

    class Config:
        extra = "forbid"


class ControlDecision(BaseModel):
    decision: Literal["accept", "retry_same_node", "reroute", "escalate", "abort"]
    retry_strategy: Optional[str] = None
    stop_conditions: List[str]
    route_to: Optional[str] = None

    class Config:
        extra = "forbid"


class FinalValidatorLabel(BaseModel):
    version: Literal["0.1"] = Field("0.1", description="Schema version.")
    hard_checks: HardChecks
    soft_checks: SoftChecks
    error_localization: List[ErrorLocalization]
    minimal_rationale: str
    orchestra_briefing: OrchestraBriefing
    control: ControlDecision

    class Config:
        extra = "forbid"
