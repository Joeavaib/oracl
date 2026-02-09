from __future__ import annotations

from pathlib import Path

from app.tier1.config import default_tier1_config
from app.tier1.indexer import build_index, compute_repo_fingerprint, index_dir
from app.tier1.query import select_files
from app.tier1.scanner import scan_repo


def _write_file(root: Path, rel_path: str, content: str) -> None:
    path = root / rel_path
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def test_build_index_and_query_are_deterministic(tmp_path: Path) -> None:
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    _write_file(repo_root, "alpha.py", "def alpha():\n    return 'alpha'\n")
    _write_file(repo_root, "beta.md", "# Beta\nbeta beta\n")
    _write_file(repo_root, "gamma.txt", "gamma content\n")

    cfg = default_tier1_config()
    cfg = cfg.__class__(**{**cfg.__dict__, "index_root": tmp_path / "index"})

    build_index(repo_root, cfg)
    result = select_files(repo_root, "beta", cfg)

    assert len(result.items) <= 20

    second_result = select_files(repo_root, "beta", cfg)
    assert [item.rel_path for item in result.items] == [
        item.rel_path for item in second_result.items
    ]

    files = scan_repo(repo_root, cfg)
    fingerprint = compute_repo_fingerprint(files)
    expected_dir = index_dir(cfg.index_root, fingerprint)
    assert expected_dir.exists()
