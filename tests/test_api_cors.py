from fastapi.testclient import TestClient

from server.api.main import create_app


def test_cors_allows_local_preview_origin(monkeypatch):
    monkeypatch.delenv("GOKAATRU_CORS_ORIGINS", raising=False)

    app = create_app()

    with TestClient(app) as client:
        response = client.options(
            "/api/health",
            headers={
                "Origin": "http://localhost:4173",
                "Access-Control-Request-Method": "GET",
            },
        )

    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == "http://localhost:4173"


def test_cors_includes_configured_origin(monkeypatch):
    monkeypatch.setenv("GOKAATRU_CORS_ORIGINS", "https://app.example.com")

    app = create_app()

    with TestClient(app) as client:
        response = client.options(
            "/api/health",
            headers={
                "Origin": "https://app.example.com",
                "Access-Control-Request-Method": "GET",
            },
        )

    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == "https://app.example.com"
