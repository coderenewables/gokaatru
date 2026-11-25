"""What MCP clients receive from ``tools/list``, as one comparable record (P1-3).

The snapshot pins the tool surface the registry generates: names, descriptions, input and
output schemas and annotations, in registration order. Refresh it only with a deliberate
change to that surface:

    python -m tests.mcp_surface --write
"""
from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path
from typing import Any

SNAPSHOT_PATH = Path(__file__).resolve().parent / "snapshots" / "mcp_tools.json"


def current_surface() -> list[dict[str, Any]]:
    from server.main import mcp

    tools = asyncio.run(mcp.list_tools())
    return [tool.to_mcp_tool().model_dump(mode="json") for tool in tools]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--write", action="store_true", help="overwrite the snapshot")
    args = parser.parse_args(argv)
    surface = current_surface()
    if args.write:
        SNAPSHOT_PATH.parent.mkdir(parents=True, exist_ok=True)
        SNAPSHOT_PATH.write_text(json.dumps(surface, indent=1, sort_keys=True) + "\n", encoding="utf-8")
        print(f"{len(surface)} tools written to {SNAPSHOT_PATH}")
        return 0
    changed = differences(load_snapshot(), surface)
    print(f"{len(surface)} tools; {'identical' if not changed else 'different'} to the snapshot")
    for line in changed:
        print("   ", line)
    return 1 if changed else 0


def load_snapshot() -> list[dict[str, Any]]:
    return json.loads(SNAPSHOT_PATH.read_text(encoding="utf-8"))


def differences(expected: list[dict[str, Any]], actual: list[dict[str, Any]]) -> list[str]:
    """Tool by tool. Registration order depends on which module is imported first, so it is
    not part of the comparison; MCP clients do not depend on it."""
    before = {tool["name"]: tool for tool in expected}
    after = {tool["name"]: tool for tool in actual}
    lines = [f"missing  {name}" for name in sorted(before.keys() - after.keys())]
    lines += [f"new      {name}" for name in sorted(after.keys() - before.keys())]
    lines += [f"changed  {name}" for name in sorted(before.keys() & after.keys()) if before[name] != after[name]]
    return lines


if __name__ == "__main__":
    sys.exit(main())
