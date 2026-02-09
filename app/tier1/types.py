from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path


def default_index_root() -> Path:
    return Path(__file__).resolve().parents[2] / "data" / "tier1_index"


@dataclass(frozen=True)
class Tier1Config:
    include_exts: set[str]
    exclude_dirs: set[str]
    max_features: int
    ngram_range: tuple[int, int]
    min_df: int
    max_df: float
    top_k_stage1: int
    top_k_final: int
    index_root: Path = field(default_factory=default_index_root)


@dataclass(frozen=True)
class Tier1FileMeta:
    id: int
    rel_path: str
    abs_path: str
    sha1: str
    size: int
    mtime: float
    lang: str
    loc: int


@dataclass(frozen=True)
class Tier1SelectionItem:
    id: int
    rel_path: str
    abs_path: str
    score: float
    rank: int


@dataclass(frozen=True)
class Tier1SelectionResult:
    repo_fingerprint: str
    query: str
    top_k_stage1: int
    top_k_final: int
    items: list[Tier1SelectionItem]
