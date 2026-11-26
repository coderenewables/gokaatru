"""The generated operation routes, for tests that drive the HTTP surface (decisions/0009).

The hand-written routes that duplicated operations were retired in P3-17e; a test that went
through one now posts to ``/api/sessions/{id}/operations/{name}`` with the operation's own
parameters, as the workbench does.
"""

from __future__ import annotations

from typing import Any

from fastapi.testclient import TestClient
from httpx import Response


def operation(client: TestClient, session_id: str, name: str, /, **parameters: Any) -> Response:
    """Call one operation as the user, through its generated route."""
    return client.post(
        f"/api/sessions/{session_id}/operations/{name}",
        headers={"X-GoKaatru-Session": session_id},
        json=parameters,
    )
