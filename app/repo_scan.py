from __future__ import annotations

import os

INCLUDE_EXTS = {
    ".py",
    ".js",
    ".ts",
    ".java",
    ".c",
    ".cpp",
    ".h",
    ".hpp",
    ".json",
    ".md",
}


def scan_repo(repo_root: str) -> list[dict[str, str]]:
    files: list[dict[str, str]] = []
    for root, dirs, fnames in os.walk(repo_root):
        for ex in [".git", "node_modules", "__pycache__", "dist", "build"]:
            if ex in dirs:
                dirs.remove(ex)
        for fname in fnames:
            ext = os.path.splitext(fname)[1]
            if ext not in INCLUDE_EXTS:
                continue
            path = os.path.join(root, fname)
            try:
                with open(path, "r", encoding="utf-8") as handle:
                    content = handle.read()
            except OSError:
                continue
            files.append({"path": path, "content": content})
    return files
