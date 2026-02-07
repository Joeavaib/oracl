import json

import pytest

from app import runtime_llamacpp


class FakeProcess:
    def __init__(self, pid: int):
        self.pid = pid


def _configure_runtime_paths(tmp_path, monkeypatch):
    runtime_dir = tmp_path / "runtimes"
    runtime_file = runtime_dir / "llamacpp.json"
    monkeypatch.setattr(runtime_llamacpp, "_RUNTIME_DIR", runtime_dir)
    monkeypatch.setattr(runtime_llamacpp, "_RUNTIME_FILE", runtime_file)
    return runtime_file


def test_start_list_stop_instance(monkeypatch, tmp_path):
    _configure_runtime_paths(tmp_path, monkeypatch)

    def fake_popen(args):
        assert args[:3] == ["llama-server", "--model", "model.gguf"]
        assert "--port" in args
        return FakeProcess(pid=4242)

    def fake_run(args, check=False):
        assert args == ["kill", "4242"]

    monkeypatch.setattr(runtime_llamacpp.subprocess, "Popen", fake_popen)
    monkeypatch.setattr(runtime_llamacpp.subprocess, "run", fake_run)

    instance = runtime_llamacpp.start_instance(
        role="validator",
        model_path="model.gguf",
        port=9001,
    )
    assert instance["pid"] == 4242
    assert instance["port"] == 9001
    assert instance["base_url"] == "http://127.0.0.1:9001"

    listed = runtime_llamacpp.list_instances()
    assert len(listed) == 1
    assert listed[0]["id"] == instance["id"]

    stopped = runtime_llamacpp.stop_instance(instance["id"])
    assert stopped is True
    updated = runtime_llamacpp.list_instances()
    assert updated[0]["status"] == "stopped"

    saved = json.loads(
        (tmp_path / "runtimes" / "llamacpp.json").read_text(encoding="utf-8")
    )
    assert saved[0]["status"] == "stopped"


def test_stop_missing_instance(monkeypatch, tmp_path):
    _configure_runtime_paths(tmp_path, monkeypatch)
    (tmp_path / "runtimes").mkdir(parents=True, exist_ok=True)
    (tmp_path / "runtimes" / "llamacpp.json").write_text("[]", encoding="utf-8")

    assert runtime_llamacpp.stop_instance("missing") is False
