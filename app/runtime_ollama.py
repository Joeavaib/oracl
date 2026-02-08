from __future__ import annotations

import json
import urllib.error
import urllib.request
from typing import Any, Dict, List


def _fetch_json(url: str, timeout_s: int = 10) -> Dict[str, Any]:
    request = urllib.request.Request(url, method="GET")
    with urllib.request.urlopen(request, timeout=timeout_s) as response:
        return json.loads(response.read().decode("utf-8"))


def healthcheck(base_url: str) -> Dict[str, Any]:
    if not isinstance(base_url, str) or not base_url.strip():
        return {"ok": False, "error": "base_url is required"}
    base = base_url.rstrip("/")
    try:
        payload = _fetch_json(f"{base}/api/version", timeout_s=5)
        if isinstance(payload.get("version"), str):
            return {"ok": True, "mode": "ollama"}
        return {"ok": False, "mode": "ollama", "error": "Missing version"}
    except (urllib.error.URLError, urllib.error.HTTPError, json.JSONDecodeError, ValueError) as exc:
        try:
            payload = _fetch_json(f"{base}/v1/models", timeout_s=5)
            data = payload.get("data")
            if isinstance(data, list):
                return {"ok": True, "mode": "openai"}
            return {"ok": False, "mode": "openai", "error": "Invalid models response"}
        except (urllib.error.URLError, urllib.error.HTTPError, json.JSONDecodeError, ValueError):
            return {"ok": False, "mode": "ollama", "error": str(exc)}


def list_models(base_url: str) -> List[str]:
    if not isinstance(base_url, str) or not base_url.strip():
        raise ValueError("base_url is required")
    base = base_url.rstrip("/")
    try:
        payload = _fetch_json(f"{base}/api/tags")
        models = payload.get("models")
        if not isinstance(models, list):
            raise ValueError("Invalid ollama discovery response")
        return [
            item["name"]
            for item in models
            if isinstance(item, dict) and isinstance(item.get("name"), str)
        ]
    except (urllib.error.URLError, urllib.error.HTTPError, json.JSONDecodeError, ValueError):
        payload = _fetch_json(f"{base}/v1/models")
        data = payload.get("data")
        if not isinstance(data, list):
            raise ValueError("Invalid openai discovery response")
        return [
            item["id"]
            for item in data
            if isinstance(item, dict) and isinstance(item.get("id"), str)
        ]
