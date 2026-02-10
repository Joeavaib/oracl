from __future__ import annotations

import json
import re
from typing import Iterable, List, Sequence

from app.llm_client import chat_completions
from app.tier2.config import Tier2Config
from app.tier2.prompts import build_phi3_validator_prompt
from app.tier2.types import Tier1Candidate


def _cheap_hints(preview: str) -> List[str]:
    hints: List[str] = []
    for pattern in (r"^import\s+.+", r"^from\s+.+\simport\s+.+", r"^class\s+\w+", r"^def\s+\w+\("):
        found = re.findall(pattern, preview, flags=re.MULTILINE)
        hints.extend(found[:3])
    return hints[:8]


def _render_candidates(candidates: Sequence[Tier1Candidate]) -> str:
    lines: List[str] = []
    for item in candidates:
        hints = _cheap_hints(item.preview)
        hint_txt = f" hints={hints}" if hints else ""
        lines.append(
            f"- rel_path={item.rel_path} rank={item.rank} score={item.score:.4f}{hint_txt}"
        )
    return "\n".join(lines)


def _fallback_csv_paths(text: str) -> List[str]:
    cleaned = text.strip().strip("[]")
    if not cleaned:
        return []
    return [segment.strip().strip('"\'') for segment in cleaned.split(",") if segment.strip()]


def _sanitize_selection(
    selected_paths: Iterable[str], candidates: Sequence[Tier1Candidate], max_selected_files: int
) -> List[str]:
    allowed = {item.rel_path for item in candidates}
    result: List[str] = []
    for path in selected_paths:
        if path in allowed and path not in result:
            result.append(path)
        if len(result) >= max_selected_files:
            break
    return result


def tier2_validate_files(query: str, candidates: Sequence[Tier1Candidate], cfg: Tier2Config) -> tuple[List[str], str, bool]:
    if not candidates:
        return [], "No Tier-1 candidates available.", True

    prompt = build_phi3_validator_prompt(query, _render_candidates(candidates))
    fallback = [item.rel_path for item in sorted(candidates, key=lambda x: x.rank)[: cfg.max_selected_files]]

    try:
        content = chat_completions(
            base_url=cfg.phi3_base_url,
            model=cfg.phi3_model_id,
            messages=[{"role": "user", "content": prompt}],
        )
        try:
            parsed = json.loads(content)
            raw_paths = parsed.get("selected_paths", [])
            reason = str(parsed.get("why", ""))
        except json.JSONDecodeError:
            raw_paths = _fallback_csv_paths(content)
            reason = "Recovered from non-JSON response"

        selected = _sanitize_selection(raw_paths, candidates, cfg.max_selected_files)
        if not selected:
            return fallback, "Phi-3 selection invalid/empty; used Tier-1 top5 fallback.", True
        return selected, reason, False
    except Exception:
        return fallback, "Phi-3 unavailable; used Tier-1 top5 fallback.", True
