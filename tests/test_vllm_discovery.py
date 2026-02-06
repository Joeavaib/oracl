import json

import pytest

pytest.importorskip("fastapi")

from fastapi.testclient import TestClient

from app.main import create_app


def _fake_response(payload: dict):
    class FakeResponse:
        def __init__(self, data: bytes):
            self._data = data

        def read(self):
            return self._data

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

    return FakeResponse(json.dumps(payload).encode("utf-8"))


def test_vllm_discovery_success(monkeypatch):
    def fake_urlopen(request, timeout=10):
        return _fake_response({"data": [{"id": "model-a"}, {"id": "model-b"}]})

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)

    app = create_app()
    client = TestClient(app)

    response = client.get("/api/discovery/vllm_models", params={"base_url": "http://localhost:8000"})
    assert response.status_code == 200
    assert response.json() == {"models": ["model-a", "model-b"]}


def test_vllm_discovery_invalid_base_url():
    app = create_app()
    client = TestClient(app)

    response = client.get("/api/discovery/vllm_models", params={"base_url": "not-a-url"})
    assert response.status_code == 400


def test_vllm_discovery_invalid_payload(monkeypatch):
    def fake_urlopen(request, timeout=10):
        return _fake_response({"bad": "payload"})

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)

    app = create_app()
    client = TestClient(app)

    response = client.get("/api/discovery/vllm_models", params={"base_url": "http://localhost:8000/v1"})
    assert response.status_code == 502


def test_vllm_discovery_ui_partial(monkeypatch):
    def fake_urlopen(request, timeout=10):
        return _fake_response({"data": [{"id": "model-x"}]})

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)

    app = create_app()
    client = TestClient(app)

    response = client.get(
        "/ui/models/discover/vllm", params={"base_url": "http://localhost:8000"}
    )
    assert response.status_code == 200
    assert "datalist" in response.text


def test_vllm_discovery_cache(monkeypatch):
    calls = {"count": 0}

    def fake_urlopen(request, timeout=10):
        calls["count"] += 1
        return _fake_response({"data": [{"id": "model-cache"}]})

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)

    app = create_app()
    client = TestClient(app)

    response = client.get(
        "/api/discovery/vllm_models", params={"base_url": "http://localhost:8000"}
    )
    assert response.status_code == 200
    response = client.get(
        "/api/discovery/vllm_models", params={"base_url": "http://localhost:8000"}
    )
    assert response.status_code == 200
    assert calls["count"] == 1


def test_vllm_discovery_ui_test_ok(monkeypatch):
    def fake_urlopen(request, timeout=10):
        return _fake_response({"data": [{"id": "model-ok"}]})

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)

    app = create_app()
    client = TestClient(app)

    response = client.get(
        "/ui/models/discover/vllm_test", params={"base_url": "http://localhost:8000"}
    )
    assert response.status_code == 200
    assert "OK" in response.text
