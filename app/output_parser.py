from __future__ import annotations

import json
from typing import Any, Dict

from app.tmps.compiler import compile_tmps


def extract_json(response_text: str) -> Dict[str, Any]:
    compiled = compile_tmps(response_text)
    if compiled.issues:
        hint = "; ".join(issue.message for issue in compiled.issues)
        raise ValueError(f"TMP-S compile failed: {hint}")
    for record in compiled.outputs:
        if not record.fields:
            continue
        payload = record.fields[2].strip()
        if payload:
            parsed = json.loads(payload)
            if not isinstance(parsed, dict):
                raise ValueError("Parsed TMP-S json payload is not an object")
            return parsed
    raise ValueError("No TMP-S json payload found in O lines")
