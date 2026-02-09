from __future__ import annotations

import argparse
from pathlib import Path

from app.tier1.config import default_tier1_config
from app.tier1.indexer import compute_repo_fingerprint, index_dir
from app.tier1.query import select_files
from app.tier1.scanner import scan_repo


def main() -> int:
    parser = argparse.ArgumentParser(description="Tier-1 TF-IDF smoke test")
    parser.add_argument("repo_root", type=Path)
    parser.add_argument("query", type=str)
    args = parser.parse_args()

    cfg = default_tier1_config()
    result = select_files(args.repo_root, args.query, cfg)

    files = scan_repo(args.repo_root, cfg)
    fingerprint = compute_repo_fingerprint(files)
    expected_dir = index_dir(cfg.index_root, fingerprint)
    if not expected_dir.exists():
        raise SystemExit(f"Index directory not created: {expected_dir}")

    for item in result.items[:20]:
        print(item.rel_path)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
