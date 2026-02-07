from __future__ import annotations

import re
from pathlib import Path
from typing import Any, Dict, List

from app.models_registry import gguf_dir


_SLUG_PATTERN = re.compile(r"[^a-z0-9]+")


def _slugify(value: str) -> str:
    cleaned = _SLUG_PATTERN.sub("-", value.lower()).strip("-")
    return cleaned or "model"


def list_local_gguf_models() -> List[Dict[str, Any]]:
    root = gguf_dir()
    if root is None or not root.exists():
        return []

    suggestions: List[Dict[str, Any]] = []
    for path in sorted(root.rglob("*.gguf")):
        if not path.is_file():
            continue
        stat = path.stat()
        suggestions.append(
            {
                "suggested_id": _slugify(path.stem),
                "model_path": str(path),
                "display_name": path.name,
                "size_bytes": stat.st_size,
                "mtime": stat.st_mtime,
            }
        )
    return suggestions
