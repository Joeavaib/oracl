from __future__ import annotations

import hashlib
import os
from subprocess import PIPE, Popen

BASE = "data/tier1_cache"


def git_sha(repo_root: str) -> str | None:
    try:
        process = Popen(["git", "-C", repo_root, "rev-parse", "HEAD"], stdout=PIPE)
        out = process.communicate()[0].decode().strip()
        return out or None
    except OSError:
        return None


def repo_snapshot_hash(repo_root: str) -> str:
    sha = git_sha(repo_root)
    if sha:
        return sha

    files: list[str] = []
    for root, _, fnames in os.walk(repo_root):
        for fname in fnames:
            path = os.path.join(root, fname)
            try:
                stat = os.stat(path)
            except OSError:
                continue
            files.append(f"{path}:{stat.st_mtime}")
    files.sort()
    return hashlib.sha256("||".join(files).encode()).hexdigest()


def get_cache_dir(repo_root: str) -> str:
    key = repo_snapshot_hash(repo_root)
    path = os.path.join(BASE, key)
    os.makedirs(path, exist_ok=True)
    return path
