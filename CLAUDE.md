# GoKaatru — CLAUDE.md

Context for Claude Code working in this repository. Read this before making changes; it
encodes conventions the codebase enforces strictly and that reviewers (including past
audit passes) have checked for by hand.

## What this is

GoKaatru ("Wind" in Tamil) is an **open-source Wind Resource Assessment (WRA) platform**:
it turns a measured wind campaign into a long-term-corrected, hub-height, ensemble-blended
wind resource characterization suitable for feeding an Energy Yield Assessment. It follows
IEC 61400-12-1 / 61400-12-2 conventions and is built for **bankable rigor** — numbers a
bank's technical advisor will try to break.

Two parts, one logic core:
- **`server/`** — Python MCP server (FastMCP) + FastAPI web API. 232 tools across ingest,
  cleaning, statistics, shear/extrapolation, ERA5+MERRA-2 reanalysis, homogeneity, 5 LTC/MCP
  algorithms, ensemble, clipping, uncertainty, mapping, visualization, BrightHub integration,
  a scenario **sweep/Analysis Engine**, and a WindKit tool surface (~180 tools).
- **`frontend/`** — React 19 + Vite + TypeScript app, navigated by a **3-phase primary rail**
  (`PhaseRail`: Prepare / Run / Interrogate) plus two independent entries (Canvas, Copilot).
  **Prepare** merges data import, cleaning, reanalysis, Sensor Overview and the Stepper into
  one screen with an internal section switcher, ending in a stamped fixed-prefix hash.
  **Run** merges the Sweep Designer and its live monitor. **Interrogate** merges the Spread
  Explorer, Sensitivity, Gate Report and Spread Summary under one shared metric switch.
  **Canvas** is the editable React-Flow DAG runner, populated *only* by explicitly loading
  one scenario's exact config from a completed sweep ("Load from sweep") or by manually
  editing/rebuilding a config — no more auto-built default pipeline — plus a "Compare runs"
  toggle (saved workflow-run comparison, retired as its own tab). A ⌘K command palette
  (`CommandPalette`) jumps to any phase/stage/preset/metric/gate or falls through to
  "Ask Copilot". See "Current state" below (2026-09-06 and 2026-09-07 entries) for the full
  rationale.

**Single trusted user, local deployment.** No auth layer; the session id is the only
credential. See README's "Deployment model" section before ever discussing hosting this for
multiple users.

**Three companion documents, each with a distinct job** — read the one that matches your
question rather than guessing from this file alone:
- **This file (`CLAUDE.md`)** — conventions the codebase enforces + current project state.
- **`CODEDOC.md`** — committed, self-contained code structure reference: every `server/core`
  and `server/tools` module, the route inventory, data flow, frontend structure, and a
  maintenance-notes section tracking cleanup passes and refactor candidates. Read it for "how
  is this organized" questions; it stays in sync with the tree because it's committed and
  checked, unlike `docs/`.
- **`README.md`** — the functional spec: full tool/endpoint inventory and every disclosed
  default with its measured magnitude.

## Core architectural principle: dual-interface, single logic

MCP tools and FastAPI routes call **identical business logic** in `server/tools/` and
`server/core/`. Never write UI-specific logic in the MCP layer, and never add a capability
to one interface without the other. New analytics go in `server/tools/` (or `server/core/`
for pure math) first, then get exposed via both `server/main.py` (MCP) and
`server/api/routes/` (HTTP).

## Layout

```
server/
├── main.py              # FastMCP server, tool registration
├── api/                 # FastAPI app; routes/ has ~13 route files (~200 endpoints)
├── core/                # Pure math + orchestration: formulas, regression, spatial,
│                         #   validators, runconfig contract, executor (workflow DAG),
│                         #   admissibility (sweep gates), sweep.py, scenario_*.py,
│                         #   sensor_selection.py, powercurve.py, reanalysis.py
├── tools/                # ~20 tool modules (data_io, cleaning, shear, extrapolation,
│                         #   era5, ltc, ltc_ml, ensemble, clipping, uncertainty,
│                         #   advanced_analysis, homogeneity, brighthub, ...)
│   ├── visualization/    # Plotly figure builders — a themed PACKAGE, not a single file
│                         #   (split from a 1,856-line module 2026-09; __init__.py wires the
│                         #   @mcp.tool() wrappers and re-exports every builder, so every
│                         #   existing `server.tools.visualization.*` import path is unchanged)
│   └── windkit/          # ~180 pass-through wrappers around the windkit PyPI package
├── state/                # session.py (SessionState), manager.py (SessionManager,
│                         #   ContextVar-bound), dataset_pool.py
└── schemas/              # Pydantic v2 contracts

frontend/src/
├── components/           # AppHeader, PhaseTabs, Stepper, stages/, results/, sweep/,
│                         #   WorkflowView (Canvas), CopilotView, CompareView, ...
├── store/                # useWorkspaceStore (Zustand, ~2000 LOC), useSweepStore
├── lib/                  # api.ts (Axios client), configSync, stages, workflow,
│                         #   defaultWorkflowPlan, sweepApi, sweepAnalysis, copilotAgent
└── types/analysis.ts     # canonical config schema + response interfaces

tests/                    # 74 backend test files (pytest) — includes oracles.py, an
                           #   independent-implementation oracle harness used to verify
                           #   fixes without importing from server/. Some depend on
                           #   gitignored fixtures under data/uploads/ (e.g. Boxkite,
                           #   WB-ESMAP) and error at setup on a fresh clone without them —
                           #   an environment condition, not a code failure.
docs/                     # LOCAL ONLY — gitignored (see below)
```

Full module-by-module detail (every `server/core`/`server/tools` file's responsibility, the
complete route inventory, frontend file layout): `CODEDOC.md`.

`runconfig` (defined once in `server/core/runconfig.py`) is the single source of truth for
site metadata; the frontend's convenience fields are derived mirrors, enforced by
`tests/test_runconfig_contract.py`. Session state (`SessionState`) holds all working data for
one analysis; it is a mutating singleton per session, bound via a `ContextVar`
(`server/state/session.py`).

## `docs/` is gitignored — local working notes only

`docs/` (audit findings, verification reports, design docs like the Analysis Engine spec) is
in `.gitignore` and **never reaches the remote**. It's real, current, load-bearing context —
just not shared history. Treat it as authoritative for understanding *why* things are the way
they are, but know a fresh clone won't have it. Key files:

- `docs/audit/00-plan.md` + `01-ledger.md` … `10-uncertainty-energy.md` — the completed
  10-step physics/logic audit (convention ledger → ingest → cleaning → statistics → vertical
  profile → air density → reanalysis → LTC → ensemble/clipping/IAV → uncertainty/energy).
- `docs/audit/FIXES.md` — the applied-fix log, round by round, with the measured magnitude of
  each defect.
- `docs/audit-verification-report.md` — independent re-verification of every fix claim
  against the code, plus the honest list of what's still open.
- `docs/design/analysis-engine.md` — the design + build log for the scenario Sweep / Analysis
  Engine feature (§1–§13), including two real-data validation runs and their findings.

(`CODEDOC.md`, by contrast, **is** committed — it's the code-structure reference that survives
a fresh clone; see the companion-documents note above.)

## Domain conventions this codebase enforces

These aren't style preferences — violating them is what the audit exists to catch.

1. **Refuse rather than guess.** Sub-six-month LTC, ambiguous DD/MM dates, undeclared
   timezone, degenerate TLS — these raise instead of returning a number. Don't add silent
   fallbacks for cases the code currently refuses.
2. **Every default/clamp/assumption that changes a number is disclosed.** If you add a
   clamp, threshold, or fallback, add: (a) a named constant (not an inline literal), (b) a
   response field reporting whether/how it fired, and (c) a row in README's "Defaults that
   affect results" or "Disclosure fields" table. Search README for the pattern before adding
   a new one — there are ~30 existing examples to match.
3. **No silent recomputation.** Derived artifacts (shear tables, hub series, LTC results)
   carry a `data_version` stamp (`stamp_derived` / `staleness_report()` in
   `server/state/session.py`) rather than being auto-recomputed when upstream data changes.
4. **Methodology choices get measured, not asserted.** When a finding involves "which is more
   correct," the fix is usually to measure the magnitude on real/synthetic data and report it
   (see `docs/audit/FIXES.md` for the pattern — nearly every entry has a measured percentage).
5. **New physics/statistics code needs an oracle-backed test.** `tests/oracles.py`
   deliberately imports nothing from `server/` — it's an independent reference
   implementation. New findings/fixes in core math get a reproducing test built against it.
6. **No TODO/FIXME/HACK markers anywhere in the tree.** This is enforced by convention, not
   tooling — grep comes back empty; keep it that way.
7. **Comments only for non-obvious WHY**, never restating what the code does. The codebase's
   own style is dense, precise, no filler — match it.

## Running things

```bash
# Backend
conda activate gokaatru
pip install -e ".[ml,dev]"
python -m server.main                                   # MCP server (stdio)
python -m uvicorn server.api.main:app --host 127.0.0.1 --port 8000   # web API

# Frontend
cd frontend && npm install && npm run dev                # :5173, proxies /api -> :8000
```

## Validating a change

```bash
python -m ruff check server/ tests/
python -m pytest tests/ -v
python -c "import asyncio; from server.main import mcp; print(len(asyncio.run(mcp.list_tools())), 'tools')"

cd frontend && npm run test          # vitest
cd frontend && npm run build         # tsc --noEmit && vite build
```

Current baseline (verified 2026-09-14, after the LTC-column / SpeedSort / sweep-tools fixes):
1048 backend tests passing / 2 skipped, 255 frontend tests passing, frontend typecheck clean,
232 MCP tools registered, and `ruff check server/ tests/` clean. These numbers move as the project
grows — `validate-gokaatru` always re-derives the live count rather than trusting any written
baseline, this one included. Backend count assumes the gitignored `data/uploads/` fixtures are
present (see the `tests/` layout note above); without them, expect setup errors on the tests
that use them, not a lower clean pass count.

**Ruff was not clean before 2026-08-25** — 185 findings (97 E501, 36 I001, 31 F401, 17 W292,
3 F841, 1 F811) had accumulated because `ruff>=0.1` is unpinned and the check was not being
run to zero. They are all fixed now; keep it at zero rather than letting a second wall build.

## Current state (last verified 2026-09-14)

**2026-11-14: hub extrapolation no longer drops sub-gate records (T1, decision D1, pending owner sign-off).**
The 3.0 m/s shear gate was applied to the extrapolation output as well as the fit: `computed[below_gate] = np.nan`
deleted every record whose reference speed was below it, so the hub series lost its low end and every long-term
correction was fitted on a truncated series (Launakalana at 120 m: 25% of records, long-term mean +5.8% to +12.8%).
The gate now governs the fit only; sub-gate records are extrapolated with the table's exponent and counted in
`below_shear_gate` / `records_below_extrapolation_gate`. Measured by a new held-out-height oracle
(`tests/test_heldout_height.py`, predicting a withheld sensor from the two below it, before → after): Launakalana 80 m
+23.08% → -0.43%, coverage 69.7% → 100%; Boxkite 250 m +4.91% → -0.40%, coverage 93.7% → 100%. Hub series and
`extrapolated` counts change on every campaign, so sweeps and LTC results produced before this change are not
comparable with ones after it. The shear fit gate itself is unchanged.

**2026-09-14: the sweep's LTC was correcting the wrong series, and three fixes followed.**
Found by investigating a user's question about the Interrogate page — "why is LTC method
the only contributor to the variance?" — on a real 167 m lidar campaign with sensors at
140/160/180/200 m. The page showed LTC (D) at 100% and the other four axes at 0.0%. Three
of those axes genuinely had one level among the admissible set (and axis B had two
*designed* — every `log_law_momm` scenario was rejected by the `roughness_clipping` gate),
so 0% was correct for them by construction. Axis A1 had two real levels, produced
genuinely different shear (α 0.086518 vs 0.084952), and still showed **0.000 swing with
every downstream number bit-identical to 16 digits**. That was a defect, not a finding.

1. **`_resolve_ltc_columns` re-derived the measured column as "the highest-height speed
   sensor in `sensor_mapping`".** A hub column is never in that mapping — extrapolation
   appends it to `timeseries_df` — so the resolver could not return one at any site, ever.
   The sweep computed the hub series in `extrapolate` and then fitted every LTC on
   `Spd_200m`, publishing the result as the hub answer. Measured: the 200 m level is
   **+0.185 m/s (+2.05%)** above the 167 m hub level (9.2166 vs 9.0316 m/s), and it
   propagated into `long_term_mean_speed_mps`, the indicative AEP and the capacity factor.
   It also made axes A1, A2 and B unable to move *any* published metric, because
   everything downstream of shear and extrapolation was bypassed — which is precisely why
   the page attributed 100% to the one axis still able to vary. Now the hub series is
   used, and a missing one is **refused by name** rather than substituted (convention 1;
   confirmed with the user before choosing refusal over a disclosed fallback). This also
   hit `/scenarios/run`, which never extrapolates at all: moving hub height there without
   re-extrapolating is now a 400 naming the missing column, pinned by a test.
2. **SpeedSort ran direction-agnostically in every sweep ever executed.** The sweep called
   every non-XGBoost algorithm as `runner(state, short, long)`, so `long_dir_col`
   defaulted to empty and SpeedSort lost the per-sector transfer functions that are the
   reason to choose it — while XGBoost kept its directional feature, so axis D was
   comparing them on unequal terms. Three call sites dispatched on the algorithm name
   independently and this was the one that drifted; they now share
   `DIRECTIONAL_LTC_ALGORITHMS` and a test asserts no inline name dispatch remains.
   Separately, `mapping.get("direction_col")` never matched (the slot is `dir_col`), so
   the measured direction column was always "" — latent, since nothing in that path
   consumed it, and now fixed.
3. **The Copilot could not see a sweep at all.** Asked the question above it answered from
   live session state — where a sweep leaves no trace, each leaf running in a forked
   context that never writes back — and confabulated an explanation about the spread
   between anemometers, including the true-but-irrelevant "LTC algorithms run: none". The
   variance decomposition existed only in `frontend/src/lib/sweepAnalysis.ts`. It is now
   `server/core/sweep_analysis.py`, exposed as `POST /sessions/{id}/sweep/{id}/spread` plus
   three read-only tools (`list_sweeps`, `get_sweep_summary`, `analyze_sweep_spread`), and
   **the TypeScript copy is deleted** — the Interrogate page fetches it, so there is one
   implementation rather than two that must agree. Tool count 229 → 232; read-only tier
   48 → 51.

`get_sweep_summary` deliberately reports `levels_designed` vs `levels_admissible` per axis
and the gate tally, because the original confusion was reading "0.0%" as "this choice does
not matter" when it meant "this choice was never varied among the admissible set".

**A security fix fell out of #3**: `_sweep_dir` did no path confinement, so a sweep id of
`../../<other session>/sweeps/<id>` read another session's manifest and every scenario
runconfig in it. Only reachable from an authenticated route before — but a sweep id is now
an input to a chat tool, where it can originate in model output. Confined the same way as
`_confined_file_path`, with traversal tests.

**Caveat, documented rather than enforced** (the user's call): fixes 1 and 2 change the
numbers every previously-stored sweep produced. There is no version stamp on the manifest,
so **any sweep run before 2026-09-14 is not comparable with one run after** — its LTC was
fitted on the top sensor rather than the hub series, and its SpeedSort was
direction-agnostic. Re-run rather than compare.

One deliberate UX regression: the decomposition was a synchronous `useMemo` and is now a
round-trip, so a metric switch or filter toggle is no longer instant. Cached per
sweep+metric+row-selection in `useSweepStore.spread`, so each distinct view is fetched once.


**2026-09-08: a CSV-only campaign can now be analysed — minimal Task 43 data model**
**builder.** Without a data model nothing populates `sensor_mapping` or `state.timezone`
(`_extract_timezone` is the only thing that ever assigns the latter), so `completed_steps`
never reached `datamodel` and every height-indexed stage had no heights: a bare CSV was a
dead end that could only *display* a sensor list. New `server/core/datamodel_builder.py`
(pure logic — header inference, spec validation, Task 43 emission) plus
`server/tools/datamodel_builder.py` (`draft_data_model`, `build_data_model`) and
`GET|POST /sessions/{id}/datamodel/draft|build` in `api/routes/uploads.py`. Tool count
227 → 229.

**It builds a document, not state.** The output is a real Task 43 subset written into the
session uploads dir and then fed through the *existing* `_parse_datamodel`, so one code
path populates session state and the declaration survives as a downloadable, auditable
artifact carrying `BUILDER_PROVENANCE_NOTE` ("drafted by header inference and declared by
the analyst; not from an instrument record"). Writing `sensor_mapping` directly would have
been faster and is exactly the divergence the single-logic principle forbids.

**The decisive test is round-trip equivalence** (`tests/test_datamodel_builder.py`): for
all three reference campaigns, a data model built from *nothing but the CSV headers*
produces a `sensor_mapping` identical to the campaign's own hand-authored data model.
Getting that to hold surfaced two real defects in shared code, both fixed with the
magnitude measured rather than asserted:

- **Boom-pair coverage ties were broken by document order.** `_resolve_boom_pair`'s
  docstring promised an alphabetical tie-break but the coverage branch returned the first
  candidate it saw and never reached it. Ties are the *normal* case — every boom pair in
  Horns Rev and Launakalana ties **exactly**, because both booms log on one channel
  schedule — so which sensor represented a height was decided by JSON ordering: **+1.15%**
  of mean wind speed at Horns Rev 30 m (`Spd_SW_30m` 8.302 → `Spd_NE_30m` 8.398 m/s) and
  −0.21% at Launakalana 60 m. Ties now fall through to the name and are reported as a
  distinct `coverage_tie_name_alphabetical`, so a coverage figure that decided nothing
  does not read as if it had. Constants `RESOLUTION_*` in `data_io.py`.
- **`sd_col` was `f"{speed}_sd"` unconditionally**, existing or not — Boxkite's mapping
  named `Spd_250m_sd` against a CSV with no standard-deviation channels at all. Inert
  (the icing rule skips a missing column) but it travelled into `runconfig` as fact. Now
  resolved declared-if-present → suffix-if-present → `None`, reading Task 43's own
  `logger_measurement_config[].column_name` with `statistic_type_id: "sd"` rather than
  inventing a key. **The existence check is load-bearing**: Horns Rev *declares*
  `wind_speed__sd__062__…` while its CSV holds `Spd_62m_sd`, so trusting declarations
  blindly would have regressed a reference campaign. With no timeseries loaded existence
  cannot be checked and the convention still applies (preserving `test_sensor_mapping`'s
  no-timeseries expectations).

Inference is deliberately a *draft*, never an answer: `draft_columns` groups columns by
stem-plus-statistic (which is what pairs `WS_80m_Avg` with `WS_80m_SD` — the old `{speed}_sd`
convention could only ever pair `Spd_80m` with `Spd_80m_sd`), classifies quality flags and
logger diagnostics as ignored *before* any instrument pattern (`Qual_Spd_58m_quality` read
as a sensor would invent a second 58 m anemometer and turn a clean height into a boom pair),
and returns `height_m: None` with a reason rather than defaulting — 0 m is a real height.
`build_data_model` refuses by name on a missing height, unknown measurement type, duplicate
column, statistic column absent from the data, or missing timezone.

Scope, confirmed with the user before building: boom orientation and `is_primary` are
collected; **install/removal dates are not** — an analyst holding only a CSV does not know
them, and supplying them would fake a `datamodel_deployment` availability basis instead of
the honest `period_of_record` fallback (see the availability entry below). Calibration,
uncertainty, mast geometry and logger provenance are out of scope: nothing in this tree
reads them, and adding them would be building a Task 43 *exporter*, a different feature.

Frontend: `DataModelBuilder.tsx` is a fourth import path in `DataLoadView` ("Build data
model"), with `dataModelDraft` / `loadDataModelDraft()` / `buildDataModel()` on the store.
Columns it could not read are disclosed with the reason in a `<details>` block rather than
hidden. **One thing checked and found *not* to be a bug**: `DataLoadView` reads
`summary.sensor_mapping_loaded`, which looks wrong against `SessionSummaryResponse`'s
`datamodel_loaded` — but the store's `summary` is the `/summary` payload
(`_get_analysis_summary`, `tools/config.py`), which does send `sensor_mapping_loaded`. Two
different summary shapes; the code is correct. Verified together: 1016 backend / 2 skipped,
251 frontend (29 files), ruff clean, 229 tools, `vite build` clean.

**Live end-to-end pass against the running server (2026-09-08), on a deliberately
non-conventional CSV** — `WS_80m_Avg` / `WS_80m_SD` / `WS_80m_Max` / `WD_80m_Avg` /
`AirTemp_10m_Avg` / `Qual_WS_80m_quality` / `LoggerBattVolt`, i.e. sharing nothing with the
`Spd_58m` convention the three checked-in fixtures happen to use. Result: draft read every
height and type correctly, paired `WS_80m_SD` to `WS_80m_Avg` by stem (the old
`{speed}_sd` convention would have produced the non-existent `WS_80m_Avg_sd`), demoted
`_Max` to a statistic, and refused a sensor slot to both the quality flag and the battery
channel. Build → `completed_steps` reached `datamodel`, `site_utc_offset_hours` = 1.0 from
the declared offset, and **`shear/calculate` recovered α = 0.15999 against the 0.16 baked
into the synthetic data** — the stage that is unreachable without a data model. The emitted
artifact re-uploads through `/uploads/datamodel` as an ordinary data model and yields the
identical mapping. All three refusals (no height / no timezone / unknown column) returned
400 naming the offending column.

**The port-8000 dev server was serving stale code again** — started before any of this
work, so neither new route existed on it (`/openapi.json` had no `datamodel/draft`). This
is the same trap recorded further below; the fresh-process test suite passing says nothing
about what the running server has. Restarted the same way (no `--reload`, single process,
no orphaned worker), and it now serves current code. **Note for the next session: Vite is
bound to `::1` only, not `127.0.0.1`** — curl against `127.0.0.1:5173` fails with a
connection error that looks like a dead server; use `http://[::1]:5173`.

**Still not verified: a visual browser pass.** No browser-automation tool was available, so
layout, spacing and the rendered look of the builder table remain unconfirmed — everything
above is the serving and API layers, not pixels.

**2026-09-08: `availability_90` now measures over each sensor's own deployed period**
(closes the §12.3 finding). `availability_pct` divided by the *total* record count, charging
every sensor for the campaign before it was installed. New `availability_measure()` in
`core/sensor_selection.py` returns an `AvailabilityMeasure` (pct + basis + record counts) over
the sensor's deployment window, taken from the Task 43 datamodel's `date_from`/`date_to` where
present and the column's own first-to-last record otherwise; `_build_sensor_inventory`
(`tools/data_io.py`) now carries those dates, which nothing read before. **Measured on the
three reference campaigns**: Horns Rev — where `Spd_58m` predates the rest of the mast by ~13
months — went from best-sensor **87.1% with 0 of 5** sensors clearing the floor to **100.0%
with 4 of 5**, so the policy went from unavailable to usable. Boxkite is **unchanged at
89.7%** and still fails: its losses are genuine scattered gaps, not late installation, which
is the correct answer rather than a fix that flatters the data. The audit's "unreachable on 2
of 3 campaigns" is therefore now 1 of 3, and that one is a real data-quality fact. The basis
travels with every figure (`availability_basis`) because a deployed-period percentage and a
whole-campaign one are not comparable. README's defaults table carries the measured row.

**2026-09-08: the Copilot's unclassified-tool guard was vacuous, and is now real.**
`_unclassified_tools()` promised (in its own docstring) that "a new tool that nobody
classified is discoverable in a test instead of at review time." It derived its input from
`_build_registries()`'s `callables`, which that function had **already filtered to classified
tools only** — so it subtracted a set from itself and could never return anything. Its test
asserted `== set()` and passed vacuously for every unclassified tool ever added, including
`get_fixed_prefix_hash` two days earlier. Fixed by measuring against the MCP registry itself
(new cached `_load_mcp_tool_specs()` / `_registry_tool_names()`), which immediately surfaced
**165 of 227 tools invisible to chat**. The old `== set()` assertion was replaced by the
invariant it was meant to express — unclassified tools must be neither advertised nor
executable — plus a check that the guard is capable of failing at all.

With the guard working, the high-value read-only analysis tools were classified: the ten
`compute_*` diagnostics (`energy_metrics`, `mcp_readiness`, `extreme_winds`, `qc_diagnostics`,
`sensor_comparison`, `mast_effects`, `atmospheric_conditions`, `wind_ramps`,
`wind_persistence`, `energy_sensitivity`) plus `get_fixed_prefix_hash` — all verified pure
reads (no session mutation, no filesystem, no network) before being added. This needed
`advanced_analysis`, `atmosphere`, `diagnostics` and `scenario_result` adding to
`_build_registries`'s module list, which is what makes a classified tool *executable* rather
than merely advertised. Read-only tier **36 → 47**, total exposed **62 → 73**. The remaining
154 unclassified are deliberate and now visible: 142 WindKit wrappers, plus all 12
BrightHub/EarthDataHub tools, which are excluded because the read-only tier's contract is "no
network" and the credential tools would hand an injected prompt a view of session auth state —
pinned by a test.

**2026-09-08: Canvas can also load a config from a local file.** A fourth Canvas entry
point, "Upload config" (`WorkflowView.tsx`), sits alongside Load from sweep/Edit config/
Rebuild from config: picking a `.json` file reads it (via `FileReader` — `Blob#text()` isn't
implemented consistently across jsdom/Node's differing `File` globals in tests, so
`FileReader.readAsText` is used for portability, not just in tests) and feeds the raw text
into the **same** "Edit config" textarea/"Save and run" flow, unvalidated at upload time —
confirmed with the user before building: load-into-editor-for-review beats a one-click blind
execute, so a bad file surfaces the existing "Configuration must be valid JSON" check instead
of silently doing nothing or running garbage. No new validation path was added; this is purely
a new way to fill the same textarea `saveConfigAndRun` already reads from. 240 frontend tests
(28 files, +4 over the 2026-09-07 baseline), tsc clean, `vite build` clean. No backend changes.

**2026-09-07: Canvas narrowed to "load a config from the sweeps and run."** Canvas
previously had a second, silent population path alongside manual editing: `prepareDefaultWorkflow`
auto-built a generic default DAG from bare session state (sensor pairing, LTC algorithms,
etc.) and jumped the user into Canvas whenever `refreshWorkspace`/`saveConfig` next ran, and
`saveConfigAndSetup` (Prepare's Data loading "Save config and setup" button) built the same
kind of default graph inline as a side effect. Both are removed — Canvas is now populated
only by explicitly loading one scenario's exact config from a completed sweep (new "Load
from sweep" button/picker in `WorkflowView.tsx`), or by the existing manual paths (Edit
config / Rebuild from config), which are unchanged. Rationale: the 2026-09-06 redesign above
already made Prepare's "Pipeline" section (the Stepper → `StageShell`) the primary way to
walk through and run every stage independently, leaving the auto-build both redundant and in
tension with Canvas's real value — taking one exact scenario's config and running/editing it
as a graph, not re-deriving a generic plan from scratch.

Two new store actions, both pure composition of existing machinery (no new persistence or
graph-building logic): `useSweepStore.previewSweepScenarios(baseUrl, sessionId, sweepId)`
peeks a sweep's scenario list via the existing `getSweep()` **without** touching
`manifest`/`rows`/`phase` — deliberately not reusing `openSweep()`, which mutates the same
state Run/Interrogate read, so a picker peek from Canvas must not silently change what those
screens show. `useWorkspaceStore.loadScenarioIntoCanvas(sweepId, configHash)` fetches the
scenario's materialised runconfig (`getScenarioRunconfig`, already existed) and sequences the
existing `replaceWorkflowRunConfig()` → `rebuildWorkflowGraph()` pair — the same pipeline the
pre-existing "Edit config" → "Save and run" flow already used, confirmed server-side
(`server/api/routes/workflow_execution.py`'s `PUT /run-config`) to safely ignore the
scenario runconfig's extra `scenario`/`admissibility` keys rather than choking on them.

`buildDefaultWorkflowConfig`/`defaultWorkflowPlanKey` (`lib/defaultWorkflowPlan.ts`) were
**not** deleted — `saveConfigAndSetup` still calls `buildDefaultWorkflowConfig` to seed
sensible shear/LTC config defaults (sensor pairing, algorithms, columns) that the Stepper's
own stage views read to have something to run; only the graph-building half of what that
function's output used to feed (`createWorkflowGraph` + `workflowNodes`/`workflowEdges`) was
removed from that flow. The `defaultWorkflowStatus` field and the `prepareDefaultWorkflow`
action were deleted outright — nothing else referenced either. Verified: 236 frontend tests
(28 files, +10 tests / +2 files over the prior baseline), tsc clean, `vite build` clean. No
backend changes — `getScenarioRunconfig`'s route and `replace_workflow_run_config` were
already exposed and untouched.

**2026-09-06: frontend redesigned around a 3-phase primary IA (Prepare / Run /**
**Interrogate), replacing the old 10-tab `PhaseTabs`.** Prompted by a Claude Design mockup
(`Gokaatru Workspace v2.dc.html`) whose own design notes observed that four of the ten tabs
were the same underlying activity seen from different angles (Canvas runs the pipeline,
Stepper inspects one stage of it, the Analysis Engine held six sub-tabs of its own, Compare
was a near-subset of the Spread Explorer) with nothing signalling where the user was in the
work. Implemented test-first (every new component's test file was written and confirmed
failing before the implementation landed), and everything built on **composition, not
rewrite**: `SweepDesigner`, `SweepMonitor`, `SpreadExplorer`, `SpreadSummaryView`,
`SensitivityView`, `GateReportView`, `DataLoadView`, `StageShell`, `SensorReviewView`,
`ResultsView` and `CompareView` all kept their existing internals and existing tests; new
phase-container components (`PrepareView`, `RunView`, `InterrogateView`, `PhaseRail`,
`CommandPalette`) import and arrange them.

Two findings reshaped the mockup's literal proposal during implementation, not just its
visuals:
- **CompareView turned out not to be a subset of SpreadExplorer.** It compares saved
  Canvas/workflow-run *executions* (node-level status, config diffs); SpreadExplorer compares
  sweep *scenarios* (gate admissibility, runconfig). Retiring the Compare tab therefore meant
  relocating its capability into **Canvas** (`WorkflowView.tsx`, behind a local "Compare
  runs" toggle that swaps the DAG canvas for `<CompareView/>` unchanged) rather than folding
  it into Interrogate.
- **The mockup's "stamped prefix hash" wasn't computable before a sweep ran.**
  `fixed_prefix_hash()` (`server/core/scenario_result.py`) previously only ran at
  sweep-launch time and only surfaced via the manifest. A new endpoint —
  `GET /sessions/{id}/sweep/prefix-hash` (`server/api/routes/sweep.py`) plus a matching MCP
  tool `get_fixed_prefix_hash` (`server/tools/scenario_result.py`, new file) — exposes it
  from live session state pre-sweep, so Prepare's stamp banner and three of its four
  prefix-stat tiles (reanalysis sources, cleaning-actions count, the hash itself) are real
  numbers, not mockup placeholders. Both the route and the tool converge on the same
  `fixed_prefix_hash()` call rather than duplicating logic. This is the one place the sweep
  engine gained an MCP counterpart — it otherwise still has none (`server/core/sweep.py`
  and friends are HTTP-only), a pre-existing gap that was deliberately not closed wholesale
  here, only not repeated by the one new capability this work added.

Two navigational gaps the mockup itself didn't address were resolved during implementation,
not left as regressions: **How To** (previously its own tab) is now a header-triggered
overlay (`toggleHowTo`/`howToOpen` on the store) rather than a phase, since it's reference
material, not one of the three phases; **Results** (the read-only report) became a 4th
Prepare section alongside Data loading / Pipeline / Sensor Overview, since it's the tail end
of the same fixed-prefix pipeline Prepare already owns.

Two deliberate simplifications versus the mockup, both disclosed rather than silently
diverged: **no ETA figure ships anywhere in Run** — `estimate()` only ever returns
`{leaf_count, prefix_count}`, and the mockup's `hours = leaves * 0.0009` formula had no basis
in this codebase; inventing one would have been exactly the kind of undisclosed magic-number
problem the audit process exists to prevent, so it was dropped instead (guarded by a
regression test in `RunView.test.tsx`). **Real sweep preset names are used** ("Quick look" /
"Standard EYA" / "Exhaustive" from `useSweepStore`'s `SWEEP_PRESETS`), not the mockup's
illustrative "Smoke test".

New/changed store shape: `useWorkspaceStore`'s `activeTab: TabId` (10 values) became
`activePhase: PhaseId` (5 values: `prepare | run | interrogate | canvas | copilot`); the 7
call sites that used to set `activeTab` directly (session reset, credential-gate bounces,
cleaning completion, workflow prepare/execute) were each updated by hand rather than
mechanically, since several now need to set a second field (`selectedStage` and/or the new
`prepareSection: "data" | "pipeline" | "sensors" | "results"`) that a blind rename would have
missed. New fields: `prefixHash`, `reanalysisSourcesForPrefix`, `cleaningActionsCount`,
`loadPrefixHash()` (Step 1's endpoint, wired to re-fetch after `deleteSensors`);
`prepareSection`/`setPrepareSection`; `howToOpen`/`toggleHowTo`; `paletteOpen`/
`setPaletteOpen`. `PhaseTabs.tsx` and `AnalysisEngineView.tsx` were deleted (superseded by
`PhaseRail.tsx` and the three new phase views respectively) — the 6 components
`AnalysisEngineView` used to compose were not deleted, only re-homed.

All of the above verified together: 939 backend tests / 2 skipped, ruff clean, 227 MCP tools
(226 → 227, the one new `get_fixed_prefix_hash` tool); 226 frontend tests / 27 files, tsc
clean, `vite build` clean. Not yet done: a live-browser pass (`npm run dev`) — everything
above is verified by the test suite and a clean production build, not by looking at the
rendered app, so treat the visual polish (spacing, the mockup's exact card/typography
details) as unverified until someone actually opens it.

**Physics/logic audit: complete.** All 10 steps done, 80 finding IDs raised, 69 fixed in the
original rounds, 2 measured-away-to-nothing, 2 partly-declined-by-design (no AEP/energy-
uncertainty — a scoped methodology decision, not a defect). A follow-up pass (2026-08-23,
`docs/audit/FIXES.md` Round 12) closed the verification report's residual list of 7: **F-15**
(shear-sensor separation floor), **F-16** (union-typed executor params), **F-23**
(extrapolation now honours the shear speed gate) and **F-26** (roughness/aggr-MoMM fallback
disclosure) are fixed; **F-09** (canvas edges are advisory) is mitigated — a tie between
edge-less nodes now breaks on pipeline stage before id, and the tie-break is itself recorded
(`stage_disambiguated_nodes`), though same-stage ties still resolve by id and a full per-tool
dependency graph remains future work; **F-24** has better aggregate visibility
(`record_counts` on the extrapolation lever) but is still not per-record; **F-25** was
reviewed and confirmed correctly non-actionable (already fully quantified and disclosed, no
further fix warranted). See `docs/audit-verification-report.md` §4 for the full detail.

**Analysis Engine (scenario sweep): built and validated against real data + live BrightHub
reanalysis**, including two real-world runs that found and fixed genuine defects (undisclosed
roughness clipping; an LTC R² admissibility gate that turned out to be structurally biased
against non-least-squares MCP methods and was removed). See
`docs/design/analysis-engine.md` status table — nearly everything is done. Open items:

- **§7.10 method gaps**: matrix/joint-distribution MCP not implemented; bootstrap CIs on LTC
  fits; SpeedSort sector count is still hardcoded, not a parameter.
- **§12.3 findings**: `availability_90` **is fixed** (2026-09-08, see below) — availability
  is now measured over each sensor's own deployed period rather than the total record count.
  `widest_lever` is still a good shear-fit set but a bad extrapolation reference (crossing
  A1×A2 over the same four policies wastes leaves on combinations nobody would defend).
- **§13.5**: the sweep cost model needs restating against real-reanalysis numbers (~2.4h for
  the 8,960-leaf core, not the 30–70 min estimated against synthetic references); a
  replacement for the removed R² gate — "is this reanalysis usable at this site at all," a
  per-reference gate computed once — is designed but not built.
- **`CompareView.tsx`** retirement is done, but not as originally flagged here: it turned out
  *not* to be a strict subset of the Spread Explorer (it compares saved Canvas/workflow-run
  executions, not sweep scenarios — see "2026-09-06: frontend redesigned..." above), so its
  tab was removed and its capability relocated into Canvas instead of merged into
  Interrogate. `CompareView.tsx` itself is unchanged, just re-homed.
- Two decisions explicitly flagged "worth revisiting, not settled": whether analyst-supplied
  shear (single-height fallback) should accept a range instead of one value; whether
  `max(parametric, empirical)` uncertainty substitution should become coverage-gated
  replacement instead.

**Superseded 2026-09-06**: Canvas and the Stepper are no longer peer top-level tabs — `
PhaseTabs.tsx` was deleted along with the 10-tab IA it rendered. Canvas is now its own
`PhaseRail` entry (React-Flow DAG, editable, live execution, plus the relocated Compare
capability); the Stepper lives inside Prepare's "Pipeline" section (`PrepareView.tsx` →
`StageShell.tsx`, unchanged internally) rather than as an independent destination. The
distinct-purposes reasoning still holds (Canvas runs the pipeline as a graph; the Stepper
inspects one stage linearly) — only where each one is reached changed. If picking this up
after a gap, re-verify against `frontend/src/App.tsx`, `PhaseRail.tsx` and `PrepareView.tsx`.

**Since 2026-08-23, two independent frontend bugs in the Analysis Engine were found and
fixed** (both in `useSweepStore.ts` / `useWorkspaceStore.ts`, with regression tests):
- The **Exhaustive preset selected axis levels this session couldn't actually run** (e.g.
  `redundant_boom` on a lidar with no boom redundancy), rendering their checkboxes checked
  *and* disabled and permanently blocking "Run sweep" with no way to untick them. Fixed by
  intersecting the preset (and the carried-over default selection) with the session's actual
  axis availability, and surfacing what got dropped rather than silently narrowing it.
- **MERRA-2 stayed permanently unavailable in the sweep** on any session that went through
  the standard "Save config and setup" flow, even though it was fully downloaded — that flow
  called `/era5/interpolate` once with no `source`, which defaults to `"era5"`, so
  `state.reanalysis_interpolated["merra2"]` never got populated. (The Canvas's own BrightHub
  reanalysis node avoided this only because it calls a different tool,
  `brighthub_prepare_reanalysis`, which interpolates both sources.) Fixed by adding the
  missing second interpolate call for the BrightHub path. **A session whose reanalysis was
  downloaded before this fix landed will still show MERRA-2 as unavailable** — the
  interpolated series lives in server memory only, so re-running "Save config and setup" (or
  the Canvas's reanalysis node) against the fixed code is required to backfill it; there is no
  way to repair an already-downloaded session's in-memory state from outside a running server.
  **Correction (2026-09-06): this fix never actually worked.** The added second
  `/era5/interpolate` call passed `{source: "merra2"}` in the JSON body, but the FastAPI route
  declared `source: str = "era5"` as a bare parameter with no `Body()` annotation — FastAPI
  binds an unannotated primitive as a *query* parameter, so every JSON-body caller (this
  frontend included) had `source` silently discarded and always got `"era5"` back, regardless
  of what was requested. See the dated entry further below ("a live user report... two more
  findings") for the real fix (`InterpolateEra5Request` body model) and why nothing caught
  this for months: every prior test called `_interpolate_era5_to_site` directly, bypassing
  FastAPI's parameter binding, so the query/body mismatch was invisible to the test suite.

**2026-09-03: a maintenance pass added `CODEDOC.md`**, split the 1,856-line
`server/tools/visualization.py` into a themed package (`server/tools/visualization/` — see
Layout above), and removed six verified-dead functions with zero references anywhere in
`server/`/`tests/` and no MCP/HTTP exposure (three `validate_*` helpers in
`core/validators.py`, `_ensure_json` in `windkit/_serializers.py`, `core/sweep.py`'s
`iter_progress`, `core/brighthub.py`'s `get_measurement_location`, and the unused public
methods `SessionManager.list_sessions` / `SessionState.set_power_curve_name`). All were
verified against the full test suite before/after (`CODEDOC.md` §12 has the full list); none
were referenced from README, this file, or any skill.

**2026-09-06: EarthDataHub migrated its ERA5 Zarr stores to the Zarr v3 spec**, and the
project's own EarthDataHub credential handling was reworked at the same time:
- `pyproject.toml` bumped `zarr>=2.14` → `zarr>=3.0` and added explicit `dask`/`aiohttp`
  dependencies (EarthDataHub's own install instructions list all three; the dataset URL
  itself is unchanged — it migrated in place).
- **The EarthDataHub PAT moved from an env var/`.netrc` file to session-scoped state**,
  mirroring BrightHub's login exactly: entered once per browser session via a credential
  field on the Data import page (`EarthDataHubCredentialForm` in `DataLoadView.tsx`), stored
  in-memory on `SessionState.earthdatahub_pat` (never written to a config file, never
  persisted to `runconfig.json`), with new session-scoped tools/routes
  (`earthdatahub_set_credential` / `_clear_credential` / `_status`,
  `POST|DELETE /era5/credential`, `GET /era5/credential/status`) replacing the old
  `EARTHDATAHUB_PAT`/`EDH_PAT`/`DESTINE_PAT` env vars and custom `.netrc` parsing. The
  speculative header-based auth path (`EARTHDATAHUB_API_KEY` etc.) was removed too — it
  never matched EarthDataHub's actual documented mechanism. Tool count moved from 223 to 226.

**2026-09-06: `.env.example` removed.** It had nothing left to configure — both BrightHub
and EarthDataHub credentials are entered per browser session through the UI and held in
server memory only, and `WINDKIT_NAME`/`WINDKIT_EMAIL`/`WINDKIT_INSTITUTION` are the only
env vars this project ever reads (optional, to skip WindKit's interactive first-run prompt).
There is no `.env` file to copy anymore; set those three vars directly if running headless.

**2026-09-06: three more real bugs in the direct-ERA5 (EarthDataHub) path found and fixed**,
the last two via a live end-to-end run against the actual Zarr v3 store with a real
credential:
- The direct-ERA5 acquisition flow extracted data only at the site's own coordinate, never at
  the four bounding-grid nodes `_interpolate_era5_to_site` actually requires, so ERA5 (not
  just MERRA-2, which is correctly always unavailable on this path) stayed permanently
  disabled in the Analysis Engine sweep whenever EarthDataHub was the provider. Fixed by
  looping over every node `/era5/nodes` discovers in both `runReanalysisAcquisition`
  (`useWorkspaceStore.ts`) and the manual "Find nodes"/"Extract"/"Interpolate" buttons
  (`ReanalysisView.tsx`), mirroring how the BrightHub path already downloads all of its nodes.
- **Node extraction was silently clobbering the site coordinate.** `_extract_era5_data`
  (`server/tools/era5.py`) called `_store_coordinate` with whatever lat/lon it was passed —
  harmless when called once at the site's own coordinate, but the fix above now calls it once
  per node in a loop, so after all four extractions `state.get_coordinate()` (what
  `_interpolate_era5_to_site` reads as "the site") silently became whichever node was
  extracted *last*. Interpolation then degenerated to exactly that one corner's raw value
  instead of a genuine spatial blend, with **no error raised** — live-reproduced against the
  real store before the fix (interpolated mean matched the last node's own mean bit-for-bit).
  Fixed by deleting the coordinate side-effect from `_extract_era5_data` entirely; only
  `_find_era5_nodes` and the initial project-config step may set the site coordinate now.
- **Cache hits crashed on a tz comparison.** `_cache_covers_period`/`_load_cached_era5`
  compared the tz-aware cached index (ERA5 is cached UTC-localized, D8) against tz-naive
  `pd.Timestamp` request bounds, raising `TypeError: Cannot compare tz-naive and tz-aware
  timestamps` on every second request for the same node/date range — every cache hit after
  the first crashed instead of serving the cache. Fixed with a new `_align_tz` helper.

All three fixed with regression tests (`tests/test_phase3.py`, `frontend/src/test/`); full
backend suite, `ruff check`, and frontend suite green afterward.

**Same day, a live user report ("ERA5 still not enabled after save config and setup") led to
two more findings** — one operational, one a real latency issue:
- **The live dev server had been silently running stale code all along.** It was started
  before the three fixes above (and before `dask` was even installed locally), so none of
  them had ever actually reached it — every `/era5/*` call kept failing regardless of the
  code fixes, because they'd only been validated by calling the functions directly in fresh
  Python processes, never through the actual running HTTP server. Restarting it hit a second
  snag: on Windows, `uvicorn --reload` (what `startup.ps1` uses) spawns workers via
  `multiprocessing.spawn`, and killing the reloader parent left an **orphaned worker process
  still bound to the port**, serving stale state indefinitely — `Get-NetTCPConnection`'s
  reported owning PID pointed at the already-dead parent, not the actual live orphaned child;
  finding the real process required cross-referencing every running python process's command
  line for `spawn_main(parent_pid=<dead-pid>, ...)`. **Lesson: after a dependency install or
  code change a `--reload` server should pick up, verify against the live server itself
  (curl/HTTP) — a fresh-process validation proves the code is correct, not that the running
  server has it.**
- **EarthDataHub's cold per-node read latency varies enormously and is the real reason ERA5**
  **never became available for this user.** Live-measured: one grid node's 1-week cold fetch
  took 582.7 seconds (~9.7 min) against seconds for its neighbours. The direct-ERA5 flow
  extracted all 4 nodes sequentially, so total wait was their *sum* — well past what anyone
  would wait for with no progress feedback, so the flow was effectively always abandoned
  before reaching interpolation. **First attempted fix (since reverted — see below):**
  switched both extraction loops to `Promise.all(...)` to bound the wait by the single
  slowest node instead of their sum. **Live-reproduced as actively worse**: firing all 4
  extractions concurrently made EarthDataHub reset/reject the simultaneous connections from
  the same credential outright — all 4 failed with `502 Bad Gateway` (retries exhausted)
  instead of just being slow, in both a real user session and a standalone reproduction.
  A slow sequential success beats a fast concurrent failure, so both loops
  (`runReanalysisAcquisition` in `useWorkspaceStore.ts`, `extractEra5Direct` in
  `ReanalysisView.tsx`) were **reverted to sequential `for`-await**. The underlying latency is
  unresolved — a single node can still take ~10 minutes cold, sequential extraction of 4 can
  take 20+ minutes in the worst case — but bounded concurrency (e.g. 2 at a time) was not
  attempted; the actual connection limit EarthDataHub tolerates is unknown, so revisit only
  after confirming that limit rather than guessing again.

**Full live proof this session, against the real server and the real store:** credential set
→ find 4 nodes → extract all 4 → interpolate (`nodes_used: 4`) → `GET /sweep/axes` reports
`{"era5": true, "merra2": false}` — the correct end state for the EarthDataHub path.
**The dev server on port 8000 is currently running without `--reload`** to sidestep the
orphaned-worker trap recurring; a future code edit will not auto-restart it.

**Same day, the user reported it again** ("says 'Finding ERA5 nodes (DIRECT)' then goes
straight to Cleaning, ERA5 not enabled") and asked three concrete questions: where is the
EarthDataHub credential stored, is something skipping work because cached files already
exist, and make the EarthDataHub cache folder/behavior match `brighthub_cache`. Findings:
- **No skip-if-cached logic exists.** `earthdatahub_pat` lives only on
  `SessionState.earthdatahub_pat` (server RAM, never disk/config file). The per-node parquet
  cache only ever provides a fast-path re-use of identical previously-fetched data — it never
  skips find-nodes, extraction, or interpolation outright.
- **The actual cause: `saveConfigAndSetup` had a BrightHub credential gate but no equivalent**
  **EarthDataHub one.** A missing/not-yet-saved PAT let the flow run straight into
  `runReanalysisAcquisition`, which fails at `/era5/nodes` with a raw 401 — live-confirmed
  this happens immediately (not slow), matching "one activity entry, then Cleaning" exactly,
  and was indistinguishable from an unrelated server fault since FastAPI turned the raw
  `aiohttp.ClientResponseError` into an opaque 500. Fixed two ways: (1) added the missing gate
  in `saveConfigAndSetup`, mirroring the BrightHub one — checks
  `getEarthDataHubStatus(...).configured` before proceeding; (2) added
  `_is_auth_error`/`_AUTH_ERROR_MESSAGE` in `server/tools/era5.py` so any 401/403 from
  `_open_era5_dataset` raises a plain `ValueError` with a clear message instead of the raw
  exception, covering credential expiry mid-session too (wired into both `_find_era5_nodes`
  and `_download_era5_frame_with_retry`).
- **Cache folder renamed `era5_cache` → `earthdatahub_cache`**, matching the user's request to
  mirror `brighthub_cache`'s provider-scoped naming and identical treatment (session-scoped,
  parquet-per-node, no TTL — a cache hit is trusted forever, same as BrightHub). Updated in
  `server/tools/era5.py`, `server/state/manager.py`, `tests/test_phase6_state.py`.

The Pass 5 `Promise.all` concurrency fix above is a *separate* contributing cause to this same
report, not something redone here — a correctly-configured session hitting sequential
extraction latency and a misconfigured session hitting the missing-credential gate produce
the identical outward symptom, so both had to be fixed. All fixed with regression tests
(`tests/test_phase3.py`, `frontend/src/test/defaultWorkflowStore.test.ts`); live-verified
again after restarting the server: no-credential → clean `400` with the new message (was a
raw 500); with-credential → `earthdatahub_cache/` populated correctly.

**2026-09-06: added a blocking progress overlay for reanalysis downloads (BrightHub and**
**EarthDataHub direct), on request** — the acquisition flow gave no visibility beyond a
generic "Downloading..." pill, which is exactly why the earlier "stuck" reports were hard to
tell apart from a real hang. `useWorkspaceStore`'s new `reanalysisProgress` field
(`{ provider, phase: "finding_nodes"|"downloading"|"interpolating", dataset, current, total,
latitude, longitude, distanceKm }`) is set/cleared around every node-level step in both
`runReanalysisAcquisition` and `ReanalysisView.tsx`'s manual buttons, and rendered by a new
`ReanalysisProgressOverlay` (mounted in `App.tsx`, above `AppHeader`) as a non-dismissable
`.modal-overlay` showing "Node X of Y", the node's lat/lon (+ distance from site when known),
and a spinner. **BrightHub's download action was changed from one bulk request (all nodes at
once) to one request per node** — `/brighthub/reanalysis/download` already accepted a node
list of any size, so this needed no backend change, just looping client-side — purely to get
the same real per-node granularity BrightHub's UI now shows that EarthDataHub's sequential
loop already had. Regression tests added at the store level (`defaultWorkflowStore.test.ts`)
and component level (`stageViews.test.tsx`); 196/196 frontend tests passing, clean build.

**2026-09-06: the "MERRA-2 interpolation" fix from earlier this same day never actually**
**worked — found via a live user report** ("why is MERRA2 disabled even though it's already
downloaded from BrightHub") **and confirmed against the user's real session.** `POST
/era5/interpolate` declared `source: str = "era5"` as a bare function parameter with no
`Body()` annotation. FastAPI binds an unannotated primitive parameter as a **query**
parameter, not a JSON body field — but every real caller, including this project's own
frontend (`callSessionRoute` always sends a JSON body for POST), sends `{"source": "merra2"}`
in the body. FastAPI silently discarded it and always used the `"era5"` default. Live-proved
against the user's actual session: calling `/era5/interpolate` with `{"source": "merra2"}`
returned `"reference_source": "era5"` with ERA5's own column names (`Spd_100m`, 100 m height)
even though the interpolation had just consumed MERRA-2's own downloaded node data — the
"second interpolate call" fix from earlier today (see above) had been silently re-interpolating
ERA5 a second time this entire time, never MERRA-2. **Why nothing caught this:** every existing
test (including the regression test added for the original fix) calls
`_interpolate_era5_to_site` directly, bypassing FastAPI's parameter binding entirely — the
query/body mismatch only exists at the HTTP layer, which nothing exercised with an actual
request body until this session. Fixed by adding a proper `InterpolateEra5Request` Pydantic
body model (`server/api/schemas.py`) and updating the route
(`server/api/routes/analysis.py`) to read `body.source` instead of a bare parameter. New
regression test in `tests/test_api_sessions.py` exercises the real HTTP route through
`TestClient` with a JSON body — verifies `reference_source`/`speed_column`/
`reference_height_m` all come back as MERRA-2's, not ERA5's. Full backend suite + ruff clean
afterward. **Any session whose MERRA-2 interpolation was attempted before this fix landed is
still showing ERA5 under the hood** — the same "re-run against the fixed, restarted server"
caveat as the original MERRA-2 fix applies here too.

## Known limitations (by design, not bugs — see README for the full list + rationale)

- No AEP/energy yield computed for the main (non-sweep) pipeline; only the sweep's Analysis
  Engine publishes an indicative gross AEP off a generic 3 MW curve.
- No outlier/spike detection (removed deliberately — F-72 — after measuring it deleted ~1,350
  good records per campaign to catch a handful of real spikes).
- No atmospheric-stability model — neutral profile only, with the 12×24 shear table as the
  empirical stability proxy.
- Confidence intervals are AR(1)-corrected but still an approximation, not a rigorous
  autocorrelation treatment.

## Where to go deeper

- **Full endpoint/tool inventory + every disclosed default and its magnitude**: `README.md`
  — genuinely worth reading in full before touching `server/tools/` or `server/core/`.
  It is the closest thing this project has to a spec.
- **Module-by-module code structure, data flow, and refactor/cleanup history**: `CODEDOC.md`
  — committed, so it's the one structural reference guaranteed to exist on a fresh clone.
- **Why a given constant/clamp/threshold has the value it has**: `docs/audit/NN-*.md` (the
  step that covers that area) then `docs/audit/FIXES.md` (search the finding ID).
- **Sweep/Analysis Engine internals and unresolved design questions**:
  `docs/design/analysis-engine.md`.
