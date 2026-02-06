import pytest

pytest.importorskip("fastapi")

from fastapi.testclient import TestClient

from app.main import create_app


def test_ui_smoke():
    app = create_app()
    client = TestClient(app)
    response = client.get("/ui")
    assert response.status_code == 200
