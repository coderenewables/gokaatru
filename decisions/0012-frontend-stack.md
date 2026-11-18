# 0012. Frontend stack for the new shell

**Status:** Proposed, except where marked. Designed in the build plan; to be confirmed before
Phase 2 starts.

| Concern | Choice | Status and note |
| --- | --- | --- |
| Framework | React 19, Vite, TypeScript | Unchanged from today |
| Charts | uPlot, regl-scatterplot; Plotly for existing static figures | Accepted (measured): [0005](0005-charts-uplot-regl-scatterplot.md) |
| Panels | Dockview with a custom tab component | Accepted (measured): [0006](0006-docking-dockview.md) |
| Server data | TanStack Query | Proposed. Replaces hand-written fetch-then-set and the single `busyLabel` |
| Interface state | Zustand, small stores per area (selection, layout, history) | Proposed. Replaces the 2,260-line `useWorkspaceStore` |
| API client | Generated from the server's OpenAPI schema | Proposed. Replaces the hand-written client |
| Drag and drop | dnd-kit | Proposed |
| Pipeline canvas | React Flow (in use today), with a palette, typed ports and generated forms | Proposed |
| Styling | Design tokens with light and dark themes, component-scoped styles | Theme: owner, 2026-11-17 (both, light first). Approach proposed |
| Tests | Vitest for logic; Playwright for interaction, screenshots and an axe check | Playwright harness in place: P0-10 (`ec2824a`) |

Every new dependency is pinned to an exact version.
