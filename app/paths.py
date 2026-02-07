from __future__ import annotations

import os
from pathlib import Path


def repo_root() -> Path:
    return Path(__file__).resolve().parents[1]


def runs_dir() -> Path:
    return Path(os.getenv("RUNS_DIR", repo_root() / "runs"))
