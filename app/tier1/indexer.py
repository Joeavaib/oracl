from __future__ import annotations

import json
from dataclasses import asdict
from pathlib import Path
from typing import Any

from app.tier1.preprocess import preprocess_docs
from app.tier1.scanner import scan_repo
from app.tier1.types import Tier1Config, Tier1FileMeta


def compute_repo_fingerprint(files: list[Tier1FileMeta]) -> str:
    lines = [f"{file.rel_path}:{file.sha1}" for file in sorted(files, key=lambda item: item.rel_path)]
    payload = "\n".join(lines) + "\n"
    return _sha1_text(payload)


def index_dir(index_root: Path, fingerprint: str) -> Path:
    return index_root / fingerprint


def build_index(repo_root: Path, cfg: Tier1Config) -> str:
    files = scan_repo(repo_root, cfg)
    fingerprint = compute_repo_fingerprint(files)
    target_dir = index_dir(cfg.index_root, fingerprint)
    target_dir.mkdir(parents=True, exist_ok=True)

    documents, kept_files = preprocess_docs(files)

    _require_dependencies()
    from sklearn.feature_extraction.text import TfidfVectorizer
    from scipy import sparse
    import joblib

    vectorizer = TfidfVectorizer(
        max_features=cfg.max_features,
        ngram_range=cfg.ngram_range,
        min_df=cfg.min_df,
        max_df=cfg.max_df,
    )
    if documents:
        matrix = vectorizer.fit_transform(documents)
    else:
        vectorizer = vectorizer.fit(["placeholder"])
        matrix = sparse.csr_matrix((0, len(vectorizer.vocabulary_)))

    joblib.dump(vectorizer, target_dir / "vectorizer.joblib")
    sparse.save_npz(target_dir / "matrix.npz", matrix)
    _write_files_jsonl(target_dir / "files.jsonl", kept_files)
    _write_json(target_dir / "config.json", _config_payload(cfg))

    return fingerprint


def load_index(index_root: Path, fingerprint: str) -> tuple[Any, Any, list[Tier1FileMeta]]:
    _require_dependencies()
    from scipy import sparse
    import joblib

    target_dir = index_dir(index_root, fingerprint)
    vectorizer = joblib.load(target_dir / "vectorizer.joblib")
    matrix = sparse.load_npz(target_dir / "matrix.npz")
    files = _read_files_jsonl(target_dir / "files.jsonl")
    return vectorizer, matrix, files


def _require_dependencies() -> None:
    import importlib.util

    required = ["sklearn", "scipy", "joblib"]
    missing = [name for name in required if importlib.util.find_spec(name) is None]
    if missing:
        raise RuntimeError(f"Missing Tier1 dependencies: {', '.join(missing)}")


def _sha1_text(payload: str) -> str:
    import hashlib

    digest = hashlib.sha1()
    digest.update(payload.encode("utf-8"))
    return digest.hexdigest()


def _write_files_jsonl(path: Path, files: list[Tier1FileMeta]) -> None:
    with path.open("w", encoding="utf-8") as handle:
        for file in files:
            payload = asdict(file)
            meta = {
                "size": file.size,
                "mtime": file.mtime,
                "lang": file.lang,
                "loc": file.loc,
            }
            payload["meta"] = meta
            handle.write(json.dumps(payload, ensure_ascii=False) + "\n")


def _read_files_jsonl(path: Path) -> list[Tier1FileMeta]:
    files: list[Tier1FileMeta] = []
    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            payload = json.loads(line)
            files.append(
                Tier1FileMeta(
                    id=int(payload["id"]),
                    rel_path=str(payload["rel_path"]),
                    abs_path=str(payload["abs_path"]),
                    sha1=str(payload["sha1"]),
                    size=int(payload.get("size", payload.get("meta", {}).get("size", 0))),
                    mtime=float(payload.get("mtime", payload.get("meta", {}).get("mtime", 0.0))),
                    lang=str(payload.get("lang", payload.get("meta", {}).get("lang", "text"))),
                    loc=int(payload.get("loc", payload.get("meta", {}).get("loc", 0))),
                )
            )
    return files


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    with path.open("w", encoding="utf-8") as handle:
        json.dump(payload, handle, ensure_ascii=False, indent=2, default=str)


def _config_payload(cfg: Tier1Config) -> dict[str, Any]:
    return {
        "include_exts": sorted(cfg.include_exts),
        "exclude_dirs": sorted(cfg.exclude_dirs),
        "max_features": cfg.max_features,
        "ngram_range": list(cfg.ngram_range),
        "min_df": cfg.min_df,
        "max_df": cfg.max_df,
        "top_k_stage1": cfg.top_k_stage1,
        "top_k_final": cfg.top_k_final,
    }


def normalize_tokens(text: str) -> str:
    import re

    tokens = re.findall(r"\b\w+\b", text.lower())
    return " ".join(tokens)


def file_feature_text(file: dict[str, str]) -> str:
    import os
    import re

    code = file["content"]
    tokens: list[str] = []

    path = file["path"]
    for part in os.path.splitext(os.path.basename(path))[0].split("_"):
        tokens.append(part)

    tokens.extend(re.findall(r"def\s+(\w+)", code))
    tokens.extend(re.findall(r"class\s+(\w+)", code))
    tokens.extend(re.findall(r"import\s+(\w+)", code))

    for line in code.splitlines()[:20]:
        if "#" in line:
            tokens.extend(re.findall(r"\b\w+\b", line))

    return normalize_tokens(" ".join(tokens))


def build_lsa_index(repo_root: str, files: list[dict[str, str]]) -> str:
    import json
    import os

    import joblib
    import numpy as np
    from sklearn.decomposition import TruncatedSVD
    from sklearn.feature_extraction.text import TfidfVectorizer

    from app.tier1.cache import get_cache_dir

    cache_dir = get_cache_dir(repo_root)
    corpus = [file_feature_text(file) for file in files]

    if not corpus:
        vectorizer = TfidfVectorizer(token_pattern=r"\b\w+\b")
        tfidf = vectorizer.fit_transform(["placeholder"])
        svd = TruncatedSVD(n_components=1)
        index_matrix = np.zeros((0, 1), dtype=float)
        svd.fit(tfidf)
        joblib.dump(vectorizer, os.path.join(cache_dir, "vectorizer.joblib"))
        joblib.dump(svd, os.path.join(cache_dir, "svd.joblib"))
        np.save(os.path.join(cache_dir, "index.npy"), index_matrix)
        with open(os.path.join(cache_dir, "paths.json"), "w", encoding="utf-8") as handle:
            json.dump([], handle)
        return cache_dir

    vectorizer = TfidfVectorizer(
        max_features=10000,
        ngram_range=(1, 3),
        token_pattern=r"\b\w+\b",
    )
    tfidf = vectorizer.fit_transform(corpus)

    n_components = max(1, min(256, tfidf.shape[0] - 1 if tfidf.shape[0] > 1 else 1, tfidf.shape[1]))
    svd = TruncatedSVD(n_components=n_components)
    index_matrix = svd.fit_transform(tfidf)

    joblib.dump(vectorizer, os.path.join(cache_dir, "vectorizer.joblib"))
    joblib.dump(svd, os.path.join(cache_dir, "svd.joblib"))
    np.save(os.path.join(cache_dir, "index.npy"), index_matrix)
    with open(os.path.join(cache_dir, "paths.json"), "w", encoding="utf-8") as handle:
        json.dump([file["path"] for file in files], handle)

    return cache_dir
