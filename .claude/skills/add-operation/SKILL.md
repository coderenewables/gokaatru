---
name: add-operation
description: Add a new analysis capability to GoKaatru as a declared operation, which generates its MCP tool, HTTP route, canvas dispatch and assistant tier, with matching tests and README rows. Use when asked to add a new analysis, computation, tool or endpoint to the backend.
---

# Add an operation

Every capability is declared once in `server/operations.py`'s registry (decisions/0009). One
`@operation(...)` declaration publishes the MCP tool, the generated route
`POST /sessions/{id}/operations/{name}` (and `/preview` when there is a dry run), the canvas
dispatch and the assistant tier. Never call `mcp.tool()` or import `server.main` in a tool
module; `tests/test_mcp_surface.py` refuses it.

## Order of work

1. **Write the logic first.** Pure math in `server/core/<area>.py` (no session, imports neither
   FastAPI nor FastMCP), the session-aware part as a private `_name(state, ...)` in
   `server/tools/<area>.py`. Match a sibling function's style. New physics or statistics needs
   an oracle-backed test against `tests/oracles.py` (it imports nothing from `server/`).

2. **Decide whether it changes a reported number.** A clamp, threshold, default or fallback
   needs the `disclosure-check` skill now, because it shapes the response.

3. **Add the public function with its declaration**, in the same module:

   ```python
   @operation(effect="read", stage="statistics")
   def compute_new_thing(sensor_name: str, window_days: int = 30) -> dict:
       """One line: what it returns. This becomes the MCP and HTTP description."""
       return _compute_new_thing(session, sensor_name, window_days)
   ```

   - `effect`: `"read"` only if it changes no session state and writes no file. A value written
     into `state.runconfig` counts as a change (P1-5a, P1-5b were both found this way).
   - `stage`: one of `STAGES`; it sets the canvas tie-break order.
   - `network=True` if it calls an external service; the assistant then needs the opt-in.
   - `canvas=False` if a workflow node must not dispatch it; `assistant=False` if the chat
     assistant must never be offered it (credential and network tools).
   - `disclosure=(...)`: every response field that reports a default, clamp or fallback firing.
     Each needs a row in README's "Disclosure fields" table.
   - `dry_run=preview_fn` for a change that should be previewable; `preview_fn` takes exactly
     the same parameters. Run the real function on `_replica(state)` and diff, as
     `server/tools/cleaning.py` does, so the preview cannot drift from the change.
   - `standards=(...)`: "Traced to ..." wording only, never "compliant" or "follows".
   - `result=result_models.ComputeNewThingResult`: the Pydantic model of the response, in
     `server/schemas/results/<module>.py` (imported as `result_models`), over the pieces in
     `_base.py`. Every field the function can return, conditional ones optional (read the
     function for each `result["..."] = ` and `**` spread; a sample shows only the branches it
     took). A float is `Number`. A dry run also needs `preview_result=`.
   - `reads=(...)`, `writes=(...)`: the artifacts (`server/state/artifacts.py`) it reads and
     writes, the canvas's ports and what staleness follows. A read writes nothing. Declare every
     artifact any branch reads or writes, not only those one sample reaches;
     `tests/test_artifacts.py` fails on an undeclared one, and a declared write no sample makes
     needs its reason in `WRITES_NOT_OBSERVED`.
   - `selectable=True` for a read that computes from the measured records (the working frame,
     raw data, or the shear and roughness timeseries). The wrapper publishes a `selection`
     parameter and runs the function with every record outside it blank; nothing in the
     function changes. A read of stored results, the long-term series, the reanalysis or the
     data inventory is not selectable, because a selection would not restrict what it reads.

4. **Make the pinned surfaces say so.** These tests fail until you do, on purpose:
   - `tests/test_operations.py`: add the name to `PINNED_READ_TIER`, `PINNED_CHANGE_TIER` or
     `PINNED_UNEXPOSED`, to `PINNED_NOT_ON_CANVAS` if `canvas=False`, and the module to
     `PINNED_STAGE_BY_MODULE` if it is new.
   - `python -m tests.mcp_surface --write` to record the new tool, then check the diff shows
     only it.
   - `python -m tests.openapi_schema --write`, then `cd frontend && npm run generate:api`: the
     committed OpenAPI schema and the TypeScript client generated from it. CI fails on either
     being stale (`tests/test_openapi_schema.py`, `npm run check:api`).
   - `tests/test_phase4.py` and `EXPECTED_MCP_TOOLS` in `.github/workflows/ci.yml`: the count.
   - A read operation is picked up by `tests/test_operation_routes.py` automatically; give its
     required parameters a value in `ARGUMENT_VALUES` if their names are new. That test also
     proves the read changes nothing.
   - Every read goes in `tests/test_selection_operations.py`: `SELECTABLE` (which then checks
     it equals the operation on a pre-filtered session) or `NOT_SELECTABLE` with the reason.
   - `tests/operation_samples.py` must produce a real response from it: a read is called on
     its own; a change needs a line in `_changes` (or `_network` against a fake). Then
     `tests/test_operation_results.py` validates the response against its model, and
     `tests/test_read_operations.py` checks a read leaves the analysed session unchanged.

5. **README**: the tool under "Tool inventory", the generated route needs no row, and any
   disclosure fields their rows. A new module gets a row in CODEDOC's `server/tools/` table.

6. **Run `validate-gokaatru`**, including `python -m tests.published_numbers --check`: a new
   operation must not move any existing number.

## Mistakes to avoid

- Declaring a write a read to keep it in the assistant's default tier. The read tier's
  contract is checked by test; a convenient misdeclaration is the defect, not the test.
- Hand-writing an HTTP route for it. The generated route already exists; a hand-written one
  is only for a request shape the generator cannot express, and then it calls the same
  private function.
- Loosening a pinned list without saying why in the commit message.
