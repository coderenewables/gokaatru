"""chat — LLM chat proxy with MCP tool execution for the GoKaatru web API.

Part of GoKaatru MCP Server.
"""
from __future__ import annotations

import asyncio
import inspect
import json
from typing import Annotated, Any

import httpx
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field, JsonValue

from server.api.deps import get_session_state
from server.state.session import SessionState, bind_session

router = APIRouter(prefix="/sessions/{session_id}", tags=["chat"])

# Maximum consecutive LLM ↔ tool-call round-trips to prevent runaway loops.
_MAX_TOOL_ROUNDS = 12

# Provider base URLs keyed by short name.
_PROVIDER_URLS: dict[str, str] = {
    "openai": "https://api.openai.com/v1",
    "openrouter": "https://openrouter.ai/api/v1",
    "groq": "https://api.groq.com/openai/v1",
    "together": "https://api.together.xyz/v1",
}

_DEFAULT_MODELS: dict[str, str] = {
    "openai": "gpt-4o",
    "openrouter": "openai/gpt-4o",
    "groq": "llama-3.3-70b-versatile",
    "together": "meta-llama/Meta-Llama-3.1-70B-Instruct-Turbo",
}


# ---------------------------------------------------------------------------
# Request / Response schemas
# ---------------------------------------------------------------------------


class ChatMessage(BaseModel):
    role: str = Field(..., pattern="^(system|user|assistant)$")
    content: str


class ChatRequest(BaseModel):
    api_key: str = Field(..., min_length=1)
    provider: str = Field("openai")
    model: str = Field("")
    messages: list[ChatMessage] = Field(..., min_length=1)


class ToolCallResult(BaseModel):
    tool_name: str
    arguments: dict[str, JsonValue]
    result: JsonValue


class ChatResponse(BaseModel):
    reply: str
    tool_calls_executed: list[ToolCallResult] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# Tool registry — build once, cache forever
# ---------------------------------------------------------------------------

_OPENAI_TOOLS: list[dict[str, Any]] | None = None
_TOOL_CALLABLES: dict[str, Any] | None = None


def _build_registries() -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Build OpenAI-compatible tool definitions and a name→callable map from the MCP registry."""
    global _OPENAI_TOOLS, _TOOL_CALLABLES
    if _OPENAI_TOOLS is not None and _TOOL_CALLABLES is not None:
        return _OPENAI_TOOLS, _TOOL_CALLABLES

    from server.main import mcp

    # FastMCP's list_tools() is async. We may be called from a sync thread
    # inside uvicorn's running event loop, so use a fresh thread + event loop.
    import concurrent.futures
    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
        future = pool.submit(asyncio.run, mcp.list_tools())
        tools = future.result(timeout=30)

    openai_tools: list[dict[str, Any]] = []
    callables: dict[str, Any] = {}

    # Build a name→function map from the tool modules.
    import server.tools.air_density as _ad
    import server.tools.cleaning as _cl
    import server.tools.clipping as _clip
    import server.tools.config as _cfg
    import server.tools.data_io as _dio
    import server.tools.ensemble as _ens
    import server.tools.era5 as _era5
    import server.tools.extrapolation as _ext
    import server.tools.homogeneity as _hom
    import server.tools.ltc as _ltc
    import server.tools.ltc_ml as _lml
    import server.tools.map as _mp
    import server.tools.shear as _sh
    import server.tools.statistics as _st
    import server.tools.uncertainty as _unc
    import server.tools.visualization as _viz

    all_modules = [_ad, _cl, _clip, _cfg, _dio, _ens, _era5, _ext, _hom, _ltc, _lml, _mp, _sh, _st, _unc, _viz]
    module_names: dict[str, Any] = {}
    for mod in all_modules:
        for name, obj in inspect.getmembers(mod, inspect.isfunction):
            if not name.startswith("_"):
                module_names[name] = obj

    for tool in tools:
        schema = dict(tool.parameters) if tool.parameters else {"type": "object", "properties": {}}
        schema.pop("title", None)
        schema.pop("additionalProperties", None)

        openai_tools.append({
            "type": "function",
            "function": {
                "name": tool.name,
                "description": tool.description or "",
                "parameters": schema,
            },
        })

        if tool.name in module_names:
            callables[tool.name] = module_names[tool.name]

    _OPENAI_TOOLS = openai_tools
    _TOOL_CALLABLES = callables
    return openai_tools, callables


# ---------------------------------------------------------------------------
# Tool execution — bind the managed session for the current tool call
# ---------------------------------------------------------------------------


def _execute_tool(name: str, arguments: dict[str, Any], state: SessionState) -> Any:
    """Execute an MCP tool by name, routing it through the correct SessionState."""
    _, callables = _build_registries()
    fn = callables.get(name)
    if fn is None:
        return {"error": f"Unknown tool: {name}"}

    with bind_session(state):
        try:
            return fn(**arguments)
        except Exception as exc:
            return {"error": f"{type(exc).__name__}: {exc}"}


# ---------------------------------------------------------------------------
# LLM interaction
# ---------------------------------------------------------------------------

_SYSTEM_PROMPT = (
    "You are GoKaatru, a wind resource assessment assistant. "
    "You have access to tools that can parse wind measurement data, compute statistics, "
    "run shear/extrapolation analysis, fetch ERA5 reanalysis data, run long-term correction algorithms, "
    "compute uncertainty, and generate visualizations. "
    "Use the tools to answer the user's questions about their wind data project. "
    "Always explain what you are doing and summarize the results clearly. "
    "When a tool returns a Plotly JSON figure, tell the user the plot has been generated."
)


def _resolve_base_url(provider: str) -> str:
    normalized = provider.lower().strip()
    base = _PROVIDER_URLS.get(normalized)
    if base is None:
        # Custom endpoints must be HTTPS to a public-looking host. Reject http://
        # and obvious internal/loopback targets so a malicious user cannot point
        # the server at internal metadata or admin services.
        if normalized.startswith("https://"):
            from urllib.parse import urlparse

            parsed = urlparse(normalized)
            host = (parsed.hostname or "").lower()
            blocked_hosts = {"localhost", "127.0.0.1", "0.0.0.0", "::1", "metadata.google.internal"}
            if (
                not host
                or host in blocked_hosts
                or host.endswith(".local")
                or host.startswith("169.254.")
                or host.startswith("10.")
                or host.startswith("192.168.")
                or host.startswith("172.")  # broad but acceptable for outbound LLM calls
            ):
                raise ValueError("Custom provider host is not allowed")
            return normalized.rstrip("/")
        raise ValueError(f"Unknown provider '{provider}'. Supported: {', '.join(sorted(_PROVIDER_URLS))}")
    return base


def _resolve_model(provider: str, model: str) -> str:
    if model.strip():
        return model.strip()
    return _DEFAULT_MODELS.get(provider.lower().strip(), "gpt-4o")


def _call_llm(
    api_key: str,
    provider: str,
    model: str,
    messages: list[dict[str, Any]],
    tools: list[dict[str, Any]],
) -> dict[str, Any]:
    """Call an OpenAI-compatible chat completions endpoint synchronously."""
    try:
        url = f"{_resolve_base_url(provider)}/chat/completions"
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
    payload: dict[str, Any] = {"model": model, "messages": messages}
    if tools:
        payload["tools"] = tools
        payload["tool_choice"] = "auto"

    with httpx.Client(timeout=120.0) as client:
        resp = client.post(url, json=payload, headers=headers)

    if resp.status_code != 200:
        # Avoid echoing upstream provider response bodies (which may contain
        # rate-limit secrets, request ids, or partial keys) back to the client.
        raise HTTPException(
            status_code=resp.status_code if 400 <= resp.status_code < 600 else 502,
            detail=f"Upstream LLM provider returned status {resp.status_code}",
        )

    return resp.json()


# ---------------------------------------------------------------------------
# Route
# ---------------------------------------------------------------------------


@router.post("/chat")
def chat(
    session_id: str,
    body: ChatRequest,
    state: Annotated[SessionState, Depends(get_session_state)],
) -> ChatResponse:
    """Send a chat message, execute any tool calls against the session, and return the reply."""
    provider = body.provider.lower().strip() or "openai"
    model = _resolve_model(provider, body.model)
    openai_tools, _ = _build_registries()

    messages: list[dict[str, Any]] = [{"role": "system", "content": _SYSTEM_PROMPT}]
    for msg in body.messages:
        messages.append({"role": msg.role, "content": msg.content})

    tool_calls_executed: list[ToolCallResult] = []

    for _ in range(_MAX_TOOL_ROUNDS):
        response = _call_llm(body.api_key, provider, model, messages, openai_tools)
        choices = response.get("choices", [])
        if not choices:
            raise HTTPException(status_code=502, detail="LLM returned no choices")

        message = choices[0].get("message", {})
        finish_reason = choices[0].get("finish_reason", "stop")
        pending = message.get("tool_calls")

        if finish_reason == "tool_calls" or pending:
            messages.append(message)
            for tc in pending or []:
                fn = tc.get("function", {})
                tool_name = fn.get("name", "")
                raw_arguments = fn.get("arguments", "{}")
                try:
                    arguments = json.loads(raw_arguments) if isinstance(raw_arguments, str) else dict(raw_arguments)
                    if not isinstance(arguments, dict):
                        raise ValueError("tool arguments must decode to a JSON object")
                    result: Any = _execute_tool(tool_name, arguments, state)
                except (json.JSONDecodeError, ValueError, TypeError) as exc:
                    arguments = {}
                    result = {"error": f"Invalid tool arguments for '{tool_name}': {exc}"}
                else:
                    pass

                try:
                    result_str = json.dumps(result, default=str)
                except (TypeError, ValueError):
                    result_str = str(result)

                tool_calls_executed.append(
                    ToolCallResult(tool_name=tool_name, arguments=arguments, result=json.loads(result_str))
                )
                messages.append({"role": "tool", "tool_call_id": tc.get("id", ""), "content": result_str})
            continue

        reply_text = message.get("content", "") or ""
        return ChatResponse(reply=reply_text, tool_calls_executed=tool_calls_executed)

    return ChatResponse(reply="Reached the maximum number of tool-call rounds.", tool_calls_executed=tool_calls_executed)
