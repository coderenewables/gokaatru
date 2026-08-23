---
name: sweep-axis
description: Add or modify a scenario axis, admissibility gate, or pipeline stage in GoKaatru's Analysis Engine (the scenario sweep feature). Use when working on server/core/sweep.py, admissibility.py, scenario_*.py, sensor_selection.py, or the frontend components/sweep/ views.
---

# Analysis Engine (sweep) work

The Analysis Engine (`docs/design/analysis-engine.md`) runs GoKaatru's contestable
methodology choices — sensor selection, shear model, LTC reference, LTC method — as a
designed factorial experiment and reports the spread, decomposed by which axis actually moved
the answer. It's built and validated against real data; most remaining work is enumerated in
the design doc's status table and §7.10/§12.3/§13.5. Check there before assuming something is
unimplemented — it likely already exists.

## Before changing an axis

Read `docs/design/analysis-engine.md` §3 (axis definitions), §4 (combinatorics — why axis
levels are deliberately non-redundant, not exhaustive), and §7.13 (runconfig traceability
requirement) first. Two hard constraints apply to any axis change:

1. **Every axis level needs a canonical runconfig key.** §7.13: "a scenario the runconfig
   cannot express is a scenario the engine cannot reproduce." A new axis level with no
   runconfig representation breaks the traceability guarantee the whole engine is built on.
2. **New axis levels should probe a genuinely different failure mode**, not sample the same
   idea at a different depth (§3.A explains why sensor-selection has exactly four levels, not
   nine). If you can't articulate what distinct failure mode a new level probes, it's
   probably redundant with an existing one and just inflates the leaf count (§4's
   combinatorics table shows how fast that compounds — 8,960 leaves from 4 crossed axes).

## Adding an admissibility gate

Follow the existing seven gates in `server/core/admissibility.py` as the template. Each gate
needs:
- A `warn` and `fail` threshold (two-tier — `warn` stays admissible but flagged; `fail`
  excludes from statistics). See §7.7's table for the existing thresholds and their literature
  basis (§7.7.1, §7.7.2 show how to derive and justify a threshold, not just pick one).
- `not_applicable` handling for scenarios the gate doesn't apply to — distinct from `pass`,
  so an absent check is never mistaken for a satisfied one.
- The threshold values as fields on `GateThresholds`, written into the scenario runconfig —
  never a bare code default — so a sweep's admissibility rules stay auditable after the fact.
- A card in `GateReportView.tsx` (frontend derives its gate list from `gate_*` columns
  automatically, but the prose description is registered per-gate and a test asserts every
  backend-emitted gate has one — don't skip this or the frontend will render an unexplained
  gate).

**Read §13.6 before adding a gate based on a goodness-of-fit statistic** (R², RMSE, etc.) as
an admissibility filter across a methodology axis. The removed LTC R² gate is the cautionary
example: least-squares methods win an R² contest by construction, so a gate on R² across the
LTC-method axis systematically eliminated every non-least-squares method regardless of
whether it was wrong — it screened *which estimator you used*, not correction quality. If a
new gate could correlate with axis D (or any axis being compared), check whether it's
measuring the axis choice itself before trusting it as a quality filter.

## Adding a pipeline stage / making cleaning-adjacent choices sweep-level

Cleaning, air density, and IAV source are deliberately **not** scenario axes (§2) — they're
decided once and hashed into the fixed prefix shared by every scenario, specifically to avoid
confounding data-conditioning choices with methodology choices. If you're tempted to make
something an axis, check whether §2's argument ("does this depend on the sensor set / shear
model / LTC method?") actually applies, or whether it's a site property that belongs in the
fixed prefix instead.

## After changes

Run `validate-gokaatru`, paying particular attention to `tests/test_scenario_pipeline.py`,
`tests/test_sweep.py`, and `tests/test_oracle_harness.py` (the oracle harness pins several
subtle sweep behaviors, e.g. that variance-ratio LTC is invariant to an affine reference
transform — §7.3b). If the change affects leaf count or cost, update the combinatorics
numbers in §4 and the cost model in §13.5 rather than leaving them stale.
