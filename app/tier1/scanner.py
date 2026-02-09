from __future__ import annotations

import hashlib
import os
from pathlib import Path
from typing import Iterable

from app.tier1.types import Tier1Config, Tier1FileMeta


def scan_repo(repo_root: Path, cfg: Tier1Config) -> list[Tier1FileMeta]:
    repo_root = repo_root.resolve()
    files: list[Tier1FileMeta] = []
    for path in _iter_candidate_files(repo_root, cfg):
        stat = path.stat()
        files.append(
            Tier1FileMeta(
                id=len(files),
                rel_path=_rel_path(repo_root, path),
                abs_path=path.as_posix(),
                sha1=_sha1(path),
                size=stat.st_size,
                mtime=stat.st_mtime,
                lang=_lang_from_ext(path.suffix),
                loc=_count_lines(path),
            )
        )
    return files


def _iter_candidate_files(repo_root: Path, cfg: Tier1Config) -> Iterable[Path]:
    for root, dirs, filenames in os.walk(repo_root):
        root_path = Path(root)
        dirs[:] = [
            d for d in dirs if d not in cfg.exclude_dirs and not d.startswith(".")
        ]
        for filename in filenames:
            if filename.startswith("."):
                continue
            path = root_path / filename
            if path.suffix.lower() not in cfg.include_exts:
                continue
            yield path


def _sha1(path: Path) -> str:
    digest = hashlib.sha1()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(8192), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _rel_path(repo_root: Path, path: Path) -> str:
    try:
        return path.relative_to(repo_root).as_posix()
    except ValueError:
        return path.as_posix()


def _lang_from_ext(ext: str) -> str:
    return ext.lstrip(".").lower() or "text"


def _count_lines(path: Path) -> int:
    try:
        content = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return 0
    return content.count("\n") + (1 if content else 0)
