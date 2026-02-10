from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Callable, Iterable, List, Optional, Sequence, Tuple

from app.tier2.config import Tier2Config, load_tier2_config
from app.tier2.preprocessor_qwen import tier2_compress_context
from app.tier2.types import (
    Tier1Candidate,
    Tier2CompressionStats,
    Tier2ContextBundle,
    Tier2FileContext,
    Tier2ModelInfo,
    Tier2SelectionResult,
)
from app.tier2.validator_phi3 import tier2_validate_files

EventFn = Optional[Callable[[str, str], None]]


def _candidate_hash(candidates: Sequence[Tier1Candidate]) -> str:
    payload = "|".join(item.rel_path for item in candidates)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:16]


def _query_hash(query: str) -> str:
    return hashlib.sha256(query.encode("utf-8")).hexdigest()[:16]


def _repo_fingerprint(repo_root: Path) -> str:
    git_head = repo_root / ".git" / "HEAD"
    if git_head.exists():
        return git_head.read_text(encoding="utf-8", errors="replace").strip()
    return str(int(repo_root.stat().st_mtime))


def _cache_key(repo_root: Path, query: str, candidates: Sequence[Tier1Candidate]) -> str:
    seed = f"{_repo_fingerprint(repo_root)}:{_query_hash(query)}:{_candidate_hash(candidates)}"
    return hashlib.sha256(seed.encode("utf-8")).hexdigest()


def _cache_paths(cache_dir: Path, key: str) -> Tuple[Path, Path]:
    return cache_dir / f"{key}.selection.json", cache_dir / f"{key}.context.json"


def run_tier2(
    repo_root: Path,
    query: str,
    tier1_items: Sequence[Tier1Candidate],
    cfg: Optional[Tier2Config] = None,
    cache_dir: Optional[Path] = None,
    event_cb: EventFn = None,
) -> Tuple[Tier2SelectionResult, Tier2ContextBundle, bool]:
    cfg = cfg or load_tier2_config()
    cache_base = cache_dir or (repo_root / ".oracl_cache" / "tier2")
    cache_base.mkdir(parents=True, exist_ok=True)

    key = _cache_key(repo_root, query, tier1_items)
    sel_cache, ctx_cache = _cache_paths(cache_base, key)

    if sel_cache.exists() and ctx_cache.exists():
        selection_payload = json.loads(sel_cache.read_text(encoding="utf-8"))
        context_payload = json.loads(ctx_cache.read_text(encoding="utf-8"))
        selection = Tier2SelectionResult(
            query=selection_payload.get("query", query),
            candidates=selection_payload.get("candidates", []),
            selected_paths=selection_payload.get("selected_paths", []),
            reason_brief=selection_payload.get("reason_brief", ""),
            model=Tier2ModelInfo(**selection_payload.get("model", {})),
        )
        context = Tier2ContextBundle(
            overall_summary=context_payload.get("overall_summary", ""),
            files=[Tier2FileContext(**item) for item in context_payload.get("files", [])],
            stats=Tier2CompressionStats(
                **context_payload.get("stats", {"input_bytes": 0, "output_bytes": 0, "compression_ratio_est": 1.0})
            ),
        )
        return selection, context, True

    if event_cb:
        event_cb("TIER2_STARTED", "Tier-2 pipeline started")

    selected_paths, reason, validator_fallback = tier2_validate_files(query, tier1_items, cfg)
    if event_cb:
        event_cb(
            "TIER2_VALIDATED",
            "Tier-2 validator selected files" + (" (fallback)" if validator_fallback else ""),
        )

    context, preprocessor_fallback = tier2_compress_context(repo_root, query, selected_paths, cfg)
    if event_cb:
        event_cb(
            "TIER2_COMPRESSED",
            "Tier-2 context preprocessed" + (" (fallback)" if preprocessor_fallback else ""),
        )

    if validator_fallback or preprocessor_fallback:
        if event_cb:
            event_cb("TIER2_FALLBACK_USED", "Tier-2 fallback was applied")

    selection = Tier2SelectionResult(
        query=query,
        candidates=[{"rel_path": item.rel_path, "score": item.score, "rank": item.rank} for item in tier1_items],
        selected_paths=selected_paths[: cfg.max_selected_files],
        reason_brief=reason,
        model=Tier2ModelInfo(
            model_id=cfg.phi3_model_id,
            model_path=cfg.phi3_model_path,
            base_url=cfg.phi3_base_url,
        ),
    )

    sel_cache.write_text(json.dumps(selection.to_dict(), ensure_ascii=False, indent=2), encoding="utf-8")
    ctx_cache.write_text(json.dumps(context.to_dict(), ensure_ascii=False, indent=2), encoding="utf-8")
    return selection, context, False
