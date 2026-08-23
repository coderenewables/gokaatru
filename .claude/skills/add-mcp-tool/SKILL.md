---
name: add-mcp-tool
description: Add a new capability to GoKaatru correctly across both interfaces (MCP tool and FastAPI route) with matching tests and README updates. Use when asked to add a new analysis, computation, or endpoint to the backend.
---

# Add an MCP tool (dual-interface)

GoKaatru's core principle: **MCP tools and FastAPI routes call identical business logic** in
`server/tools/` or `server/core/`. Never write logic directly in the MCP handler or the route
handler — both are thin wrappers over a shared function. See root `CLAUDE.md` before starting.

## Order of work

1. **Write the logic first**, in `server/tools/<area>.py` (session-aware, e.g. reads/writes
   `SessionState`) or `server/core/<area>.py` (pure math, no session dependency — prefer this
   when possible, it's independently testable). Look at a sibling function in the same file
   for the house style: small, single-purpose (~50 LOC), Pydantic-validated inputs.

2. **Decide if it changes a reported number.** If it introduces a clamp, threshold, default,
   or fallback that affects output, you need the disclosure pattern — invoke the
   `disclosure-check` skill now, before wiring up the interfaces, since it affects the
   function's return shape.

3. **Register the MCP tool** in `server/main.py`, following the existing registration style
   for tools in the same category (check the README's "Tool inventory" section for which
   category this belongs in).

4. **Add the FastAPI route** in the matching file under `server/api/routes/` (e.g. shear
   logic → `server/api/routes/analysis.py` alongside other shear endpoints). Session-scoped
   routes require the `X-GoKaatru-Session` header; `ValueError` → 400, upstream errors → 502
   (existing convention — check a neighboring route for the exact pattern).

5. **Test it against `tests/oracles.py` where physics/statistics is involved.** If the new
   tool computes something with a closed-form or independently-derivable answer, add or reuse
   an oracle generator there (it deliberately imports nothing from `server/`) and assert
   agreement to a tight tolerance. This is how GoKaatru catches its own math bugs; see
   `docs/audit/01-ledger.md` for why this harness exists.

6. **Update README.md**:
   - Add the tool name to the relevant category under "Tool inventory".
   - Add the endpoint to the "Web API" table if you added a route.
   - If it introduces a disclosed default/clamp, add a row to "Defaults that affect results"
     or "Disclosure fields" (see the `disclosure-check` skill).

7. **Run `validate-gokaatru`** — confirm the tool count moved by exactly the number of tools
   you added, tests pass, and (if the frontend consumes it) `npm run build` is clean.

## Common mistake to avoid

Adding the route without the MCP tool (or vice versa) because "the UI doesn't need it via
MCP" or "the Copilot doesn't need it via HTTP." Both interfaces should expose the same
capability set — that's the whole point of the dual-interface principle. If you genuinely
believe one interface shouldn't get this capability, that's a decision worth surfacing to the
user rather than making silently.
