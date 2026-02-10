from __future__ import annotations

import json
import os
import time

import joblib
import numpy as np
from sklearn.metrics.pairwise import cosine_similarity

from app.repo_scan import scan_repo
from app.tier1.cache import get_cache_dir
from app.tier1.indexer import build_lsa_index
from app.tier1.meta import extract_meta
from app.tier1.types import FileCandidate, Tier1Result


def _index_files_exist(cache_dir: str) -> bool:
    return all(
        os.path.exists(os.path.join(cache_dir, name))
        for name in ["vectorizer.joblib", "svd.joblib", "index.npy", "paths.json"]
    )


def run_tier1(
    repo_root: str,
    goal: str,
    prompt: str,
    constraints: list[str] | str,
    top_k_index: int = 100,
    top_k_final: int = 20,
) -> Tier1Result:
    constraints_text = constraints if isinstance(constraints, str) else "\n".join(constraints)
    query = f"{goal}\n{prompt}\n{constraints_text}".strip()

    cache_dir = get_cache_dir(repo_root)
    start_build = time.perf_counter()
    if not _index_files_exist(cache_dir):
        files = scan_repo(repo_root)
        build_lsa_index(repo_root, files)
    build_ms = (time.perf_counter() - start_build) * 1000.0

    start_search = time.perf_counter()
    vectorizer = joblib.load(os.path.join(cache_dir, "vectorizer.joblib"))
    svd = joblib.load(os.path.join(cache_dir, "svd.joblib"))
    index = np.load(os.path.join(cache_dir, "index.npy"))
    with open(os.path.join(cache_dir, "paths.json"), "r", encoding="utf-8") as handle:
        paths: list[str] = json.load(handle)

    if len(paths) == 0:
        return Tier1Result(
            query=query,
            top_k_index=top_k_index,
            top_k_final=top_k_final,
            candidates=[],
            cache_key=cache_dir,
            build_ms=build_ms,
            search_ms=(time.perf_counter() - start_search) * 1000.0,
        )

    q_tfidf = vectorizer.transform([query])
    q_lsa = svd.transform(q_tfidf)

    sims = cosine_similarity(q_lsa, index)[0]
    idxs = np.argsort(sims)[-top_k_index:][::-1]

    files_by_path = {f["path"]: f for f in scan_repo(repo_root)}
    candidates: list[FileCandidate] = []
    for i in idxs[:top_k_final]:
        path = paths[i]
        file = files_by_path.get(path, {"content": ""})
        candidates.append(
            FileCandidate(
                path=path,
                score=float(sims[i]),
                reasons=["lsa_similarity"],
                meta=extract_meta(file) if file else {},
            )
        )

    search_ms = (time.perf_counter() - start_search) * 1000.0
    return Tier1Result(
        query=query,
        top_k_index=top_k_index,
        top_k_final=top_k_final,
        candidates=candidates,
        cache_key=cache_dir,
        build_ms=build_ms,
        search_ms=search_ms,
    )
