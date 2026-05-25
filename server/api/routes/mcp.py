"""mcp - MCP catalog endpoints for the GoKaatru web API.

Part of GoKaatru MCP Server.
"""
from __future__ import annotations

from fastapi import APIRouter

from server.main import mcp

router = APIRouter(prefix="/mcp", tags=["mcp"])


@router.get("/catalog")
async def get_mcp_catalog() -> dict[str, object]:
    """Return the MCP server catalog for browser clients that cannot connect to raw SSE directly."""
    tools = await mcp.list_tools()
    resources = await mcp.list_resources()

    return {
        "serverName": getattr(mcp, "name", "GoKaatru MCP"),
        "serverVersion": getattr(mcp, "version", "unknown"),
        "instructions": getattr(mcp, "instructions", "") or "",
        "tools": [
            {
                "name": tool.name,
                "description": tool.description or "",
                "inputSchema": dict(tool.parameters) if tool.parameters else {},
            }
            for tool in tools
        ],
        "resources": [
            {
                "uri": str(getattr(resource, "uri", "")),
                "name": getattr(resource, "name", "") or str(getattr(resource, "uri", "")),
                "description": getattr(resource, "description", None),
                "mimeType": getattr(resource, "mimeType", None),
            }
            for resource in resources
        ],
    }