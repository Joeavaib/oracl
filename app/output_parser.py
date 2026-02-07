from __future__ import annotations

import json
from typing import Any, Dict


def _find_json_bounds(text: str) -> tuple[int, int]:
    start = text.find("{")
    if start == -1:
        return -1, -1
    depth = 0
    in_string = False
    escape = False
    for index in range(start, len(text)):
        char = text[index]
        if in_string:
            if escape:
                escape = False
            elif char == "\\":
                escape = True
            elif char == '"':
                in_string = False
            continue
        if char == '"':
            in_string = True
            continue
        if char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0:
                return start, index + 1
    return -1, -1


def extract_json(response_text: str) -> Dict[str, Any]:
    start, end = _find_json_bounds(response_text)
    if start == -1 or end == -1:
        raise ValueError("No JSON object found in response text")
    snippet = response_text[start:end]
    parsed = json.loads(snippet)
    if not isinstance(parsed, dict):
        raise ValueError("Extracted JSON is not an object")
    return parsed
