# 0005. Interactive charts: uPlot and regl-scatterplot, decimated on the server

**Status:** Accepted (measured), 2026-11-19. Evidence: `spikes/chart-libraries/FINDINGS.md`
(P0-11, `7cc16dd`). The owner can overrule it.

## Context

The workbench brushes time ranges, lassos scatter points and highlights one shared selection
in every view. The owner's target scale is 5 years of 10-minute data and 60 channels:
262,800 points per channel, about 15.8 million values. Budget: first render within 1 s and
brush response within 100 ms. Measured on an Intel i5-10210U laptop with integrated graphics,
headed Chromium, median of 5 runs.

| Case | Library | First render | Brush |
| --- | --- | --- | --- |
| One channel, 262,800 points | uPlot 1.6.32 | 62 ms | 19.7 ms |
| | ECharts 6.1.0 | 123 ms | 245 ms |
| | Plotly 4.3.0 | 455 ms | 478 ms |
| Scatter, 252,665 points | regl-scatterplot 1.16.0 | 256 ms | 50 ms |
| | Plotly 4.3.0 | 407 ms | 182 ms |
| | ECharts 6.1.0 | 663 ms | 922 ms |
| 60 channels decimated to 3,200 points each | uPlot | 67 ms | 15 ms |

Plotly spends over 100 ms before its own selection callback fires, so no faster highlight can
bring it under budget.

## Decision

- **Time series:** uPlot.
- **Scatters:** regl-scatterplot.
- **Many channels or long ranges:** the server reduces each channel to minimum and maximum per
  screen bucket, and the client fetches more detail when it zooms. The full series never goes
  to the browser.
- **Selections** are the bounds the analyst drew, resolved to records on the server
  ([0011](0011-selections-on-the-server.md)).
- **Plotly** stays only for the existing server-built static figures (wind rose, profiles and
  the other `plotly_json` views) until each is replaced, loaded only by the views that use it
  (1.42 MB gzip).

## Consequences

- Highlights, axes and legends are written against uPlot's hooks; uPlot draws no highlight
  of its own. Draw a selection as shaded x ranges, not markers: the spike's marker overlay
  made uPlot's six-channel highlight 512 ms.
- Chart timings belong in local headed runs. Default headless Chromium uses a software
  renderer, where Plotly was about 37 times slower to brush, so CI asserts behaviour, not speed.
- Two libraries reported selected counts that differ slightly from an independent count (+11
  of 53,817 for Plotly; -1 of 50,302 for regl-scatterplot). This is why selections are
  resolved on the server.
