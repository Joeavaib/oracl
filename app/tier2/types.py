from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Dict, List


@dataclass
class Tier1Candidate:
    rel_path: str
    score: float = 0.0
    rank: int = 0
    preview: str = ""


@dataclass
class Tier2ModelInfo:
    model_id: str = ""
    model_path: str = ""
    base_url: str = ""


@dataclass
class Tier2SelectionResult:
    query: str
    candidates: List[Dict[str, Any]]
    selected_paths: List[str]
    reason_brief: str = ""
    model: Tier2ModelInfo = field(default_factory=Tier2ModelInfo)

    def to_dict(self) -> Dict[str, Any]:
        payload = asdict(self)
        payload["selected_paths"] = self.selected_paths[:5]
        return payload


@dataclass
class Tier2FileContext:
    path: str
    purpose: str
    key_symbols: List[str] = field(default_factory=list)
    imports: List[str] = field(default_factory=list)
    classes: List[str] = field(default_factory=list)
    functions: List[str] = field(default_factory=list)
    notes: List[str] = field(default_factory=list)


@dataclass
class Tier2CompressionStats:
    input_bytes: int
    output_bytes: int
    compression_ratio_est: float


@dataclass
class Tier2ContextBundle:
    overall_summary: str
    files: List[Tier2FileContext]
    stats: Tier2CompressionStats

    def to_dict(self) -> Dict[str, Any]:
        payload = asdict(self)
        payload["files"] = [asdict(item) for item in self.files]
        return payload
