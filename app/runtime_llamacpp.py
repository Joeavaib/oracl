from __future__ import annotations

import json
import socket
import subprocess
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional
import urllib.error
import urllib.request


_RUNTIME_DIR = Path(__file__).resolve().parents[1] / "data" / "runtimes"
_RUNTIME_FILE = _RUNTIME_DIR / "llamacpp.json"
_DEFAULT_PORT_START = 8001
_PORT_SEARCH_LIMIT = 100


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


def _find_free_port(start_port: int = _DEFAULT_PORT_START) -> int:
    for offset in range(_PORT_SEARCH_LIMIT):
        port = start_port + offset
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


def list_instances() -> List[Dict[str, Any]]:
    return _load_instances()


def start_instance(
    role: str,
    model_path: str,
    port: Optional[int] = None,
    extra_args: Optional[List[str]] = None,
) -> Dict[str, Any]:
    if not isinstance(role, str) or not role.strip():
        raise ValueError("role is required")
    if not isinstance(model_path, str) or not model_path.strip():
        raise ValueError("model_path is required")
    runtime_port = port or _find_free_port()
    args = ["llama-server", "--model", model_path, "--port", str(runtime_port)]
    if extra_args:
        args.extend(extra_args)
    process = subprocess.Popen(args)
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
    )
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
                try:
                    subprocess.run(["kill", str(pid)], check=False)
                except OSError:
                    pass
            entry["status"] = "stopped"
            updated = True
            break
    if updated:
        _save_instances(instances)
    return updated


def healthcheck(base_url: str) -> Dict[str, Any]:
    if not isinstance(base_url, str) or not base_url.strip():
        return {"ok": False, "error": "base_url is required"}
    url = base_url.rstrip("/") + "/v1/models"
    request = urllib.request.Request(url, method="GET")
    try:
        with urllib.request.urlopen(request, timeout=5) as response:
            if response.status != 200:
                return {"ok": False, "error": f"status {response.status}"}
            return {"ok": True}
    except (urllib.error.URLError, urllib.error.HTTPError) as exc:
        return {"ok": False, "error": str(exc)}
