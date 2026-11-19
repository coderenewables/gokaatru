"""The MCP surface is generated from the operation registry and unchanged by it (P1-3)."""
from __future__ import annotations

from pathlib import Path

from tests.mcp_surface import current_surface, differences, load_snapshot

TOOLS_DIR = Path(__file__).resolve().parents[1] / "server" / "tools"


def test_the_generated_mcp_surface_equals_the_snapshot() -> None:
    changed = differences(load_snapshot(), current_surface())
    assert not changed, (
        "The MCP tool surface changed:\n  " + "\n  ".join(changed)
        + "\nIf intended: python -m tests.mcp_surface --write, and record it."
    )


def test_no_tool_module_registers_with_mcp_directly() -> None:
    """Every tool reaches MCP through its operation declaration, never around it."""
    direct = [
        f"{path.relative_to(TOOLS_DIR)}:{number}"
        for path in sorted(TOOLS_DIR.rglob("*.py"))
        for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1)
        if line.lstrip().startswith("@mcp.") or "from server.main import mcp" in line
    ]
    assert direct == []


def test_differences_reports_missing_new_and_changed_tools() -> None:
    before = [{"name": "a", "description": "x"}, {"name": "b", "description": "y"}]
    after = [{"name": "b", "description": "z"}, {"name": "c", "description": "w"}]
    assert differences(before, after) == ["missing  a", "new      c", "changed  b"]
