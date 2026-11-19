# 0011. Selections are server objects resolved from drawn bounds

**Status:** Accepted (owner), 2026-11-19. Built in Phase 1. Part of the chart decision's
evidence ([0005](0005-charts-uplot-regl-scatterplot.md)).

## Context

Every view in the workbench shows one shared selection. In the chart spike, the libraries
that report selected indices disagreed slightly with an independent count (+11 of 53,817
for Plotly; -1 of 50,302 for regl-scatterplot), and line traces in Plotly and sampled series
in ECharts report no indices at all.

## Decision

- A **selection** is a named server object: time ranges, direction sectors, value bands on a
  named channel, or an explicit record set, combined by union and intersection.
- The browser sends the bounds the analyst drew. The server resolves them to records, so
  every view and every statistic uses exactly the same records.
- Every chart and statistic endpoint accepts a selection, so linking two views is a
  parameter, not code written per pair of charts.
- **Data transport** is columnar (Arrow), reduced on the server to what the screen can show.
- **Preview before apply:** every data-changing operation has a dry run that returns what it
  would change, for both the interface and the assistant ([0007](0007-assistant-byok-with-approval.md)).
