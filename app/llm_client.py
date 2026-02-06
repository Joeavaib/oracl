from __future__ import annotations

import json
import urllib.error
import urllib.request
from typing import Any, Dict


class LLMClientError(RuntimeError):
    pass


def chat_completions(
    *,
    base_url: str,
    payload: Dict[str, Any],
    timeout_s: int = 30,
) -> Dict[str, Any]:
    if not base_url:
        raise LLMClientError("base_url is required")
    url = base_url.rstrip("/") + "/v1/chat/completions"
    data = json.dumps(payload).encode("utf-8")
    request = urllib.request.Request(
        url,
        data=data,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout_s) as response:
            body = response.read().decode("utf-8")
    except urllib.error.HTTPError as exc:
        raise LLMClientError(f"LLM request failed with status {exc.code}") from exc
    except urllib.error.URLError as exc:
        raise LLMClientError(f"LLM request failed: {exc.reason}") from exc
    try:
        return json.loads(body)
    except json.JSONDecodeError as exc:
        raise LLMClientError("LLM response was not valid JSON") from exc
