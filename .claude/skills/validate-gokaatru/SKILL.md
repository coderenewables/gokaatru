---
name: validate-gokaatru
description: Run GoKaatru's full backend + frontend validation suite (ruff, pytest, published-numbers check, MCP tool count, vitest, tsc/build, Playwright) and report a pass/fail summary. Use after any change to server/ or frontend/src/, or before telling the user a change is done.
---

# Validate GoKaatru

Run this whenever you've changed `server/` or `frontend/src/` and need to confirm nothing
broke, or before reporting a task complete. Run one suite at a time: running the backend and
frontend suites together has caused flaky failures.

## Steps

1. Backend lint:
   ```bash
   python -m ruff check server/ tests/
   ```
2. Backend tests:
   ```bash
   python -m pytest tests/ -q
   ```
   The current baseline is recorded in `CLAUDE.md` ("Current baseline"); re-derive it, don't
   trust it. Tests that need the gitignored campaign files skip without them, by name. If
   failures show up, don't assume they're pre-existing: the audit history found two dismissed
   failures that were real defects. Read the failing test and the code it exercises.
3. Published numbers (every number on the three reference campaigns, exact, about 35 s):
   ```bash
   python -m tests.published_numbers --check
   ```
   Also part of step 2. Any difference is a moved number: either a defect, or a deliberate
   change to record in `CLAUDE.md` with its before and after and to refresh with `--write`.
4. MCP surface and tool count:
   ```bash
   python -c "import asyncio; from server.main import mcp; print(len(asyncio.run(mcp.list_tools())), 'tools')"
   python -m tests.mcp_surface
   ```
   The count must equal `EXPECTED_MCP_TOOLS` in `.github/workflows/ci.yml`; the surface must be
   identical to `tests/snapshots/mcp_tools.json` unless you meant to change it.
5. If `frontend/` changed:
   ```bash
   cd frontend && npm run test       # vitest
   cd frontend && npm run build      # tsc --noEmit && vite build
   cd frontend && npm run test:e2e   # Playwright; own backend :8011 and Vite :5183
   ```

## Reporting

Summarize as a short pass/fail table, not raw command output. Call out any count that moved
from the recorded baseline even if everything passes: a moved baseline is worth flagging.

If you changed `server/tools/` or `server/operations.py`, check the declaration of what you
touched still says what the code does (`effect`, `network`, `disclosure`). The registry tests
pin the tiers, but only an honest declaration keeps them meaningful.
