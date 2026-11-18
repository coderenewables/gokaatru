# 0001. Keep the analysis engine; build a new interface shell; restructure the layer between

**Status:** Accepted (owner), 2026-11-17. The owner asked for an interactive, drag-and-drop
workbench and said starting afresh was acceptable; on 2026-11-17 the owner accepted
retiring the old interface once the new one passes its gates, and confirmed the clickable
mockup's direction.

## Context

The owner wants the application to be intuitive, visual and interactive. An audit of the
repository on 2026-11-16 found three layers in different states:

- **Engine** (`server/core`, `server/tools`): about 19,600 lines with over 1,000 tests and a
  completed 10-step physics audit. Every published number has a measured basis and a
  disclosure field.
- **Wiring** (`server/state`, `server/api`, the MCP registration): about 7,600 lines. Data
  lives in memory and is lost on restart (only `runconfig.json` is restored). Method names
  are hard-coded in about 15 places.
- **Frontend** (`frontend/src`): about 16,100 lines plus a 3,967-line stylesheet. Charts are
  display-only (no chart event bindings), one view shows at a time, and cleaning is a form.

## Decision

- Keep the engine and extend it. Do not rewrite audited physics.
- Build a new interface shell beside the old one. Reuse `frontend/src/lib`, `types`, the API
  clients and the sweep store where they fit. Retire the old interface once the new one
  passes its gates.
- Restructure the wiring: one operation registry ([0009](0009-operation-registry.md)) and a
  project store that survives restarts ([0010](0010-project-store-and-flags.md)).

## Consequences

- Every refactor of the wiring carries a numbers-identical gate on the reference campaigns,
  as handover task T8 did (68 sweep rows compared before and after).
- Two interfaces coexist until the gate; the old one is not extended in the meantime.
- "In one shot" is not achievable: the work is phased, each phase ending in something usable.
