from __future__ import annotations

from pathlib import Path

from app.tier1.types import Tier1FileMeta


def preprocess_docs(
    files: list[Tier1FileMeta],
) -> tuple[list[str], list[Tier1FileMeta]]:
    documents: list[str] = []
    kept: list[Tier1FileMeta] = []
    for meta in files:
        content = _read_text(Path(meta.abs_path))
        if not content:
            continue
        documents.append(content)
        kept.append(meta)
    return documents, kept


def _read_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""
