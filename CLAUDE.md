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
- **`server/`** — Python MCP server (FastMCP) + FastAPI web API. 226 tools across ingest,
  cleaning, statistics, shear/extrapolation, ERA5+MERRA-2 reanalysis, homogeneity, 5 LTC/MCP
  algorithms, ensemble, clipping, uncertainty, mapping, visualization, BrightHub integration,
  a scenario **sweep/Analysis Engine**, and a WindKit tool surface (~180 tools).
- **`frontend/`** — React 19 + Vite + TypeScript app: data import, an editable React-Flow
  Canvas, a guided post-import Stepper, a read-only Results report, a Sensor Overview
  validation dashboard, a BYOK AI Copilot, scenario Compare, and the Analysis Engine (Sweep
  Designer → Run Monitor → Spread Explorer → Sensitivity → Spread Summary).

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

Current baseline (verified 2026-09-06, after the EarthDataHub direct-ERA5 fixes below): 935
backend tests passing / 2 skipped, 196 frontend tests passing, frontend typecheck clean, 226
MCP tools registered, and `ruff check server/ tests/` clean. These numbers move as the project
grows — `validate-gokaatru` always re-derives the live count rather than trusting any written
baseline, this one included. Backend count assumes the gitignored `data/uploads/` fixtures are
present (see the `tests/` layout note above); without them, expect setup errors on the tests
that use them, not a lower clean pass count.

**Ruff was not clean before 2026-08-25** — 185 findings (97 E501, 36 I001, 31 F401, 17 W292,
3 F841, 1 F811) had accumulated because `ruff>=0.1` is unpinned and the check was not being
run to zero. They are all fixed now; keep it at zero rather than letting a second wall build.

## Current state (last verified 2026-09-06)

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
- **§12.3 findings**: `availability_90` sensor policy is unreachable on 2 of 3 real test
  campaigns (measures availability against total record count including pre-installation
  gaps — should measure against each sensor's own deployed period); `widest_lever` is a good
  shear-fit set but a bad extrapolation reference (crossing A1×A2 over the same four policies
  wastes leaves on combinations nobody would defend).
- **§13.5**: the sweep cost model needs restating against real-reanalysis numbers (~2.4h for
  the 8,960-leaf core, not the 30–70 min estimated against synthetic references); a
  replacement for the removed R² gate — "is this reanalysis usable at this site at all," a
  per-reference gate computed once — is designed but not built.
- **`CompareView.tsx`** is flagged for retirement/subsumption into the Spread Explorer (its
  manual 2–4 run comparison is a strict subset) — not yet done; both still exist.
- Two decisions explicitly flagged "worth revisiting, not settled": whether analyst-supplied
  shear (single-height fallback) should accept a range instead of one value; whether
  `max(parametric, empirical)` uncertainty substitution should become coverage-gated
  replacement instead.

**No architectural drift currently known** between the Canvas (React-Flow DAG, editable,
live execution) and the Stepper (guided linear review) — they coexist as separate tabs in
`PhaseTabs`, each serving a distinct purpose (Canvas = run the pipeline; Stepper = inspect
one stage in depth), not competing models. If you're picking this up after a gap, re-verify
this against `frontend/src/App.tsx` and `PhaseTabs.tsx` before assuming it still holds.

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
