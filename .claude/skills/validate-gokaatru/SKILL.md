---
name: validate-gokaatru
description: Run GoKaatru's full backend + frontend validation suite (ruff, pytest, MCP tool count, vitest, tsc/build) and report a pass/fail summary. Use after any change to server/ or frontend/src/, or before telling the user a change is done.
---

# Validate GoKaatru

Run this whenever you've changed `server/` or `frontend/src/` and need to confirm nothing
broke, or before reporting a task complete.

## Steps

1. Backend lint:
   ```bash
   python -m ruff check server/ tests/
   ```
2. Backend tests:
   ```bash
   python -m pytest tests/ -v
   ```
   Current clean baseline (2026-08-23): 926 passed, 2 skipped. This number moves as the
   project grows — treat it as "roughly this many, zero failures" rather than an exact target.
   If a *different* count of failures shows
   up, don't assume they're pre-existing — GoKaatru's own audit history
   (`docs/audit-verification-report.md` §1.1) found that two failures once dismissed as
   "pre-existing and unrelated" were actually a real platform-divergence bug and a real
   defect. Read the failing test and the code it exercises before writing it off.
3. MCP tool count (confirms nothing broke tool registration):
   ```bash
   python -c "import asyncio; from server.main import mcp; print(len(asyncio.run(mcp.list_tools())), 'tools')"
   ```
   Current baseline: 223. If you added or removed a tool, expect the count to move by that
   many; if it moved unexpectedly, something registered wrong.
4. If `frontend/` changed:
   ```bash
   cd frontend && npm run test    # vitest, baseline 172 passed (2026-08-23)
   cd frontend && npm run build   # tsc --noEmit && vite build
   ```

## Reporting

Summarize as a short pass/fail table, not raw command output. Call out any count that moved
from the baselines above (926/2 skipped backend, 172 frontend, 223 tools) even if everything
still "passes" — a moved baseline is itself worth flagging to the user.

If you changed `server/tools/` or `server/api/routes/`, also check whether both the MCP tool
and the HTTP route were updated (dual-interface principle — see root `CLAUDE.md`). A route
change with no matching tool change (or vice versa) is a likely miss, not necessarily a bug.
