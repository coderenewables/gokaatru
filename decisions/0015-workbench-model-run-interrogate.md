# 0015. The workbench's Model, Run and Interrogate, and the old interface retired

**Status:** Accepted (owner), 2026-11-25. Built in Phase 3.

## Context

Phase 3 builds the rest of the workbench and retires the interface at `/` (plan §6): a pipeline
canvas with a palette and generated forms, a matrix sweep designer, linked and brushable
scenario views (plan §3.3 rows Model, Run and Interrogate). Phase 2 left the shell, Prepare,
the operation log with undo, and the generated client ([0014](0014-workbench-prepare.md)). Each
choice below was put to the owner with its alternatives; the ones marked "not put to the owner"
follow from those answers and the plan.

## Decision

1. **The canvas holds the campaign's one chosen chain, and the sweep explores around it.** Each
   method is a node whose form is generated from its operation's declaration. A sweep scenario
   loads into the canvas, and running it reproduces that scenario's row; "Sweep around this"
   fills the matrix from the pipeline's choices. The sweep engine and its five axes are
   unchanged. (The owner chose this over making every canvas parameter sweepable, which would
   have rewritten the engine.)
2. **Operations declare what they read and write** (the working data, the shear table, the hub
   series, each long-term correction, and so on). These are the canvas's typed ports. One
   operation produces each result, so a node's inputs connect to their producer when it is
   dropped and a connection between mismatched types cannot be drawn. The order of a pipeline
   comes from these dependencies, never from drawn edges (which removes F-09's advisory edges).
   A test holds the declarations to the code: what an operation changes in the session equals
   what it declares it writes, and it gives the same answer with every result it does not
   declare as read removed. *(Not put to the owner.)*
3. **A result is stale when anything it was built from changed:** the data, the engine, or a
   result it read, rebuilt since or itself stale. Today only the first two count, so rebuilding
   the shear table with another method leaves the hub series, every long-term correction, the
   ensemble and the uncertainty reported current (measured on the synthetic pipeline,
   2026-11-25). A node whose parameters differ from those its result was built with shows as
   changed. Nothing is recomputed on its own; "Run stale" is a click. *(Not put to the owner.)*
4. **A pipeline runs one step at a time through the generated routes,** in the order the server
   gives, each step a logged operation of its own. The Canvas executor and its workflow routes
   go with the old interface. *(Not put to the owner.)*
5. **Named pipelines only.** A pipeline is saved and reopened by name in the campaign, saved
   with the project. The pipeline being edited is view state. Snapshots, run comparison and
   session forks are not carried over.
6. **The matrix sweep designer** shows the five axes by their levels. Ticking a cell updates the
   scenario count, the duplicates and the unavailable levels with their reasons, from the
   server; they equal what the run then skips and refuses.
7. **Interrogate** links its scenario views as Prepare links its charts: a metric histogram with
   a brush, parallel coordinates with a brush on each axis, and level filters, intersected.
   The variance decomposition, gate report, spread summary and uncertainty substitution are
   computed on the server over the filtered scenarios. Two scenarios can be pinned side by side
   with their configurations compared.
8. **What is not swept is stated as a sentence with its reason** (closing the wording left open
   by [0013](0013-long-term-direction-and-temperature.md)): "Not swept: wind direction,
   temperature and air density. Every scenario in this sweep uses the same ones, so the spread
   covers the wind-speed chain only: sensor choice, shear, reference source and long-term
   method." The manifest carries `not_swept`, and the summary, the Interrogate page and the
   export provenance render it from there.
9. **The energy sensitivity computes the site's air density itself** from the measured
   temperature and pressure, so its answer depends only on the data, not on whether the
   atmospheric diagnostic ran first (closes P1-5b). It reports the density and the sensors
   used, and skips normalisation, disclosed as now, only when either sensor is missing.
10. **The old interface is retired at the Phase 3 gate.** The workbench is served at `/`. The old
    application, its store, its hand-written client and its tests are deleted, as are the
    hand-written routes that the generated ones replace; their tests move to the generated
    routes.
11. **The Copilot and the Results report are dropped until they are rebuilt,** in Phase 4 and
    Phase 7. No screen offers an assistant between the Phase 3 and Phase 4 gates. The server's
    chat route stays as the base Phase 4 builds on. The How To page is dropped: each operation's
    description, disclosure fields and standards references are shown in the inspector instead.
12. **Sessions made in the old interface stay unreachable from the screens:** they belong to no
    project, and remain on disk and over MCP and HTTP (owner, 2026-11-17, confirmed 2026-11-25).
13. **Prepare gains what 0014.7 left in the old interface:** the sensor overview tables and the
    form-based cleaning rules, with a preview before applying. *(Not put to the owner.)*
14. **Work split** as in 0014.13: server work and integration inline, self-contained
    components to Sonnet agents in separate worktrees.

## Consequences

- `@operation` gains `reads` and `writes`, published by `GET /operations`; the MCP surface does
  not change.
- `stamp_derived` records the build of each input. `staleness_report` can now list results whose
  data version is current, and its `stale_reasons` name the input that changed.
- Saved selections become undoable, as 0014.6 already said; Phase 2 left them out.
- The equivalence of old and new sweep designers is tested before the old one is deleted;
  afterwards the new designer's rows are held to the server's own run of the same
  specification.
