# Docking layout spike: findings (P0-12)

**Question.** Which docking-layout library should the workbench build on: Dockview or
FlexLayout, on React 19?

**Answer.** **Dockview 8.9.1**, with its tabs drawn by a custom tab component and the theme
set through a custom theme class. On every functional check the two behaved the same.
What decides it is maintenance: 70 releases in the last 12 months against 17, and 817,563
weekly downloads against 152,329. Dockview's one serious accessibility violation comes from
its default tab, a close button nested inside `role="tab"`. A custom tab component removes
it, and the workbench needs its own tab anyway.

Measured 2026-11-18/19 by `run.mjs` in this folder (Playwright driving headed Chromium). The
measurements were made by a Sonnet sub-agent. This document was written from its report and
spot-checked against the results files (the axe rule ids, and the splitter timings in
`results-prod-*4.json`).

## Environment and versions

Same machine as the chart spike (`../chart-libraries/FINDINGS.md`): Intel Core i5-10210U,
Intel UHD Graphics, Windows 11, Node 22.17.0. Chromium 159.0.8154.6, headed, 1280×800. WebGL
renderer `ANGLE (Intel, Intel(R) UHD Graphics (0x00009B41) Direct3D11 vs_5_0 ps_5_0, D3D11)`;
the pages use Canvas 2D only (uPlot). Frame deltas floor at about 17.5 ms, a display of
about 57 Hz.

Exact pins: dockview-react 8.9.1 and dockview-core 8.9.1 (`dockview-react` also installs
`dockview` 8.9.1); flexlayout-react 0.11.2; react and react-dom 19.3.1; uplot 1.6.32;
@playwright/test 1.65.1; @axe-core/playwright 4.14.0; @types/react and @types/react-dom
19.3.0; @vitejs/plugin-react 4.7.0; vite 6.4.3; typescript 5.9.3.

## Method

Each library gets the same page: four panels (data tree, inspector, chart, wind rose), one
holding a uPlot chart of 262,800 generated points (`src/data.ts`, fixed seed), the others a
button and a text input each. The chart follows its panel through a `ResizeObserver` on its
own host element in both, so resizing is compared like for like. The app runs in
`<StrictMode>`. A module-level counter counts chart mounts and unmounts.

Items 1, 2, 3, 5, 6 and 7 ran on the Vite dev server, where StrictMode is active, so mount
results are reported as deltas. Item 4 and the production console check ran on the
production build (`vite preview`).

## Results

| # | Check | Dockview 8.9.1 | FlexLayout 0.11.2 |
| --- | --- | --- | --- |
| 1 | React 19 install | Clean, no `--legacy-peer-deps`; peer range `^16.8 … ^19` | Clean; peer range `^18 \|\| ^19` |
| 1 | Console in StrictMode, and production | 0 errors, 0 warnings; production silent | 0 errors, 0 warnings; production silent |
| 1 | Chart mounts after load | Dev: 2 mounts, 1 unmount, 1 live chart (StrictMode's deliberate double-run, nothing left behind). Production: 1 mount | Same |
| 2 | Drag tab into another group | Worked. Mount delta 0, unmount delta 0, same instance, 262,800 points, same checksum, still drawn | Same |
| 2 | Drag tab to an edge to split | Worked; group count 3 → 4; same outcomes as above | Same |
| 2 | Hide and show the chart's tab | 0 mounts / 0 unmounts. Detaches the chart's DOM while hidden; the component stays mounted | 0 / 0. Keeps it in the DOM |
| 3 | Save layout, reload, restore | `toJSON` / `fromJSON`, 788 bytes. Same panels in the same groups (compared as sets: group order differs after restore). JSON deep-equal, not string-identical | `toJson` / `Model.fromJson`, 889 bytes. Same groups in the same order; JSON string-identical |
| 4 | Splitter drag, 300 px in 30 steps, 5 repetitions | Median frame 17.7 ms (runs 17.5-17.8), worst 19.0 ms, 0 frames over 33 ms, 30 resize callbacks; chart ends at the host size | Median 17.6 ms (17.5-17.6), worst 19.4 ms, 0 over 33 ms, 30 callbacks; chart ends at the host size |
| 5 | Floating panel | `api.addFloatingGroup`; chart drawn, 0 / 0 mounts | `Actions.popoutTab(id, "float")` (needs `tabEnableFloat`); chart drawn, 0 / 0 |
| 5 | Pop-out to a browser window | `api.addPopoutGroup` with a `popoutUrl` page; chart drawn, follows a window resize; the source group is left empty in the main grid | `Actions.popoutTab(id, "window")`; opens a blank window that closes at once, then the real one; chart drawn, follows a resize |
| 6 | Keyboard | Tab reaches a tab; ArrowLeft/Right move; Enter/Space select; Home/End do nothing. After a group's last tab, Tab goes to the next group's tab | Same keys. After the last tab, Tab goes to the group's Maximize button |
| 6 | Roles | 3 `tablist`, 4 `tab`, `aria-selected`, `aria-controls` on all tabs; a `role="button"` close control nested in each tab; no `role="separator"` on splitters | Same tab roles; no nested buttons; 2 `role="separator"` on splitters |
| 6 | axe-core 4.14.0 | 1 violation: `nested-interactive` (serious), 4 nodes, from the close button inside each tab. `color-contrast` incomplete, 13 nodes | 1 violation: `region` (moderate), 3 nodes, from the test page having no landmarks |
| 7 | Theming from CSS variables | 116 `--dv-*` variables. The theme class sits on two nested elements and the inner one re-declares them, so variables set on the outer element alone had no effect; set them on a custom theme class | Global `--flexlayout-*` on `:root` reach every theme, float and pop-out (documented in its README) |
| 8 | Bundle, minified / gzip | JS 425,637 B / 99,619 B; CSS 142,500 B / 10,831 B (all themes) | JS 195,698 B / 50,238 B; CSS 24,154 B / 3,916 B |
| 9 | Licence | MIT | MIT |
| 9 | Releases, all / last 12 months (including pre-releases) | dockview-react 120 / 70; dockview-core 172 / 73 | 124 / 17 |
| 9 | Latest release | 8.9.1, 2026-11-17 | 0.11.2, 2026-11-16 |
| 9 | Weekly downloads, 2026-11-11 to 11-17 | dockview-react 817,563; dockview-core 1,021,585 | 152,329 |
| 9 | First published | 2024-03-05 | 2016-04-23 |

React (223,215 B / 69,248 B gzip) and uPlot (52,273 B / 23,278 B gzip) are separate chunks,
common to both.

## Weaknesses of the method

- **Item 4 does not separate them.** Both sit at the display refresh interval, so the test
  shows neither drops a frame but gives no headroom figure. It used one cheap uPlot line and
  no heavier mix of panels.
- **Item 2 moved only the active chart tab,** once into a group and once to a split. Moving
  a chart from a hidden tab, reordering within a strip and other drop targets were not tested.
- **Item 3 compared panel ids per group and the chart rectangle,** not every group size.
- **Float and pop-out were one attempt each,** with a blank `popout.html` supplied by the
  spike. Closing, re-docking and dragging a popped-out window were not tested, and the popup
  was resized by viewport emulation, not by a user.
- **Keyboard was one scripted sequence on the default tabs.** No screen reader was tested.
  FlexLayout's `region` violation comes from the test page, so Dockview not showing it says
  nothing about Dockview's landmarks.
- **Release counts measure how often versions ship,** not their quality.
- **One machine, one Chromium,** no Firefox or Safari.
- `npm audit` reports one high-severity advisory in Vite 6.4.3, the dev tooling both the spike
  and the frontend use; it is not in either candidate.

## Recommendation, and what decides it

1. **Dockview 8.9.1, pinned exactly.** Items 1 to 7 passed the same way for both, so they do
   not decide. Maintenance does: 70 releases in 12 months against 17, and 817,563 weekly
   downloads against 152,329, for a library the workbench will depend on for years.
2. **Custom tab component from the start.** It removes the `nested-interactive` violation
   (the close control moves out of `role="tab"`), and the workbench's tabs need their own
   look anyway. The axe check runs in the workbench's browser tests (P0-10's harness), so
   the violation cannot return unnoticed.
3. **A custom theme class carrying the `--dv-*` variables,** set from the workbench's
   design tokens for light and dark, not the stock theme classes (item 7).
4. **Cost accepted:** about 49 kB more gzip JavaScript than FlexLayout (99.6 kB against
   50.2 kB) and 7 kB more CSS. For a local application served from the same machine this
   ranks below maintenance.
5. **Choose FlexLayout instead** only if the custom tab component turns out not to clear axe,
   or if a bundle budget is set that the extra 49 kB breaks.

These choices are recorded as an architecture decision in P0-13.
