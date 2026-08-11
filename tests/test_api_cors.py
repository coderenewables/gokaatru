from fastapi.testclient import TestClient

from server.api.main import create_app, _get_allowed_origins


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


class TestConfiguredOriginsReplaceDefaults:
    """D36: When GOKAATRU_CORS_ORIGINS is set, it should replace the dev
    defaults entirely — not extend them.  This prevents localhost origins
    from being trusted in production."""

    def test_configured_origins_excludes_localhost(self, monkeypatch):
        """A production CORS configuration must not include loopback defaults."""
        monkeypatch.setenv("GOKAATRU_CORS_ORIGINS", "https://app.example.com")
        origins = _get_allowed_origins()
        assert origins == ["https://app.example.com"]
        assert "http://localhost:5173" not in origins
        assert "http://127.0.0.1:5173" not in origins
        assert "http://localhost:4173" not in origins
        assert "http://127.0.0.1:4173" not in origins

    def test_localhost_rejected_when_origin_configured(self, monkeypatch):
        """An OPTIONS preflight from a localhost origin must be denied when
        only production origins are configured."""
        monkeypatch.setenv("GOKAATRU_CORS_ORIGINS", "https://app.example.com")
        app = create_app()

        with TestClient(app) as client:
            response = client.options(
                "/api/health",
                headers={
                    "Origin": "http://localhost:5173",
                    "Access-Control-Request-Method": "GET",
                },
            )

        # The CORS middleware rejects the unrecognized origin — the key
        # assertion is that localhost is not reflected back.
        assert "access-control-allow-origin" not in response.headers

    def test_multiple_configured_origins(self, monkeypatch):
        """Several production origins are all accepted; no dev defaults leak."""
        monkeypatch.setenv(
            "GOKAATRU_CORS_ORIGINS",
            "https://app.example.com, https://staging.example.com",
        )
        origins = _get_allowed_origins()
        assert origins == [
            "https://app.example.com",
            "https://staging.example.com",
        ]

    def test_empty_configured_value_still_falls_back(self, monkeypatch):
        """An empty string or whitespace-only value is treated as unset,
        so dev defaults are still used."""
        monkeypatch.setenv("GOKAATRU_CORS_ORIGINS", "  ")
        origins = _get_allowed_origins()
        assert "http://localhost:5173" in origins

    def test_unset_env_returns_dev_defaults(self, monkeypatch):
        """When the env var is missing entirely, all four dev origins
        are returned."""
        monkeypatch.delenv("GOKAATRU_CORS_ORIGINS", raising=False)
        origins = _get_allowed_origins()
        assert len(origins) == 4
        assert "http://localhost:5173" in origins
        assert "http://127.0.0.1:5173" in origins
        assert "http://localhost:4173" in origins
        assert "http://127.0.0.1:4173" in origins
