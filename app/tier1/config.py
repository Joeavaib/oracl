from __future__ import annotations

from app.tier1.types import Tier1Config


DEFAULT_INCLUDE_EXTS = {
    ".cfg",
    ".css",
    ".html",
    ".ini",
    ".js",
    ".json",
    ".md",
    ".py",
    ".toml",
    ".ts",
    ".tsx",
    ".txt",
    ".yaml",
    ".yml",
}
DEFAULT_EXCLUDE_DIRS = {
    ".git",
    ".pytest_cache",
    ".venv",
    "__pycache__",
    "build",
    "coverage",
    "dist",
    "node_modules",
    "runs",
    "venv",
}


def default_tier1_config() -> Tier1Config:
    return Tier1Config(
        include_exts=set(DEFAULT_INCLUDE_EXTS),
        exclude_dirs=set(DEFAULT_EXCLUDE_DIRS),
        max_features=50000,
        ngram_range=(1, 2),
        min_df=1,
        max_df=1.0,
        top_k_stage1=200,
        top_k_final=20,
    )
