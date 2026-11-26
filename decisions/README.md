# Decision records

One file per architectural or scope decision for the workbench rebuild: what was decided,
why, and on what evidence. Committed so a fresh clone carries the reasons (`docs/` is
gitignored). The build plan itself is local; these records are the parts of it that were
decided.

**Status** is one of:

- **Accepted (owner)**: the project owner decided it, with the date.
- **Accepted (measured)**: chosen by a measurement whose evidence is linked; the owner can
  overrule it.
- **Proposed**: designed in the plan and needed for Phase 1, but not yet decided on its own.
  It is confirmed or changed before the code that depends on it is written.
- **Superseded**: replaced by a later record, named in the file.

A record is not edited after acceptance except to change its status. A changed decision
gets a new record that supersedes the old one.

| # | Decision | Status |
| --- | --- | --- |
| [0001](0001-keep-engine-new-shell.md) | Keep the analysis engine; build a new interface shell; restructure the layer between | Accepted (owner), 2026-11-17 |
| [0002](0002-scope-long-term-dataset.md) | The product's output is a long-term-corrected dataset, not an energy yield | Accepted (owner), 2026-11-16 and 2026-11-17 |
| [0003](0003-local-single-user.md) | Local, single-user deployment; actor recorded on every action; no authentication | Accepted (owner), 2026-11-16 |
| [0004](0004-standards-traced-not-claimed.md) | Methods are traced to public standards material; no conformance claim | Accepted (owner), 2026-11-16 and 2026-11-17 |
| [0005](0005-charts-uplot-regl-scatterplot.md) | Interactive charts: uPlot and regl-scatterplot, decimated on the server | Accepted (measured), 2026-11-19 |
| [0006](0006-docking-dockview.md) | Docking layout: Dockview, with a custom tab component and theme class | Accepted (measured), 2026-11-19 |
| [0007](0007-assistant-byok-with-approval.md) | Assistant: bring your own key; every data change needs approval | Accepted (owner), 2026-11-17 |
| [0008](0008-bring-your-own-models.md) | Your own models: Python plugin and ONNX file first; pickle refused | Accepted (owner), 2026-11-17 |
| [0009](0009-operation-registry.md) | One operation registry generates every surface; WindKit only where it is the reference | Accepted (owner), 2026-11-19 |
| [0010](0010-project-store-and-flags.md) | A project store on disk; cleaning as flags, not deletions; one operation log | Accepted (owner), 2026-11-19 |
| [0011](0011-selections-on-the-server.md) | Selections are server objects resolved from drawn bounds | Accepted (owner), 2026-11-19 |
| [0012](0012-frontend-stack.md) | Frontend stack for the new shell | Accepted (owner), 2026-11-19 |
| [0013](0013-long-term-direction-and-temperature.md) | Long-term direction, temperature and air density in the dataset; methods chosen by measurement; not swept, and said so | Accepted (owner), 2026-11-19 |
| [0014](0014-workbench-prepare.md) | The workbench's Prepare: flags from selections, linked views, projects of campaigns | Accepted (owner), 2026-11-25 |
| [0015](0015-workbench-model-run-interrogate.md) | The workbench's Model, Run and Interrogate; staleness follows dependencies; the old interface retired | Accepted (owner), 2026-11-25 |
