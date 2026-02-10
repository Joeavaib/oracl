from __future__ import annotations

import json
from typing import Any, Dict, List, Optional
from urllib import request


class LLMClientError(RuntimeError):
    """Raised when an upstream LLM request fails."""


def chat_completions(
    *,
    base_url: str,
    model: str,
    messages: List[Dict[str, str]],
    timeout_s: float = 20.0,
    temperature: float = 0.0,
) -> str:
    """Minimal OpenAI-compatible chat completion helper.

    Returns the first assistant message content.
    """

    payload = {
        "model": model,
        "messages": messages,
        "temperature": temperature,
    }
    body = json.dumps(payload).encode("utf-8")
    endpoint = base_url.rstrip("/") + "/chat/completions"
    req = request.Request(
        endpoint,
        data=body,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with request.urlopen(req, timeout=timeout_s) as response:
            raw = response.read().decode("utf-8", errors="replace")
    except Exception as exc:  # pragma: no cover - network runtime path
        raise LLMClientError(str(exc)) from exc

    try:
        parsed: Dict[str, Any] = json.loads(raw)
        return str(parsed["choices"][0]["message"]["content"])
    except Exception as exc:  # pragma: no cover - runtime parse guard
        raise LLMClientError("Invalid completion payload") from exc
