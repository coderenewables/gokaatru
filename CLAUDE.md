# GoKaatru — CLAUDE.md

Context for Claude Code working in this repository. Read this before making changes; it
encodes conventions the codebase enforces strictly and that reviewers (including past
audit passes) have checked for by hand.

## What this is

GoKaatru ("Wind" in Tamil) is an **open-source Wind Resource Assessment (WRA) platform**:
it turns a measured wind campaign into a long-term-corrected, hub-height, ensemble-blended
wind resource characterization suitable for feeding an Energy Yield Assessment. It is built
for **bankable rigor** — numbers a bank's technical advisor will try to break. It makes **no
standards-conformance claim**: individual methods cite the IEC 61400 clause they draw on,
those citations have not been checked against the clause text, and the only wording allowed
is "traced to", never "compliant with" or "follows".

Two parts, one logic core:
- **`server/`** — Python MCP server (FastMCP) + FastAPI web API. 103 tools across ingest,
  cleaning, statistics, shear/extrapolation, ERA5+MERRA-2 reanalysis, homogeneity, 5 LTC/MCP
  algorithms, ensemble, clipping, uncertainty, mapping, visualization, BrightHub integration,
  and a scenario **sweep/Analysis Engine**. DTU's WindKit (pinned `==2.2.0`) is used only
  where it is the reference implementation and has no tools of its own (`decisions/0009`).
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
  rationale. The new workbench is built beside it at `/workbench/` (Phase 2: projects of
  campaigns, Dockview panels, data tree and mast diagram, linked timeline, scatter, rose and
  profile, flags drawn on the charts, undo through the server's history; `decisions/0014`), and
  replaces it at the Phase 3 gate.

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
- **`decisions/`** — committed architecture and scope decision records for the workbench
  rebuild, each with its status (owner, measured, or proposed) and its evidence. Read the
  index before changing anything they cover.

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
│   └── visualization/    # Plotly figure builders — a themed PACKAGE, not a single file
│                         #   (split from a 1,856-line module 2026-09; __init__.py wires the
│                         #   @mcp.tool() wrappers and re-exports every builder, so every
│                         #   existing `server.tools.visualization.*` import path is unchanged)
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

tests/                    # 83 backend test files (pytest) — includes oracles.py, an
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
python -m tests.published_numbers --check   # every published number on the 3 campaigns, exact (~35 s)

cd frontend && npm run test          # vitest
cd frontend && npm run build         # tsc --noEmit && vite build
cd frontend && npm run check:api     # generated API client matches frontend/src/api/openapi.json
python -m tests.openapi_schema --write && (cd frontend && npm run generate:api)   # after an API change
cd frontend && npm run test:e2e      # Playwright; starts its own backend :8011 and Vite :5183
```

CI (`.github/workflows/ci.yml`) runs the same on every push: backend on Ubuntu and Windows,
frontend, and the Playwright smoke test. The real campaigns are gitignored, so CI runs only
the synthetic-data tests; `GOKAATRU_TEST_UPLOADS_DIR` points the suite at another campaign
folder, and a missing campaign file skips its test by name (`require_campaign_file` in
`tests/conftest.py`), never errors.

Current baseline (verified 2026-11-25, branch `phase2-workbench` at the Phase 2 gate):
1701 backend tests passing / 4 skipped (each skip states its reason), 346 frontend tests
passing (45 files), 41 Playwright tests passing (the smoke test and the workbench's), frontend
typecheck and build clean, the generated API client current, 103 MCP tools registered and
identical to the snapshot, and `ruff check server/ tests/` clean. Without the campaign files
(CI run 45592898191, Ubuntu and Windows): 1639 passed / 66 skipped; all four CI jobs passed. These numbers move as the project
grows — `validate-gokaatru` always re-derives the live count rather than trusting any written
baseline, this one included. Backend count assumes the gitignored `data/uploads/` fixtures are
present (see the `tests/` layout note above); without them the tests that need them skip.

**Ruff was not clean before 2026-08-25** — 185 findings (97 E501, 36 I001, 31 F401, 17 W292,
3 F841, 1 F811) had accumulated because `ruff>=0.1` is unpinned and the check was not being
run to zero. They are all fixed now; keep it at zero rather than letting a second wall build.

## Current state (last verified 2026-11-25)

**2026-11-25: workbench Phase 2 on branch `phase2-workbench`, gate passed and pushed (not merged).** Phase 1 was merged as PR #8. The owner's Phase 2 decisions, taken by interview on 2026-11-25, are `decisions/0014-workbench-prepare.md`; the task list is `Claude outputs/WORKBENCH_PLAN.md` §8d. The gate: browser tests for every Prepare row of plan §3.3; flags drawn on a chart equal, record for record, those of the old rules for the same records; every published number identical; every suite and CI green.

- **P2-G, the gate (2026-11-25):** all of it holds. 1701 backend tests pass / 4 skipped, 346 frontend tests (45 files), 41 Playwright tests (smoke included), typecheck, build and the generated client clean, 103 MCP tools identical to the snapshot, ruff clean, every published number identical on the three campaigns. CI run 45592898191 green on all four jobs (Ubuntu and Windows backend 1639 passed / 66 skipped without the campaign files, frontend 346 in 45 files, Playwright 41). Flags drawn in the browser equal the old rules' (`e2e/flags.spec.ts`): a brushed period and `custom_period_exclude` over the same records, rose sectors and `tower_shadow` through the old route; the scatter box against `expression_filter` and the period against `custom_period_exclude` are also held on the server (`tests/test_exclude_selection.py`). **Open for the owner:** the energy sensitivity's order dependence (P1-5b) and the wording of decision 13's sweep exclusion, both carried from Phase 1. **Known, not fixed:** before a data model exists the sensors route guesses types from names, so the charts' defaults can include a statistic column (`Spd_100m_sd` read as a speed) until the model is built; the start screen fetches every project's details, which will be slow with many projects; the mast diagram scrolls inside the narrow Data panel, and a pointer drag to a level out of view needs the panel taller.
- **Server (P2-1 to P2-8c):** polygon selections (lasso; even-odd rule, a rectangle equals its two half-open bands; the edge loop sorted by y took a 199-vertex lasso over 262,800 records from 1,037 ms to 59 ms). A `selection` is a saved name or an inline definition, and a read on an inline one is not logged (brushing is view state). `exclude_selection`, the rule a drawn flag applies: the definition frozen into the rule, the whole instrument as one log entry, a reason from `MANUAL_FLAG_REASONS` and a note. New reads `get_flag_intervals`, `get_scatter_pairs` (Arrow at `/sessions/{id}/pairs`), `summarise_channels`, `list_instruments`. `remove_sensors` is an operation with a dry run and undo (removed columns kept in `state.removed_sensors`); a rebuilt drafted data model is undoable, a campaign's own uploaded one refuses any build. Projects of campaigns (`/api/projects`, `server/state/projects.py`), one reanalysis node cache per project; a cached BrightHub node is reused when it reaches the campaign's last record. 98 -> 103 tools.
- **Defects found on the way, each its own commit:** a replayed cleaning rule took the undoer's actor and time (P2-4a; the actor is now on each log entry, unhashed in the prefix); a data model declaring another timezone for records already in UTC was accepted while the records kept the first (P2-7a, refused now); a refused build left its document on disk (P2-7); a rebuilt mapping did not mark results stale (P2-7); a removal did not either (P2-6); the BrightHub route and preparation each had their own download loop (P2-8b); the project view read a campaign's site only from `runconfig.json`, which the generated routes do not write (P2-10a).
- **Interface (P2-9 to P2-20), at `/workbench/` beside the current interface:** Dockview shell with a title-only tab (axe's nested-interactive), light and dark tokens; start screen of projects and campaigns, campaign switcher; data tree with every channel draggable onto a chart; loading by drop or chooser and the mast diagram (drafted model editable by drag, uploaded model read-only); timeline (uPlot over Arrow windows, brush, flag bands, arrows through flags); scatter (regl-scatterplot, own lasso); rose (sectors as the server bins them, tower-shadow proposal); profile; inspector (crossfilter terms and counts, flag the selection with preview, a proposed rule, the focused flag with one-click removal); undo and redo on Ctrl+Z / Ctrl+Shift+Z through the server's history; Ctrl+K palette; status bar (actions, data version, prefix hash, stale results); reanalysis acquisition one node at a time. Every browser spec fails on any error the page throws: two uPlot throws that left the timeline blank, and an unhandled regl rejection, were found that way. Each Playwright run's backend keeps its data in its own folder (`GOKAATRU_DATA_DIR`).
- **Work split (decision 0014.13):** the timeline, scatter, start screen, reanalysis panel and mast diagram were built by Sonnet agents in separate worktrees, each verified and merged with its own follow-up fixes; the rest inline.

**2026-11-19 to 2026-11-24: workbench Phase 1 on branch `phase1-foundations`, gate passed; merged by the owner as PR #8 (`cc35605`, 2026-11-25).** Task list and status in `Claude outputs/WORKBENCH_PLAN.md` §8c; the gate is every published number identical, all tests passing through the new layer, and a project that reopens intact after a restart.

- **P1-G, the gate (2026-11-24):** all three items hold. Every test passes through the new layer: 1572 passed / 4 skipped locally (three disclosure fields this pipeline never reaches, and the operation log, which each surface logs differently by design), 269 frontend, Playwright, CI run 45440289043 green on all four jobs (Ubuntu and Windows backend 1510 / 66 without the campaign files). Every published number is identical on the three reference campaigns (Boxkite 6,093, Horns Rev 4,367, Launakalana 7,613). A project reopens after the server process is killed with every result, its log and its staleness intact (`tests/test_restart.py`, in the suite and in CI). The MCP surface equals its snapshot and the OpenAPI schema equals the committed one. 30 commits since `origin/master` (PR #7). **Still open for the owner:** the energy sensitivity depends on whether the atmospheric diagnostic ran first (P1-5b); the stray remote `phase0-stabilise` branch (pushed again by mistake after PR #5 merged it); confirmation of how decision 13's sweep exclusion is mentioned. **Carried to Phase 2:** the working frame is still stored with its missing values rather than derived from raw data plus flags; the hand-written routes and their logging middleware stay until the interface moves to the generated routes and client; the GitHub actions used target Node 20, which GitHub now forces onto Node 24 (annotation only).

- **P1-0a `dc895f2`:** `fixed_prefix_hash` hashed each cleaning-log entry whole, including `applied_at`, so the same cleaning applied a minute apart gave a different prefix and a different `config_hash` for every scenario: no two sessions with cleaning were ever comparable. Entries are now hashed without `CLEANING_LOG_UNHASHED_KEYS`; the oracle drops the time independently. No metric moved; prefix and config hashes of sessions with cleaning changed. Found by P1-0, whose two identical Launakalana runs disagreed on the prefix and all 32 config hashes.
- **P1-0:** `tests/published_numbers.py` runs the pipeline on the three campaigns and records every number each step returns, plus a SHA-256 of every series it reads or writes, into `tests/snapshots/published_numbers.json` (Boxkite 6,093, Horns Rev 4,367, Launakalana 7,609). Launakalana carries the whole chain against the cached ERA5 and MERRA-2 in `data/e2e-real/brighthub_cache` (five correction methods and XGBoost, ensemble, clipping, uncertainty, a 32-row sweep); Boxkite and Horns Rev stop at the hub series because no reanalysis for them is cached locally. Recorded as refused, not run: the icing filter on all three (no temperature sensor at a speed height) and tower shadow on Launakalana (no paired vane). Two fresh runs are identical, about 35 s. `tests/test_published_numbers.py` compares exactly and skips without the campaign files.
- **P1-0b:** the MCP server's instructions called the tools "IEC-compliant" (P0-1 had fixed README only), and 16 docstrings, 7 of them tool descriptions, said "per IEC"; all now say "traced to", clause references kept.
- **P1-1:** the registry core (`server/operations.py`; moved out of `core/` in P1-2 because it imports FastMCP): `Operation`, `OperationRegistry`, `REGISTRY`, `@operation`. Nothing is declared yet. The schema comes from FastMCP's parser, and `tests/test_operations.py` checks it equals each of the 90 tools' schema and description; declarations with an unknown effect or stage, a dry run on a read, a malformed disclosure field or conformance wording in a standards reference are refused.
- **P1-2 `89209e2`:** all 90 tools declared with `@operation` (effect, stage, and canvas, assistant, network where they differ from the defaults), classified from today's chat tiers, executor module list and stage order, and tested equal to all three. `effect` is data change only; `network` is separate, and the assistant's change tier is changes or network calls.
- **P1-3:** the declaration publishes the MCP tool; the 90 `@mcp.tool()` lines and the tool modules' `server.main` imports are gone. What MCP clients receive is pinned in `tests/snapshots/mcp_tools.json`, tool by tool (registration order depends on import order and is not compared), and was identical before and after.
- **P1-4:** the chat tiers, the chat callables, the executor's canvas dispatch and its stage tie-break rank are read from the registry. `TOOL_MODULE_PATHS`, `CANONICAL_STAGE_ORDER` (its F-09 reasoning moved to `STAGES`), the hand-kept tier sets and chat's module list are deleted. The tiers, the six non-canvas operations, the module-to-stage map and the stage order are pinned by name in `tests/test_operations.py`, so moving a tool between tiers is a visible test edit.
- **P1-5a `b322314`:** `get_run_config`, declared a read, rewrote `state.runconfig` with the sensor mapping, cleaning log and table shapes on every call. It now returns the same canonical view built from a deep copy.
- **P1-5:** `server/api/routes/operations.py` generates `POST /sessions/{id}/operations/{name}` for all 90 operations (body model from the signature, extra fields refused, `ValueError` 400, `RuntimeError` 502) and `GET /operations`. The hand-written routes stay until Phases 2-3. `tests/test_operation_routes.py`: every read operation returns the same over HTTP as over MCP as the result crosses the wire (both send NaN as null), refusals included, and leaves the session unchanged.
- **P1-5b:** `compute_atmospheric_conditions` was in the assistant's read tier, but it records `mean_air_density_kgm3` in the run configuration and the energy-sensitivity factor normalises speed with it, so an assistant without the opt-in could move that number. It is declared a change now (read tier 51 → 50, change tier 27 → 28). **Open for the owner:** the energy sensitivity depends on whether the diagnostic was run first; when it was not, the response says normalisation was skipped (disclosed, F-57), but the result is order-dependent.
- **P1-6:** dry runs for `apply_cleaning_rule` and `undo_cleaning_rule`, declared on their operations and served at `POST .../operations/{name}/preview` with the same body. Each runs the real function on a replica of the session and reports the change as a diff of the frames, so a preview cannot drift from what applying does; `tests/test_dry_run.py` checks preview-then-apply equals the previewed change for all seven rules and for undo, with the session untouched. A copy of the session proxy forwarded writes to the bound session, so the replica resolves the proxy first. The registry refuses a dry run whose parameters differ from its operation's. Sensor removal is HTTP-only today, not an operation, so it has no dry run yet; every other changing operation shows `dry_run: false` in `GET /operations`.
- **P1-7a:** `compute_mcp_readiness` crashed with a raw pandas error when the mast speed and the reference shared a column name (`Spd_100m`, ERA5's name and a common 100 m sensor name); it now joins on fixed internal names, as the corrections do. Found by P1-7's pipeline.
- **P1-7b:** README said every correction reports `variance_ratio_to_reference`; XGBoost builds its own response and did not. It now reports it (Launakalana: 0.706 of the reference's variability kept). Four new snapshot fields, no existing number moved.
- **P1-7:** 29 operations declare their disclosure fields, taken from README's table. `tests/test_disclosure_fields.py` checks the table against the declarations both ways (fields from the HTTP-only sweep engine and from `derive_uncertainty_inputs` are listed with their source) and runs a synthetic pipeline that finds each declared field in its operation's response; three conditional fields are skipped with the reason. `extrapolate_reanalysis` and `reanalysis_status` belong to the sweep's stage detail, not the tool's response, and `get_fixed_prefix_hash` hashes `engine_version` without returning it, so those three were not declared.
- **P1-8:** the `add-operation` skill replaces `add-mcp-tool`: one declaration, then the pinned lists, the MCP snapshot and the counts that must move with it. Tried in a throwaway worktree by adding a trivial read operation: the pinned tests failed until each step was done, the generated-route test covered the new operation without being told, and the suite was green after. That trial found a fourth copy of the tool count in `tests/test_operations.py`, now removed (the count stays pinned in `tests/test_phase4.py` and CI). `validate-gokaatru` now runs the published-numbers check, the MCP surface check and Playwright, and re-derives its baseline from this file instead of carrying a stale one.
- **P1-9:** `server/state/project.py`, the project store (decisions/0010). Raw inputs stay in `uploads/` with their SHA-256 in `catalogue.sqlite`, and a project whose recorded input was changed or removed is refused on open (`ProjectIntegrityError`, HTTP 409). Every frame is saved as `working/<content sha256>.parquet` (unchanged frames are not rewritten; identical ones are stored once) and every other field as JSON; credentials, identity and in-flight run status are never written (`EXCLUDED_FIELDS`, each with its reason). `SessionManager.get_session` reopens a saved project after a restart. Nothing saves automatically yet: P1-10's operation log does that after each change. `tests/test_project_store.py` round-trips the fully analysed Launakalana session (every correction, ensemble, clipping, uncertainty) field by field, identical.
- **P1-10:** the operation log. Each declaration wraps its function (`functools.wraps`; MCP surface unchanged): every call appends to `state.operation_log` (actor, operation, effect, parameters, code version, data version before and after, status or error) and every successful change saves the project. The actor is a context variable each surface sets: `user` (generated routes), `assistant:<provider>/<model>` (chat), `canvas`, `mcp`; `direct` otherwise. `secret_parameters` (BrightHub client id and secret, the EarthDataHub key) are logged as `[redacted]`, also inside error messages; a test searches every file on disk for them. The hand-written routes the current frontend uses bypass the operations, so a middleware logs and saves after each successful change through one, by route template, never the body. `tests/test_operation_log.py`: a pipeline run over HTTP is logged in order and reopens after a restart.
- **P1-11:** cleaning flags. Every record a rule removes gets a row in `state.cleaning_flags` (timestamp, sensor, rule sequence and type, reason code, actor, time), found by diffing the column before and after the rule, so no rule's internals changed. Raw data reindexed to the working index with the flags applied reproduces the cleaned series bit for bit, tested on synthetic data and on all three campaigns' cleaning sequences, undo included. Undo still replays the remaining rules from raw (rules are order-dependent, so deleting one rule's flags would not give today's numbers) and keeps each replayed rule's original actor and time. **What this is not yet:** the working frame still holds the missing values itself; deriving it from raw plus flags on read is Phase 2 work with brush-to-flag. Published numbers identical.
- **P1-12:** result provenance. A result stamped during an operation call records the call (`derived_provenance`: operation, log sequence, parameters, engine version, data version); the wrapper sets the call in flight in the `current_operation` context variable. An artifact is stale when its data version is behind **or** it was built by another `ENGINE_VERSION`, and `staleness_report` gives `stale_reasons` when anything is stale. A reopened project keeps every result, its log and its staleness exactly; under a newer engine its results read as stale with the reason and are not recomputed. The catalogue records the engine version of each save.
- **P1-13:** server-side undo and redo, three new tools (90 → 93): `undo_last_change`, `redo_last_change`, `get_operation_log` (`server/tools/history.py`). An operation can attach an undo note to its own log entry (`note_undo`): cleaning records its rule's sequence, configuration its before and after snapshots. Undo of a cleaning rule uses the replay undo, so the series comes back bit for bit; undo of a configuration change restores exactly the paths and synced fields it changed and leaves unrelated later writes alone. Undo refuses when a later change moved what it would restore, or when the rule is no longer the last one. Redo re-runs the logged call. Any other change clears the redo history (`state.undo_stack`). Not snapshot-based: a snapshot per change would store a full frame each time (Horns Rev, tens of MB per rule). Tiers 51 read / 30 change; `EXPECTED_MCP_TOOLS` 93.
- **P1-14a:** concurrent saves of one project collided. The interface sends several changing requests at once; two saves wrote the same content-addressed frame through one temporary name and the rename failed on Windows (`PermissionError`, found by the Playwright run), and unserialised, one save's clean-up could delete a frame another had just recorded. Saves and loads of a workspace now take a lock, and each write uses its own temporary name. The session state itself can still be read by a save while another request changes it; single-user, not addressed.
- **P1-14:** `tests/test_restart.py` runs a real uvicorn process: upload, data model build, a configuration change, cleaning, shear and extrapolation over HTTP, then kills the process outright and starts a new one on the same workspace. Every read answers the same, and every change in the log survives (gate item 3). About 17 s, runs in CI.
- **P1-18:** `GET /sessions/{id}/sensors` answered 400 on a new session because it matched on the wrong error text; it now returns an empty inventory when no data is loaded, and the Playwright smoke test has no allow-listed error left.
- **P1-15:** selections (decisions/0011), four new tools (93 → 97). `server/core/selection.py` resolves a tree of time ranges, direction sectors, value bands and record sets, combined by union and intersection, to a record mask: half-open bounds, sectors wrap through north, a missing value is never selected, and a definition that names a missing channel, an offset-less time or bounds that describe nothing is refused. `define_selection`, `delete_selection`, `list_selections`, `resolve_selection` keep named selections on `state.selections` (saved with the project) and resolve them against the working data on every use. 200 random nested definitions agree with an independent per-record evaluator in `tests/oracles.py`. Tiers 53 read / 32 change.
- **P1-16:** 23 statistics and charts take a selection. A declaration sets `selectable=True` (reads only; the registry refuses it on a change) and the wrapper publishes a keyword-only `selection` parameter, so every surface offers it with no edit to the functions. Named, the function runs on a copy of the session where every record outside the selection is **blank, not dropped**, in the working frame and the raw, shear and roughness timeseries, and the result gains `selection` (name, records, of records, basis). Blanking keeps the timestamps: dropped, every other record of a 10-minute series reads as a 20-minute cadence and ramps join records the selection separates (pinned by a test). `tests/test_selection_operations.py`: each of the 23 equals the same operation without a selection on a session pre-filtered with the oracle mask; the other 35 reads are listed with why they take none (stored results, the long-term series, the reanalysis, the data inventory). The MCP snapshot gains exactly the `selection` property on those 23; no published number moved.
- **P1-17:** series transport (decisions/0005), one new tool (97 → 98). `server/core/decimation.py` cuts a half-open window into at most `buckets` equal-width buckets (whole milliseconds) and returns each channel's exact minimum, maximum and valid count per bucket, or the records themselves when there are no more than buckets; zoom is a request for a narrower window. `get_series_window` (selectable) returns it as JSON and `GET /sessions/{id}/series` as an Arrow stream, both through `_series_window`; the route applies a selection's mask to the requested channels in the window only. Equal to an independent per-record bucketing in `tests/oracles.py` over 60 random windows. Measured (`python -m tests.measure_series_transport`, 5 years × 10 minutes × 60 channels, a 128 MB frame, median of 5): whole record at 2,000 buckets, Arrow 2.4 MB in 183 ms (JSON 5.4 MB in 402 ms); with a selection, Arrow 251 ms; a zoomed week (1,008 records, not decimated) 1.2 MB in 6.6 ms. Cutting the window before copying took the week from 72.6 ms, and masking the window instead of blanking a copy of the session took the selection from 624 ms. Tiers 54 read / 32 change. The frontend client (uPlot, refetch on zoom) is Phase 2.
- **P1-19a:** two reads changed the session, found by `tests/test_read_operations.py`, which runs every read on the synthetic pipeline's fully analysed session (`tests/synthetic_pipeline.py`, moved out of the disclosure test) and requires every field of the session unchanged; the route tests' mast has no reanalysis, so these refused there before writing anything. `run_clipping_analysis` keeps its result on the session and the uncertainty model takes its measured inter-annual variability from it, so it is declared a change now (read tier 54 → 53, change tier 32 → 33). `compute_air_density_timeseries` wrote an `air_density_kg_m3` column into the session's reference frame (or the working frame with `source="measured"`) that nothing reads; the density stays local. Published numbers identical.
- **P1-19:** every operation route has a typed result in the OpenAPI schema. `server/schemas/results/` holds one model per operation (one module per tool module, shared pieces in `_base.py`), named on the declaration (`@operation(result=..., preview_result=...)`) and published by the generated route with 400 and 502 as `ErrorDetail`. The routes do not validate against the models, so a wrong model cannot fail a call; `tests/test_operation_results.py` keeps them honest, validating strictly (extra fields refused) every response `tests/operation_samples.py` collects: 207 responses from all 98 operations and both dry runs, from the synthetic pipeline, every read on it and on the 120-day route-test mast, the remaining changes, and the network operations against the BrightHub and EarthDataHub fakes. Drafted from those samples and then read against each function for fields only some branches return (a partial-year warning, a skipped reanalysis leg, a hub measured directly, the unavailable energy sensitivity). Every float is `Number` (nullable), because NaN and infinity are sent as null. The run configuration and a selection definition are open models, since they keep keys the caller set; BrightHub's own documents are passed through untyped. The MCP surface is unchanged: the output schemas MCP clients see are still the plain object they were.
- **P1-20a:** `fastmcp`, `mcp`, `fastapi` and `pydantic` are pinned exactly (3.2.3, 1.27.0, 0.135.1, 2.12.5, the versions Phase 1 was built and tested on); they were `>=` ranges. They render the two surfaces the repository pins (the MCP tool snapshot and the committed OpenAPI schema) and the registry builds on FastMCP's `FunctionTool`, while CI installs the newest a range allows: on 2026-11-24 that was FastMCP 4.2.5, FastAPI 0.165.0 and Pydantic 2.14.4, none of which this code has run on. Phase 1 had not yet run in CI. Upgrade deliberately: refresh both snapshots and run the suite.
- **P1-20:** the TypeScript client is generated from the server's OpenAPI schema (decisions/0012). `frontend/src/api/openapi.json` is committed (`python -m tests.openapi_schema --write`; `tests/test_openapi_schema.py` fails when it differs from what the server serves); `npm run generate:api` turns it into `frontend/src/api/schema.d.ts` with `openapi-typescript` 7.13.0, and `src/api/client.ts` is a thin `openapi-fetch` 0.17.0 client (both pinned exactly) that adds the session header from the path. `--default-non-nullable false`: by default the generator marks every field with a default as required, which made `method` and `selection` mandatory in a request body and a result's optional fields mandatory in a response (caught by the type check). CI's frontend job runs `npm run check:api`, which regenerates the client and fails on any difference; tried by renaming a result field in the schema (exit 1) and restoring it (exit 0). Nothing calls the new client yet: `src/lib/api.ts` stays until the Phase 2 interface replaces it.

**2026-11-17 to 2026-11-19: workbench Phase 0.** P0-1 to P0-13 were on branch `phase0-stabilise`, merged into `master` by the owner as PR #5 (`f8a24ca`, 2026-11-18). P0-14 (`f2191ea`) was merged as PR #6 (`2c2f069`, 2026-11-19). Phase 1 runs on branch `phase1-foundations`. One task per commit; the task list and status are in `Claude outputs/WORKBENCH_PLAN.md` §8a.

- **P0-1 `e04446e`:** `K_SHEAR_ANALYST_SUPPLIED` 0.07 (entry below). `startup.ps1 -IncludeMcp` bound the unauthenticated SSE transport to `0.0.0.0`; it now binds to `127.0.0.1`. The "follows IEC 61400-12-1 / 61400-12-2" claim is replaced by a statement that no conformance claim is made.
- **P0-2 `ee24eac` (F1):** `normalise_speed_to_reference_density` carried the stall and pitch labels the wrong way round. IEC 61400-12-1 normalises wind speed for a pitch-regulated turbine and power for a stall-regulated one. The arithmetic applied was already the pitch one, so no number moved; `regulation` now defaults to `"pitch"`, `"stall"` is refused, and `density_normalisation.method` is `iec_61400_12_1_wind_speed_normalisation` (was `iec_61400_12_1_stall`). Basis: a public ECN/TNO report; the clause text has not been read.
- **P0-3 `f28347f` (F7):** `compute_mcp_readiness` said ready at 720 concurrent hours while the correction refuses below 4,380 (`MIN_CONCURRENT_HOURS`). It now uses that floor and reports `not_ready_reasons`. Pinned value moved: `tests/test_sensor_overview.py` readiness at 1,000 hours, ready True → False.
- **P0-4 `fe6d03d` (F8):** `compute_qc_diagnostics` counted range failures against a fixed 0-50 m/s; it now uses the `range_check` rule's own bounds (`_resolve_range_bounds`) and reports them.
- **P0-5 `ec5a0d5` (F3, F4):** the Copilot listed Anthropic, which the backend refuses; it now offers only `SUPPORTED_COPILOT_PROVIDERS` (pinned against `_PROVIDER_URLS` on both sides). Data-changing tools were on by default; they are now off unless the user opts in, because per-action approval does not exist yet.
- **P0-6 `100928f` (F9):** the sweep's uncertainty substitution (design doc §8.1) existed only in the browser and measured the swing of `total_uncertainty_pct`. It is now `uncertainty_substitution` in `server/core/sweep_analysis.py`, on `analyze_sweep_spread` and `POST .../spread`: per axis, the sample standard deviation of the long-term mean speed across level means as a % of the sweep mean (owner decision 2026-11-18), at least 3 levels (`MIN_LEVELS_FOR_EMPIRICAL`), max(parametric, empirical) per scenario for the MCP and vertical terms, the reference-source spread added. Stored rows are unchanged. With two reanalyses the reference-source term cannot fire. Measured on the two stored sweeps: LTC term 0.30% → 0.55% and 0.24% → 1.76%.
- **P0-7 `6748e02` (F5):** README described a 4.2 MW curve and said no AEP or capacity factor is computed. It now describes the default `generic-3.0MW-130m-IIA` (3.0 MW, 130 m, 226 W/m²) and the sensitivity table is re-measured on it, pinned by `tests/test_readme_energy_table.py` against the oracle.
- **P0-8 `d35ead6`, P0-9 `782545d`, P0-10 `ec2824a`:** campaign-dependent tests skip when files are absent; CI workflow; Playwright harness and smoke test. First CI run on GitHub (run 44375931264, 2026-11-18): all four jobs passed (backend on Ubuntu and Windows, frontend, Playwright). The smoke test allow-lists one known error: `GET /sessions/{id}/sensors` returns 400 on a new, empty session.
- **P0-11 `7cc16dd`:** chart-library spike, `spikes/chart-libraries/FINDINGS.md`. At one channel of 262,800 points, uPlot renders in 62 ms and brushes in 19.7 ms (Plotly 455 / 478, ECharts 123 / 245); regl-scatterplot renders 252,665 points in 256 ms and brushes in 50 ms (Plotly 407 / 182, ECharts 663 / 922). Plotly spends over 100 ms before its own selection callback. Recommendation: uPlot for time series, regl-scatterplot for scatters, server-side decimation with refetch on zoom, selections resolved on the server from the drawn bounds, Plotly only for the existing static figures.
- **P0-12 `e0987cb`, `40b31ba`:** docking-layout spike, `spikes/docking-layout/FINDINGS.md`. Dockview 8.9.1 and FlexLayout 0.11.2 behaved the same on every functional check under React 19; Dockview chosen on maintenance (70 releases in 12 months against 17), with a custom tab component to remove its `nested-interactive` axe violation.
- **P0-13:** twelve decision records in `decisions/`. Eight are decided (by the owner or by measurement); four are proposed and must be confirmed before Phase 1: the operation registry (0009), the project store with flags (0010), server-side selections (0011), and the frontend stack (0012).
- **P0-14 (decision 0009, accepted by the owner 2026-11-19, with WindKit narrowed):** the owner asked whether WindKit should become the core; the answer recorded in `decisions/0009-operation-registry.md` is no, only where it is the reference implementation. Removed the 142 pass-through tools in `server/tools/windkit/`, their 142 HTTP routes and `windkit_schemas.py`, `tests/test_windkit.py` and `tests/test_windkit_submodule_smoke.py` (94 tests), the never-written `SessionState.windkit_data` and its `windkit` completed-step token, and the frontend config values naming WindKit modes the backend never implemented. Tool count 232 → 90 (`EXPECTED_MCP_TOOLS`, `tests/test_phase4.py`). The two LTC wrappers were broken: on 2.0.1 every call raised inside WindKit, and they passed the measured series where WindKit expects the reference, so on 2.2.0 they would have returned a long-term mean 38.9% low on a synthetic year. WindKit pinned `>=2.0,<2.1` → `==2.2.0`: Weibull A and k bit-identical on all 16 campaign speed sensors; 2.2.0 never prompts for attribution, so the `WINDKIT_*` variables left CI and the Playwright config. `tests/test_windkit_adopted.py` pins the version and the Weibull fit against exact moments, and checks native variance ratio against `VarRatMCP` (equal to 1e-9) and native Huber linear against `LinRegMCP` OLS within 0.25% (measured: slope +0.081%, long-term mean -0.066%). No published number moved; `ENGINE_VERSION` unchanged.
- **Owner decisions, 2026-11-19:** records 0010 (project store, flags, operation log), 0011 (selections on the server) and 0012 (frontend stack) accepted; record 0013 takes the six long-term direction and temperature decisions, all as recommended (direction at the nearest vane's height, no veer extrapolation; 6.5 K/km lapse rate with one temperature height; methods chosen by a held-out measurement; a missing sensor marks its column unavailable instead of refusing the export; air density as a fourth column; direction and temperature not swept, and the exclusion stated explicitly in the sweep manifest and summary, the Interrogate page and the export provenance). No decision record is open.

**2026-11-17: owner decisions for the workbench build, and the analyst-supplied constant raised.**

- **`K_SHEAR_ANALYST_SUPPLIED` 0.05 → 0.07 (owner, 2026-11-17).** A typed-in exponent has no measured dispersion, so it takes the largest assumed constant and never scores better than the log law. Same heights (80 m, 120 m hub): 2.03% → 2.84%. Pinned value moved: `tests/test_shear_method_validation.py` analyst `k_shear` 0.05 → 0.07. **`ENGINE_VERSION` is now `"2026.11.2"`.**
- **D3 accepted (owner, 2026-11-17):** duplicate scenarios are skipped and listed in the manifest. D1, D2's constants and D3 are now all accepted; the per-campaign vertical rule in `docs/design/vertical-uncertainty.md` is approved with the note's recommended values (12-month blocks, floor 0.015, one estimate per campaign and shear model, no small-sample correction, interpolated hub stays 1%) and is not built.
- **The product's deliverable (owner, 2026-11-17): a long-term-corrected dataset carrying wind speed, wind direction and temperature for at least one hub height.** Today only speed is long-term corrected; direction and temperature correction are new methods to design, measure and disclose before building.
- **Workbench build decisions (owner, 2026-11-17), full list in `Claude outputs/WORKBENCH_PLAN.md` §8:** the old interface is retired once the new one passes its gates; Anthropic and OpenAI-compatible providers first; API keys in the OS keychain; own models as a Python plugin or an ONNX file; every assistant data change needs approval; local server in the browser, Windows first; existing sessions and sweeps are not migrated; standards traced to IEC and MEASNET only. Work runs on branch `phase0-stabilise`.

**2026-11-16: owner decisions, and the log-law vertical constant raised.**

- **`K_SHEAR_LOG_LAW` 0.05 → 0.07 (D2, approved by the owner 2026-11-16).** The held-out height matrix (`docs/design/vertical-uncertainty.md`) measured the log law at 0.065 pooled and 0.070 in the worst year at Launakalana, 0.038 and 0.069 at Boxkite, so 0.05 understated a single-year campaign at both sites. Same heights (80 m measurement, 120 m hub): vertical term 2.03% → 2.84%. Only `shear_method: "log_law"` moves; the power-law and analyst-supplied constants are unchanged. Pinned value moved: `tests/test_shear_method_validation.py` log-law vertical 2.03 → 2.84. **`ENGINE_VERSION` is now `"2026.11.1"`**, because every log-law sweep leaf's `total_uncertainty_pct` moves; a sweep stamped `2026.11` is not comparable with one stamped `2026.11.1`. The evidence-based per-campaign rule in the design note is still not built.
- **Scope (owner, 2026-11-16): the product's output is long-term-corrected wind data, not energy yield.** No losses chain, no net P50/P90. The "no AEP for the main pipeline" limitation below is a standing decision, not a gap to close.
- **Deployment (owner, 2026-11-16): local, single user first.** Record who did each action so logins can be added later; do not build auth now.
- **Standards (owner, 2026-11-16): trace against what is publicly available; a purchased standards text and an external benchmark are not required.** Claims must stay at "traced to", never "compliant with".
- `handover-2026-11-14` was merged into `master` on 2026-11-16. The workbench redesign plan is `Claude outputs/WORKBENCH_PLAN.md` (untracked, local).

**2026-11-14 (handover T1–T12 and 11a671a; verified 2026-11-15): the hub series, SpeedSort, vertical uncertainty and sweep engine changed on purpose. Sweeps run before this work are not comparable with any run after it.** Sweep manifests now carry `engine_version: "2026.11"` (`ENGINE_VERSION` in `server/core/scenario_result.py`, also hashed into `fixed_prefix_hash`); manifests written earlier have no key and read as `None` in `get_sweep_summary`. Re-run rather than compare. **Owner decisions:** D1 (sub-gate records are extrapolated, not dropped) was **accepted by the owner on 2026-11-15**. D2 (the interim vertical-uncertainty rule, T4): the owner approved raising the log-law constant on 2026-11-16 (see the 2026-11-16 entry above); the evidence-based replacement is designed in `docs/design/vertical-uncertainty.md` and not built. D3 (duplicate scenarios are skipped and listed in the manifest; the row schema is unchanged) is pending.

1. **Hub extrapolation keeps sub-gate records (T1, D1, accepted by the owner 2026-11-15).** The 3.0 m/s shear gate governs the fit only. `computed[below_gate] = np.nan` had deleted every record below it from the hub series (Launakalana at 120 m: 25% of records lost, long-term mean +5.8% to +12.8%). Sub-gate records are now extrapolated with the table's exponent and counted in `below_shear_gate` / `records_below_extrapolation_gate`; `method_counts.extrapolated` includes them, and `extrapolation_gate_warning` says they were extrapolated. The shear fit gate is unchanged. The hub series changes on every campaign. Pinned values moved: Boxkite 150 m `method_counts.extrapolated` 689 → 757 (`below_shear_gate` stays 68) and hub mean 9.62020702747371 → 9.612528096642762 (`tests/test_uploaded_dataset.py`); the same campaign through HTTP (`tests/test_api_workflow.py`) 689 → 757.
2. **Held-out height oracle (T2, `tests/test_heldout_height.py`).** Predicts a withheld sensor from the two below it and compares series means. Before → after: Launakalana 80 m from 40/60 m **+23.08% → -0.43%** (coverage 69.7% → 100%); Boxkite 250 m from 180/200 m **+4.91% → -0.40%** (coverage 93.7% → 100%). The handover expected -0.46% for Boxkite; the measured figure is -0.40%, inside the < 1% assertion.
3. **SpeedSort fits through rank-sorted pairs (T3).** `_speedsort_fit` sorts the reference and measured speeds independently, then applies the threshold to the sorted reference. Sorting before masking is what fixes the bias; masking first does not. All three fit sites use it (all-sector fallback, per-sector, non-directional). Launakalana, hub 120 m from 60 m and 80 m, ERA5 reference, concurrent mean bias and long-term mean, before → after: non-directional **-0.3975 → -0.0933 m/s** (long-term mean 4.4903 → 4.8262 m/s); directional **-0.3947 → -0.1845 m/s** (long-term mean 4.4064 → 4.6592 m/s). Responses carry `fit_basis: "rank_sorted"`. Prediction, the dog-leg segment and the thresholds are unchanged. `tests/test_speedsort_rank_sorted.py` asserts mbe in -0.15..+0.05 (non-directional) and -0.25..+0.05 (directional), and that sorted and time-paired fits agree to 1e-9 on perfectly correlated data.
4. **Vertical uncertainty: INTERIM rule so measuring never scores worse than assuming (T4, D2, NEEDS OWNER SIGN-OFF).** A fitted profile used `k_shear = shear_std` (the scatter of 10-minute exponents), which measured 8.03% of vertical uncertainty against 1.22% for an analyst-typed exponent or the log law. It now takes `k_shear = min(shear_std, K_SHEAR_ASSUMED_POWER_LAW)`. The constants are named in `server/tools/uncertainty.py`: `K_SHEAR_ASSUMED_POWER_LAW = 0.03`, `K_SHEAR_LOG_LAW = 0.05`, `K_SHEAR_ANALYST_SUPPLIED = 0.05`. A new `shear_method: "analyst_supplied"` takes the analyst constant. `derive_uncertainty_inputs` selects `analyst_supplied` for an analyst exponent and `log_law` for a roughness-derived profile with no shear table. The response reports `inputs.k_shear` and `inputs.k_shear_basis`. Same heights (80 m measurement, 120 m hub), formula values: fitted 1.22% ≤ assumed 1.22% ≤ analyst-supplied 2.03% (`TestVerticalUncertaintyOrdering`). **This is interim.** The constants are the values the code already used, promoted to names; the evidence-based vertical term from held-out height error is not built and replaces this rule once designed. Pinned values moved: `tests/test_shear_method_validation.py` shear_std 0.10 vertical 4.05 → 1.22; `tests/test_uncertainty_inputs.py` analyst-supplied `shear_method` simple_power_law → analyst_supplied, with its basis text changed.
5. **Engine version stamped (T5).** `ENGINE_VERSION = "2026.11"` is hashed into `fixed_prefix_hash` (`09d31b854a55b0e2` → `bc0e680184f7bc7d` on the sweep test fixture) and written to every manifest. `load_sweep` returns old manifests unchanged. `tests/oracles.py` `fixed_prefix_hash_oracle` takes the version.
6. **An unusable reference policy no longer fails its siblings (T6).** `resolve_sensors` is split into `resolve_fit` (axis A1 and the `can_fit_shear` check) and `resolve_reference` (axis A2); `resolve_sensors` keeps its signature. The sweep's shear-prefix step calls `resolve_fit` only, so each leaf refuses on its own reference policy. Before, on Boxkite with `("redundant_boom", "nearest_2")`, usable `nearest_2` leaves failed whenever `redundant_boom` was the first leaf of their group, so results depended on list order. Test `test_an_unusable_reference_policy_does_not_fail_its_siblings`. No pinned values changed.
7. **Duplicate scenarios are skipped (T7, D3).** `config_hash` now hashes the spec without `sensor_selection`: policy names are labels, and the resolved columns already carry what the computation reads. `run_sweep` keys each leaf on its resolved fit columns, reference columns, shear model, reference source, LTC algorithm, hub height and analyst exponent; a key already run in this sweep is not run again. Skipped leaves are listed in `manifest.duplicates_skipped` (each names both policies and `same_as`, the config hash of the row that ran), counted in `counts.duplicates_skipped`, and announced by a `scenario_skipped_duplicate` progress event. The row schema and `ScenarioResult` are unchanged. Every config hash in the `_small_spec` test fixture moved (the policy names left the hash); `fixed_prefix_hash` did not. Two policies that resolve to the same sensors (Launakalana: `availability_90` and `redundant_boom`) previously ran twice with identical numbers.
8. **The sweep no longer extrapolates reanalysis it never reads (T8).** `_extrapolate_to_hub_height` gains `extrapolate_reanalysis` (default `True`, so the MCP tool and HTTP route are unchanged). The sweep's extrapolate stage passes `False`, returns `{"status": "skipped", "reason": "not_requested", "wrote_hub_column": False}` for the reanalysis, and reports `reanalysis_status: "not_run"`. The sweep's LTC reads the native `Spd_100m` / `Spd_50m` columns, never a hub-height reanalysis column. Equality check on 68 rows across three sweeps (synthetic default 4, synthetic wide 48, Launakalana 16): config hashes identical, maximum absolute difference in `long_term_mean_speed_mps` and `total_uncertainty_pct` = 0. Timings 1.68 → 1.96 s, 8.54 → 7.37 s, 1.53 → 1.41 s. The 4.5 s of 8.0 s saving from the review was **not reproduced**: these fixtures carry little node-frame data.
9. **Rows and manifest share one prefix hash (T9).** `build_result` recomputed `fixed_prefix_hash` on the scenario state, whose hub height is the leaf's own. A sweep at hub 100 m on a 120 m session gave rows hashed `8e1393d1b7205133` under a manifest hashed `bc0e680184f7bc7d`. The prefix is now computed once in `run_sweep` and passed in.
10. **The interpolation flag uses the scenario's own reference heights (T10).** `is_hub_interpolated` takes `reference_heights` (falling back to every mapped height). A scenario restricted to 40/60 m with a 90 m hub is extrapolated, so it takes the extrapolated vertical term; the same hub with 80/100 m is interpolated (1% vertical). Before, any sensor above hub made a below-hub scenario count as interpolated. No pinned sweep value moved.
11. **`fork_session` copies every session field (T11).** `_clone_session_state` never copied nine fields: `timezone`, `clipping_result`, `data_version`, `derived_versions`, `ltc_matching_disclosure`, `shear_clamp_stats`, `roughness_clip_stats`, `executed_nodes`, `persist_result_files`. A fork lost its site UTC offset and every staleness stamp. They are now copied (deep copies for containers); identity fields are named in `_CLONE_EXCLUDED`. A coverage test requires every `SessionState` attribute to be cloned or excluded.
12. **Sweeps checkpoint as they go (T12).** With persistence on, `run_sweep` writes an interim manifest carrying `in_progress: true`, plus the rows and runconfigs so far, after every shear-prefix group. The final write has no `in_progress` key; `list_sweeps` reports it. A crash in the second group now leaves the first group loadable (`tests/test_sweep.py`). All writes go through a `.tmp` file and `os.replace` (`_write_json_atomic`). Windows refuses the replace while another process holds the target, so it is retried on `PermissionError` (`_REPLACE_ATTEMPTS = 10`, `_REPLACE_RETRY_DELAY_S = 0.2`, about 2 s) and then raised. The cause of the lock is inferred, not identified.
13. **Unknown `shear_method` is refused on the MCP path (11a671a).** The MCP `calculate_uncertainty` tool has no Pydantic layer, so an unknown name fell through to the 0.03 branch silently. It now raises, naming `VALID_SHEAR_METHODS`, and a test pins that whitelist to the HTTP schema's `Literal`. The Ensemble view's shear-method dropdown gains `log_law` and `analyst_supplied`.

**Known residuals, not fixed here:**
- The SpeedSort dog-leg segment below the threshold leaves a residual negative mean bias (-0.09 m/s non-directional, -0.18 m/s directional at Launakalana, item 3). Removing it is an owner method decision and was not attempted.
- D1, D2 and D3 are all accepted (2026-11-15 to 2026-11-17); D2's evidence-based rule is approved and not built.
- T7 matches a duplicate only against a *completed* first run; a failed first leaf does not shadow its duplicate.
- `SweepMonitor`'s live event list does not show the `scenario_skipped_duplicate` event. (Fixed 2026-11-15, D3 follow-up: `get_sweep_summary` and the spread decomposition report `duplicate_levels` per policy axis, the Interrogate page labels them "same sensors: X = Y", and the Outcome panel counts `duplicates_skipped`.)
- T12 checkpoints set `finished_at` to the checkpoint time, and `get_sweep_summary` / `analyze_sweep_spread` do not flag `in_progress` sweeps.
- T12 rewrites every accumulated runconfig at each checkpoint: about 94,500 writes, roughly 5 minutes at 3.3 ms per write, for a 9,000-leaf, 20-group sweep. Writing only runconfigs not yet on disk would cut that to about 9,000 writes; not done.
- The frontend `WorkflowView` "Upload config" test times out intermittently under full-suite load (it passes alone).

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
