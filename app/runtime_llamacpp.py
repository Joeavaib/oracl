from __future__ import annotations

import json
import os
import shutil
import signal
import socket
import subprocess
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional


_RUNTIME_DIR = Path(__file__).resolve().parents[1] / "data" / "runtimes"
_RUNTIME_FILE = _RUNTIME_DIR / "llamacpp.json"
_DEFAULT_PORT_START = 18000
_DEFAULT_PORT_LIMIT = 200
_DEFAULT_HEALTHCHECK_TIMEOUT_S = 20
_DEFAULT_HEALTHCHECK_INTERVAL_S = 0.5
_DEFAULT_STOP_TIMEOUT_S = 5
_DEFAULT_BIN_NAME = "llama-server"


@dataclass
class RuntimeInstance:
    id: str
    role: str
    model_path: str
    port: int
    pid: int
    base_url: str
    started_at: str
    status: str
    extra_args: List[str]
    log_path: Optional[str] = None

    def as_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "role": self.role,
            "model_path": self.model_path,
            "port": self.port,
            "pid": self.pid,
            "base_url": self.base_url,
            "started_at": self.started_at,
            "status": self.status,
            "extra_args": self.extra_args,
            "log_path": self.log_path,
        }


def _ensure_runtime_file() -> None:
    _RUNTIME_DIR.mkdir(parents=True, exist_ok=True)
    if not _RUNTIME_FILE.exists():
        _RUNTIME_FILE.write_text("[]", encoding="utf-8")


def _load_instances() -> List[Dict[str, Any]]:
    _ensure_runtime_file()
    return json.loads(_RUNTIME_FILE.read_text(encoding="utf-8"))


def _save_instances(instances: List[Dict[str, Any]]) -> None:
    _ensure_runtime_file()
    _RUNTIME_FILE.write_text(
        json.dumps(instances, ensure_ascii=False, indent=2), encoding="utf-8"
    )


def _read_env_int(key: str, default: int) -> int:
    raw = os.getenv(key)
    if raw is None or not raw.strip():
        return default
    try:
        value = int(raw)
    except ValueError:
        return default
    return value if value > 0 else default


def _port_candidates() -> List[int]:
    start = _read_env_int("LLAMA_PORT_START", _DEFAULT_PORT_START)
    limit = _read_env_int("LLAMA_PORT_LIMIT", _DEFAULT_PORT_LIMIT)
    return list(range(start, start + limit))


def _find_free_port() -> int:
    for port in _port_candidates():
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            try:
                sock.bind(("127.0.0.1", port))
            except OSError:
                continue
            return port
    raise RuntimeError("No free port available for llama.cpp runtime")


def _generate_instance_id(role: str, port: int) -> str:
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S")
    return f"{role}-{port}-{timestamp}"


def _resolve_binary_path(binary_path: Optional[str]) -> str:
    env_value = os.getenv("LLAMA_SERVER_BIN", _DEFAULT_BIN_NAME).strip()
    candidate_value = binary_path.strip() if binary_path else env_value
    candidate = Path(candidate_value).expanduser()
    if candidate.is_absolute() or "/" in candidate_value:
        if candidate.exists():
            return str(candidate)
        raise RuntimeError(f"llama-server not found: set LLAMA_SERVER_BIN to {candidate_value}")
    resolved = shutil.which(candidate_value)
    if resolved:
        return resolved
    raise RuntimeError(f"llama-server not found: set LLAMA_SERVER_BIN to {candidate_value}")


def _log_path(role: str, port: int) -> Path:
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S")
    return _RUNTIME_DIR / f"llamacpp-{role}-{port}-{timestamp}.log"


def _pid_is_running(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except OSError:
        return False
    return True


def _stop_pid(pid: int, timeout_s: int = _DEFAULT_STOP_TIMEOUT_S) -> None:
    try:
        os.kill(pid, signal.SIGTERM)
    except OSError:
        return
    deadline = time.time() + timeout_s
    while time.time() < deadline:
        if not _pid_is_running(pid):
            return
        time.sleep(0.2)
    try:
        os.kill(pid, signal.SIGKILL)
    except OSError:
        return
    deadline = time.time() + timeout_s
    while time.time() < deadline:
        if not _pid_is_running(pid):
            return
        time.sleep(0.2)


def list_instances() -> List[Dict[str, Any]]:
    return _load_instances()


def start_instance(
    role: str,
    model_path: str,
    port: Optional[int] = None,
    extra_args: Optional[List[str]] = None,
    binary_path: Optional[str] = None,
) -> Dict[str, Any]:
    if not isinstance(role, str) or not role.strip():
        raise ValueError("role is required")
    if not isinstance(model_path, str) or not model_path.strip():
        raise ValueError("model_path is required")
    runtime_port = port or _find_free_port()
    bin_path = _resolve_binary_path(binary_path)
    args = [bin_path, "--model", model_path, "--port", str(runtime_port)]
    if extra_args:
        args.extend(extra_args)
    log_path = _log_path(role, runtime_port)
    _RUNTIME_DIR.mkdir(parents=True, exist_ok=True)
    log_handle = log_path.open("a", encoding="utf-8")
    process = subprocess.Popen(
        args,
        stdout=log_handle,
        stderr=log_handle,
        start_new_session=True,
    )
    started_at = datetime.now(timezone.utc).isoformat()
    instance = RuntimeInstance(
        id=_generate_instance_id(role, runtime_port),
        role=role,
        model_path=model_path,
        port=runtime_port,
        pid=process.pid,
        base_url=f"http://127.0.0.1:{runtime_port}",
        started_at=started_at,
        status="running",
        extra_args=list(extra_args or []),
        log_path=str(log_path),
    )
    health = wait_for_healthcheck(instance.base_url)
    if not health.get("ok"):
        _stop_pid(process.pid)
        raise RuntimeError(f"llama.cpp runtime failed healthcheck: {health.get('error')}")
    instances = _load_instances()
    instances.append(instance.as_dict())
    _save_instances(instances)
    return instance.as_dict()


def stop_instance(instance_id: str) -> bool:
    if not isinstance(instance_id, str) or not instance_id.strip():
        raise ValueError("instance_id is required")
    instances = _load_instances()
    updated = False
    for entry in instances:
        if entry.get("id") == instance_id and entry.get("status") == "running":
            pid = entry.get("pid")
            if isinstance(pid, int):
                _stop_pid(pid)
            entry["status"] = "stopped"
            updated = True
            break
    if updated:
        _save_instances(instances)
    return updated


def fetch_models(base_url: str, timeout_s: int = 5) -> List[str]:
    url = base_url.rstrip("/") + "/v1/models"
    request = urllib.request.Request(url, method="GET")
    with urllib.request.urlopen(request, timeout=timeout_s) as response:
        payload = json.loads(response.read().decode("utf-8"))
    data = payload.get("data")
    if not isinstance(data, list):
        raise ValueError("Invalid discovery response")
    return [
        item["id"]
        for item in data
        if isinstance(item, dict) and isinstance(item.get("id"), str)
    ]


def healthcheck(base_url: str) -> Dict[str, Any]:
    if not isinstance(base_url, str) or not base_url.strip():
        return {"ok": False, "error": "base_url is required"}
    try:
        models = fetch_models(base_url, timeout_s=5)
    except (urllib.error.URLError, urllib.error.HTTPError, ValueError, json.JSONDecodeError) as exc:
        return {"ok": False, "error": str(exc)}
    return {"ok": True, "models": models}


def wait_for_healthcheck(
    base_url: str,
    timeout_s: int = _DEFAULT_HEALTHCHECK_TIMEOUT_S,
    interval_s: float = _DEFAULT_HEALTHCHECK_INTERVAL_S,
) -> Dict[str, Any]:
    deadline = time.time() + timeout_s
    last_error: Optional[str] = None
    while time.time() < deadline:
        result = healthcheck(base_url)
        if result.get("ok"):
            return result
        last_error = result.get("error")
        time.sleep(interval_s)
    return {"ok": False, "error": last_error or "Healthcheck timeout"}


def _select_model_name(models: List[str], fallback: Optional[str] = None) -> str:
    for model in models:
        if isinstance(model, str) and model.strip():
            return model
    if fallback and isinstance(fallback, str) and fallback.strip():
        return fallback
    return "llama.cpp"


def ensure_runtime(model: Dict[str, Any], role: str) -> Dict[str, Any]:
    base_url = model.get("base_url")
    model_name = model.get("model_name")
    if isinstance(base_url, str) and base_url.strip():
        health = healthcheck(base_url)
        if health.get("ok"):
            return {
                "base_url": base_url,
                "model_name": _select_model_name(health.get("models", []), model_name),
                "runtime": None,
            }
    model_path = model.get("model_path")
    if not isinstance(model_path, str) or not model_path.strip():
        raise RuntimeError("model_path is required to start llama.cpp runtime")
    instance = start_instance(role=role, model_path=model_path)
    health = wait_for_healthcheck(instance["base_url"])
    return {
        "base_url": instance["base_url"],
        "model_name": _select_model_name(health.get("models", []), model_name),
        "runtime": instance,
    }
