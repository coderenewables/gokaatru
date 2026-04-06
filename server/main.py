"""server.main — GoKaatru MCP Server entry point.

Part of GoKaatru MCP Server.
"""
from __future__ import annotations

import argparse
import sys

from fastmcp import FastMCP

mcp = FastMCP(
    name="GoKaatru",
    version="0.1.0",
    instructions="Wind Resource Assessment MCP Server - IEC-compliant wind data analysis tools",
)

sys.modules.setdefault("server.main", sys.modules[__name__])

import server.tools.cleaning  # noqa: F401,E402
import server.tools.config  # noqa: F401,E402
import server.tools.data_io  # noqa: F401,E402
import server.tools.extrapolation  # noqa: F401,E402
import server.tools.shear  # noqa: F401,E402
import server.tools.statistics  # noqa: F401,E402


def main() -> None:
    """Run the FastMCP server with a thin CLI wrapper for transport selection."""
    parser = argparse.ArgumentParser(prog="python -m server.main")
    parser.add_argument("--transport", choices=["stdio", "sse"], default="stdio")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8000)
    args = parser.parse_args()
    if args.transport == "sse":
        mcp.run(transport="sse", host=args.host, port=args.port)
        return
    mcp.run(transport="stdio")

if __name__ == "__main__":
    main()
