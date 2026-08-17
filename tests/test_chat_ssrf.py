"""Regression tests for D21 — the chat proxy must not be aimable at internal hosts.

The old guard was a string blocklist on the literal hostname, which six of the
rows below walked straight past. Custom endpoint URLs are now rejected outright.
"""

from __future__ import annotations

import pytest

from server.api.routes.chat import _PROVIDER_URLS, _resolve_base_url

# Every row that is not one of the four named providers must raise.
SSRF_CANDIDATES = [
    pytest.param("https://127.0.0.1", id="loopback-literal"),
    pytest.param("https://127.0.0.2", id="loopback-8-not-just-dot-1"),
    pytest.param("https://2130706433", id="decimal-encoded-loopback"),
    pytest.param("https://0x7f000001", id="hex-encoded-loopback"),
    pytest.param("https://0", id="zero-resolves-to-0.0.0.0"),
    pytest.param("https://[fd00::1]", id="ipv6-unique-local"),
    pytest.param("https://internal.corp", id="dns-name-to-internal-ip"),
    pytest.param("https://169.254.169.254", id="cloud-metadata"),
    pytest.param("https://10.0.0.5", id="rfc1918-10"),
    pytest.param("https://172.16.0.5", id="rfc1918-172-16"),
    pytest.param("https://192.168.1.5", id="rfc1918-192-168"),
    pytest.param("https://localhost", id="localhost"),
    pytest.param("https://metadata.google.internal", id="gcp-metadata"),
    pytest.param("https://api.openai.com.evil.test", id="suffix-confusion"),
    pytest.param("http://127.0.0.1", id="plain-http-loopback"),
    pytest.param("https://172.32.0.1", id="public-172-was-over-blocked"),
]


class TestCustomEndpointsRejected:
    """D21 — resolve-then-validate is unnecessary once the feature is gone."""

    @pytest.mark.parametrize("candidate", SSRF_CANDIDATES)
    def test_custom_urls_raise(self, candidate: str) -> None:
        with pytest.raises(ValueError) as excinfo:
            _resolve_base_url(candidate)
        assert "Custom endpoint URLs are not accepted" in str(excinfo.value)

    def test_error_names_the_supported_providers(self) -> None:
        with pytest.raises(ValueError) as excinfo:
            _resolve_base_url("https://internal.corp")
        message = str(excinfo.value)
        for provider in _PROVIDER_URLS:
            assert provider in message


class TestNamedProvidersStillWork:
    """The allowlist must not break the providers the UI actually offers."""

    @pytest.mark.parametrize("provider", sorted(_PROVIDER_URLS))
    def test_named_provider_resolves(self, provider: str) -> None:
        assert _resolve_base_url(provider) == _PROVIDER_URLS[provider]

    @pytest.mark.parametrize("provider", ["OpenAI", "  groq  ", "OPENROUTER"])
    def test_name_matching_is_case_and_space_insensitive(self, provider: str) -> None:
        assert _resolve_base_url(provider).startswith("https://")

    def test_every_resolved_url_is_https(self) -> None:
        for provider in _PROVIDER_URLS:
            assert _resolve_base_url(provider).startswith("https://")
