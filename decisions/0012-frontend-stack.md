# 0012. Frontend stack for the new shell

**Status:** Accepted (owner), 2026-11-19. Charts and panels were accepted earlier by
measurement.

| Concern | Choice | Status and note |
| --- | --- | --- |
| Framework | React 19, Vite, TypeScript | Unchanged from today |
| Charts | uPlot, regl-scatterplot; Plotly for existing static figures | Accepted (measured): [0005](0005-charts-uplot-regl-scatterplot.md) |
| Panels | Dockview with a custom tab component | Accepted (measured): [0006](0006-docking-dockview.md) |
| Server data | TanStack Query | Accepted (owner), 2026-11-19. Replaces hand-written fetch-then-set and the single `busyLabel` |
| Interface state | Zustand, small stores per area (selection, layout, history) | Accepted (owner), 2026-11-19. Replaces the 2,260-line `useWorkspaceStore` |
| API client | Generated from the server's OpenAPI schema | Accepted (owner), 2026-11-19. Replaces the hand-written client |
| Drag and drop | dnd-kit | Accepted (owner), 2026-11-19 |
| Pipeline canvas | React Flow (in use today), with a palette, typed ports and generated forms | Accepted (owner), 2026-11-19 |
| Styling | Design tokens with light and dark themes, component-scoped styles | Themes: owner, 2026-11-17 (both, light first). Approach: owner, 2026-11-19 |
| Tests | Vitest for logic; Playwright for interaction, screenshots and an axe check | Playwright harness in place: P0-10 (`ec2824a`) |

Every new dependency is pinned to an exact version.
