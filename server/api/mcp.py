"""mcp — Session-aware MCP transport mounting for the GoKaatru FastAPI app.

Part of GoKaatru MCP Server.
"""
from __future__ import annotations

import json
from collections.abc import Callable
from contextlib import asynccontextmanager

from starlette.types import ASGIApp, Receive, Scope, Send

from server.api.deps import SESSION_HEADER_NAME
from server.main import mcp
from server.state.manager import SessionManager
from server.state.session import bind_session


class SessionResolutionError(Exception):
    """Represent an HTTP-level failure while resolving the bound browser session."""

    def __init__(self, status_code: int, detail: str) -> None:
        self.status_code = status_code
        self.detail = detail
        super().__init__(detail)


class SessionAwareMcpApp:
    """Bind incoming MCP HTTP requests to a managed SessionState before tool execution."""

    def __init__(self, app: ASGIApp, manager_provider: Callable[[], SessionManager]) -> None:
        self._app = app
        self._manager_provider = manager_provider

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self._app(scope, receive, send)
            return

        try:
            state = self._resolve_state(scope)
        except SessionResolutionError as exc:
            await self._send_json_error(send, exc.status_code, exc.detail)
            return

        with bind_session(state):
            await self._app(scope, receive, send)

    async def startup(self) -> None:
        """Start the mounted FastMCP sub-application lifespan hooks."""
        router = getattr(self._app, "router", None)
        if router is not None:
            await router.startup()

    async def shutdown(self) -> None:
        """Stop the mounted FastMCP sub-application lifespan hooks."""
        router = getattr(self._app, "router", None)
        if router is not None:
            await router.shutdown()

    @asynccontextmanager
    async def lifespan(self):
        """Expose the mounted FastMCP app lifespan for composition by the parent FastAPI app."""
        router = getattr(self._app, "router", None)
        if router is None:
            yield
            return
        async with router.lifespan_context(self._app):
            yield

    def _resolve_state(self, scope: Scope):
        path_params = scope.get("path_params") or {}
        path_session_id = path_params.get("session_id")
        header_session_id = self._get_header(scope, SESSION_HEADER_NAME)

        if path_session_id is None and header_session_id is None:
            raise SessionResolutionError(
                status_code=400,
                detail=(
                    "Session-aware MCP requests must include a session in the mount path "
                    f"or the '{SESSION_HEADER_NAME}' header"
                ),
            )
        if path_session_id and header_session_id and path_session_id != header_session_id:
            raise SessionResolutionError(
                status_code=400,
                detail=f"Header '{SESSION_HEADER_NAME}' must match path session_id",
            )

        session_id = path_session_id or header_session_id
        if session_id is None:
            raise SessionResolutionError(status_code=400, detail="Missing session_id")

        manager = self._manager_provider()
        try:
            return manager.get_session(session_id)
        except KeyError as exc:
            raise SessionResolutionError(status_code=404, detail=str(exc)) from exc

    @staticmethod
    def _get_header(scope: Scope, header_name: str) -> str | None:
        target = header_name.lower().encode("latin-1")
        for key, value in scope.get("headers", []):
            if key.lower() == target:
                return value.decode("latin-1")
        return None

    @staticmethod
    async def _send_json_error(send: Send, status_code: int, detail: str) -> None:
        payload = json.dumps({"detail": detail}).encode("utf-8")
        await send(
            {
                "type": "http.response.start",
                "status": status_code,
                "headers": [
                    (b"content-type", b"application/json"),
                    (b"content-length", str(len(payload)).encode("ascii")),
                ],
            }
        )
        await send({"type": "http.response.body", "body": payload})


def create_session_aware_mcp_app(manager_provider: Callable[[], SessionManager]) -> ASGIApp:
    """Create a stateless HTTP MCP app that executes tools against the resolved browser session."""
    base_app = mcp.http_app(path="/", transport="streamable-http", stateless_http=True)
    return SessionAwareMcpApp(base_app, manager_provider)