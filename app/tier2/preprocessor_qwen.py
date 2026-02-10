from __future__ import annotations

import ast
import json
import re
from pathlib import Path
from typing import Dict, List, Sequence, Tuple

from app.llm_client import chat_completions
from app.tier2.config import Tier2Config
from app.tier2.prompts import build_qwen_preprocessor_prompt
from app.tier2.types import Tier2CompressionStats, Tier2ContextBundle, Tier2FileContext


ANCHOR_LINES = 40


def _load_with_limits(repo_root: Path, selected_paths: Sequence[str], cfg: Tier2Config) -> Dict[str, str]:
    loaded: Dict[str, str] = {}
    consumed = 0
    for rel_path in selected_paths:
        path = (repo_root / rel_path).resolve()
        if not path.exists() or not path.is_file():
            continue
        raw = path.read_bytes()[: cfg.max_bytes_per_file]
        if consumed + len(raw) > cfg.max_total_bytes:
            remaining = max(cfg.max_total_bytes - consumed, 0)
            raw = raw[:remaining]
        if not raw:
            break
        consumed += len(raw)
        loaded[rel_path] = raw.decode("utf-8", errors="replace")
        if consumed >= cfg.max_total_bytes:
            break
    return loaded


def _extract_signatures(path: str, content: str) -> Tier2FileContext:
    imports = re.findall(r"^(?:from\s+.+\s+import\s+.+|import\s+.+)$", content, flags=re.MULTILINE)
    classes = re.findall(r"^class\s+(\w+)", content, flags=re.MULTILINE)
    functions = re.findall(r"^def\s+(\w+\([^)]*\))", content, flags=re.MULTILINE)

    notes: List[str] = []
    for marker in ("TODO", "FIXME", "HACK"):
        if marker in content:
            notes.append(f"Contains {marker} markers")

    purpose = "Code file summary"
    key_symbols = [*classes[:3], *[item.split("(")[0] for item in functions[:4]]]

    try:
        module = ast.parse(content)
        doc = ast.get_docstring(module)
        if doc:
            purpose = doc.strip().splitlines()[0][:160]
    except Exception:
        pass

    lines = content.splitlines()
    if len(lines) > ANCHOR_LINES * 2:
        notes.append("Anchored by first/last 40 lines in preprocessing")

    return Tier2FileContext(
        path=path,
        purpose=purpose,
        key_symbols=key_symbols,
        imports=imports[:10],
        classes=classes[:10],
        functions=functions[:12],
        notes=notes,
    )


def deterministic_signature_bundle(repo_root: Path, selected_paths: Sequence[str], cfg: Tier2Config) -> Tier2ContextBundle:
    loaded = _load_with_limits(repo_root, selected_paths, cfg)
    files = [_extract_signatures(path, content) for path, content in loaded.items()]
    overall = "Deterministic Tier-2 bundle based on imports/signatures/classes without LLM enrichment."
    output_bytes = len(json.dumps([file.__dict__ for file in files], ensure_ascii=False))
    input_bytes = sum(len(content.encode("utf-8")) for content in loaded.values())
    ratio = (input_bytes / output_bytes) if output_bytes else 1.0
    return Tier2ContextBundle(
        overall_summary=overall,
        files=files,
        stats=Tier2CompressionStats(
            input_bytes=input_bytes,
            output_bytes=output_bytes,
            compression_ratio_est=round(ratio, 3),
        ),
    )


def _to_prompt_text(loaded: Dict[str, str]) -> str:
    chunks: List[str] = []
    for path, content in loaded.items():
        lines = content.splitlines()
        anchor = lines
        if len(lines) > ANCHOR_LINES * 2:
            anchor = lines[:ANCHOR_LINES] + ["...<snip>..."] + lines[-ANCHOR_LINES:]
        chunks.append(f"## {path}\n" + "\n".join(anchor))
    return "\n\n".join(chunks)


def tier2_compress_context(
    repo_root: Path, query: str, selected_paths: Sequence[str], cfg: Tier2Config
) -> Tuple[Tier2ContextBundle, bool]:
    if not selected_paths:
        empty = Tier2ContextBundle(
            overall_summary="No files selected.",
            files=[],
            stats=Tier2CompressionStats(input_bytes=0, output_bytes=0, compression_ratio_est=1.0),
        )
        return empty, True

    loaded = _load_with_limits(repo_root, selected_paths, cfg)
    if not loaded:
        return deterministic_signature_bundle(repo_root, selected_paths, cfg), True

    prompt = build_qwen_preprocessor_prompt(query, _to_prompt_text(loaded))

    try:
        content = chat_completions(
            base_url=cfg.qwen_base_url,
            model=cfg.qwen_model_id,
            messages=[{"role": "user", "content": prompt}],
        )
        parsed = json.loads(content)
        files_raw = parsed.get("files", [])
        file_context = [
            Tier2FileContext(
                path=str(item.get("path", "")),
                purpose=str(item.get("purpose", "")),
                key_symbols=[str(v) for v in item.get("key_symbols", [])],
                imports=[str(v) for v in item.get("imports", [])],
                classes=[str(v) for v in item.get("classes", [])],
                functions=[str(v) for v in item.get("functions", [])],
                notes=[str(v) for v in item.get("notes", [])],
            )
            for item in files_raw
            if str(item.get("path", "")) in selected_paths
        ]
        if not file_context:
            return deterministic_signature_bundle(repo_root, selected_paths, cfg), True
        output_bytes = len(content.encode("utf-8"))
        input_bytes = sum(len(value.encode("utf-8")) for value in loaded.values())
        ratio = (input_bytes / output_bytes) if output_bytes else 1.0
        bundle = Tier2ContextBundle(
            overall_summary=str(parsed.get("overall_summary", "")),
            files=file_context,
            stats=Tier2CompressionStats(
                input_bytes=input_bytes,
                output_bytes=output_bytes,
                compression_ratio_est=round(ratio, 3),
            ),
        )
        return bundle, False
    except Exception:
        return deterministic_signature_bundle(repo_root, selected_paths, cfg), True
