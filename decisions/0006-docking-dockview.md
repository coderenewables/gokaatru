# 0006. Docking layout: Dockview, with a custom tab component and theme class

**Status:** Accepted (measured), 2026-11-19. Evidence: `spikes/docking-layout/FINDINGS.md`
(P0-12, `e0987cb`, `40b31ba`). The owner can overrule it.

## Context

The workbench arranges views in panels the analyst can tab, split, drag, float and pop out,
and the arrangement persists. Dockview 8.9.1 and FlexLayout 0.11.2 were compared on React
19.3.1 in StrictMode.

They behaved the same on: clean install and silent console under React 19; dragging a chart
tab into another group and to an edge to split, with the chart neither unmounted nor
remounted; saving, reloading and restoring the layout; a splitter drag with the chart
following (median frame 17.7 ms against 17.6 ms, none over 33 ms); floating panels and
pop-out windows; keyboard tab access.

They differed on:

| | Dockview 8.9.1 | FlexLayout 0.11.2 |
| --- | --- | --- |
| Releases in the last 12 months | 70 | 17 |
| Weekly downloads (2026-11-11 to 11-17) | 817,563 | 152,329 |
| axe-core violations | `nested-interactive` (serious), 4 nodes: its close button inside `role="tab"` | `region` (moderate), from the test page having no landmarks |
| JavaScript, gzip | 99.6 kB | 50.2 kB |
| Theming | `--dv-*` variables, set on a theme class (they did nothing on the outer element alone) | `--flexlayout-*` on `:root` |

## Decision

- **Dockview, pinned exactly.** Maintenance decides it, for a library the workbench will
  depend on for years.
- **A custom tab component from the start,** with the close control outside `role="tab"`.
  It removes the axe violation, and the workbench's tabs need their own look anyway.
- **A custom theme class** carrying the `--dv-*` variables, set from the workbench's design
  tokens for light and dark.

## Consequences

- An axe check on the workbench shell runs in the Playwright suite, so the violation cannot
  return unnoticed.
- About 49 kB more gzip JavaScript than FlexLayout, accepted for a locally served application.
- Switch to FlexLayout only if the custom tab component cannot clear axe, or a bundle budget
  is set that the extra size breaks.
