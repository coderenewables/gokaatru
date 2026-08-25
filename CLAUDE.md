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
- **`server/`** — Python MCP server (FastMCP) + FastAPI web API. 223 tools across ingest,
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

tests/                    # ~60 backend test files (pytest) — includes oracles.py, an
                           #   independent-implementation oracle harness used to verify
                           #   fixes without importing from server/
docs/                     # LOCAL ONLY — gitignored (see below)
```

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

Current baseline (verified 2026-08-25): 927 backend tests passing / 2 skipped, 178 frontend
tests passing, frontend typecheck clean, 223 MCP tools registered, and
`ruff check server/ tests/` clean. (The 2026-08-19 verification report's 785/117 figures are
stale — the project has added the sweep/Analysis Engine test suite and the F-09/15/16/23/26
fix-round tests since. `validate-gokaatru` always re-derives the live count rather than
trusting either baseline.)

**Ruff was not clean before 2026-08-25** — 185 findings (97 E501, 36 I001, 31 F401, 17 W292,
3 F841, 1 F811) had accumulated because `ruff>=0.1` is unpinned and the check was not being
run to zero. They are all fixed now; keep it at zero rather than letting a second wall build.

## Current state (2026-08-23)

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
- **Why a given constant/clamp/threshold has the value it has**: `docs/audit/NN-*.md` (the
  step that covers that area) then `docs/audit/FIXES.md` (search the finding ID).
- **Sweep/Analysis Engine internals and unresolved design questions**:
  `docs/design/analysis-engine.md`.
