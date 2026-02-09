from __future__ import annotations

from dataclasses import asdict
from pathlib import Path
from typing import Any

from app.tier1.indexer import build_index, compute_repo_fingerprint, index_dir, load_index
from app.tier1.scanner import scan_repo
from app.tier1.types import Tier1Config, Tier1SelectionItem, Tier1SelectionResult


def select_files(
    repo_root: Path,
    query: str,
    cfg: Tier1Config,
    force_rebuild: bool = False,
) -> Tier1SelectionResult:
    files = scan_repo(repo_root, cfg)
    fingerprint = compute_repo_fingerprint(files)
    target_dir = index_dir(cfg.index_root, fingerprint)

    if not files or not _dependencies_available():
        return Tier1SelectionResult(
            repo_fingerprint=fingerprint,
            query=query,
            top_k_stage1=cfg.top_k_stage1,
            top_k_final=cfg.top_k_final,
            items=[],
        )

    if force_rebuild or not _index_exists(target_dir):
        _safe_build_index(repo_root, cfg)

    try:
        vectorizer, matrix, indexed_files = load_index(cfg.index_root, fingerprint)
    except Exception:
        _safe_build_index(repo_root, cfg)
        vectorizer, matrix, indexed_files = load_index(cfg.index_root, fingerprint)

    if not query:
        return Tier1SelectionResult(
            repo_fingerprint=fingerprint,
            query=query,
            top_k_stage1=cfg.top_k_stage1,
            top_k_final=cfg.top_k_final,
            items=[],
        )

    from sklearn.metrics.pairwise import cosine_similarity

    q_vec = vectorizer.transform([query])
    scores = cosine_similarity(q_vec, matrix).ravel()

    ranked_indices = sorted(range(len(scores)), key=lambda idx: scores[idx], reverse=True)
    stage1 = ranked_indices[: cfg.top_k_stage1]
    final_indices = stage1[: cfg.top_k_final]

    items = [
        Tier1SelectionItem(
            id=indexed_files[idx].id,
            rel_path=indexed_files[idx].rel_path,
            abs_path=indexed_files[idx].abs_path,
            score=float(scores[idx]),
            rank=rank + 1,
        )
        for rank, idx in enumerate(final_indices)
    ]

    return Tier1SelectionResult(
        repo_fingerprint=fingerprint,
        query=query,
        top_k_stage1=cfg.top_k_stage1,
        top_k_final=cfg.top_k_final,
        items=items,
    )


def _index_exists(target_dir: Path) -> bool:
    return (
        target_dir / "vectorizer.joblib"
    ).exists() and (target_dir / "matrix.npz").exists() and (target_dir / "files.jsonl").exists()


def _safe_build_index(repo_root: Path, cfg: Tier1Config) -> None:
    try:
        build_index(repo_root, cfg)
    except RuntimeError:
        return


def _dependencies_available() -> bool:
    import importlib.util

    required = ["sklearn", "scipy", "joblib"]
    return all(importlib.util.find_spec(name) is not None for name in required)


def selection_to_dict(result: Tier1SelectionResult) -> dict[str, Any]:
    return asdict(result)
