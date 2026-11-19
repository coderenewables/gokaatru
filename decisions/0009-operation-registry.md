# 0009. One operation registry generates every surface

**Status:** Accepted (owner), 2026-11-19, with WindKit narrowed to the functions it is the
reference implementation for. The registry is built in Phase 1.

## Context

Today an analysis capability is written by hand in several places: the MCP tool in
`server/main.py`, the HTTP route in `server/api/routes/`, the executor's
`TOOL_MODULE_PATHS`, the chat tool tiers in `server/api/routes/chat.py`, the sweep's axis
lists, and about nine frontend copies of the method list. Three defects in this session's
audit came from copies drifting: the Copilot offering a provider the backend refused (F3),
the readiness diagnostic using a floor the correction did not (F7), and the QC diagnostic
using bounds the range rule did not (F8).

## Decision

Each analysis step is declared once as an **operation**: name, typed inputs and outputs, a
parameter schema with units and defaults, whether it reads or changes data, its pipeline
stage, the disclosure fields it returns, its standards references, a dry run for changing
operations, and a code version. From that declaration are generated:

- the MCP tool and the HTTP route,
- the canvas palette entry and its parameter form,
- the sweep axis level and its availability check,
- the assistant's tool and its read or change tier,
- the README defaults row and the traceability row.

Existing functions are wrapped, not rewritten. A test asserts the generated surface equals
today's 90 tools until a change is deliberate.

## WindKit

The owner asked whether DTU's WindKit should become the core, replacing native functions
wherever possible. It should not: WindKit 2.2.0 has no cleaning, gates, hub-series
construction or LTC uncertainty, and has two of GoKaatru's five long-term corrections. Where
the two overlap, the native code is the audited version and WindKit's defaults guess where
GoKaatru refuses (an exponent of 0.143 when none is given, column names inferred from
headers). WindKit is used where it is the reference implementation, and nowhere else.

**Adopted.** Each enters the registry as a native operation that calls WindKit, with its
disclosure fields, once the feature that needs it is built:

| WindKit function | Used for | When |
| --- | --- | --- |
| `weibull.fit_weibull_wasp_m1_m3` | Weibull A and k in `compute_weibull_params` and the wind-climate statistics | In use |
| `ltc.LinRegMCP`, `ltc.VarRatMCP` | A second implementation that the native linear and variance-ratio corrections are tested against; not used in any result | In use, in `tests/test_windkit_adopted.py` |
| `bwc_from_tswc`, `bwc_to_file` (WAsP TAB) | The TAB frequency table of the long-term dataset | When the dataset export is built |
| windIO readers and writers; `read_wtg` | Interchange formats and turbine files | When those features are built |
| `vinterp_wind_direction`, `veer_extrapolate` | Direction at hub height | Candidate: measured against held-out sensors first, as T2 did for speed |

`fit_weibull_wasp_m1_m3_fgtm`, the variant that matches the share of records above the mean,
is a candidate to measure against the current fit before any change.

**Removed (2026-11-19).** The 142 pass-through tools in `server/tools/windkit/`, their 142 HTTP
routes and their request schemas. No pipeline stage called them and the assistant could not
reach them. The two long-term correction wrappers were broken on both versions: on 2.0.1 every
call raised inside WindKit, and they passed the measured series where WindKit expects the
reference, so on 2.2.0 they would have returned a long-term mean 38.9% low on a synthetic
year. The tool count went from 232 to 90.

**Version.** WindKit is pinned to exactly 2.2.0. Upgrading from 2.0.1 left Weibull A and k
bit-identical on all 16 speed sensors of the three reference campaigns, and no published
number depends on any other WindKit function. Between those versions `LinRegMCP`'s default
`ws_cutoff` changed from 3.0 to 0.0, so every adopted call passes its parameters explicitly
and an upgrade needs `tests/test_windkit_adopted.py` green.

## Consequences

- An adopted WindKit function is never exposed as a WindKit tool; it is a step of a native
  operation, so it carries the operation's refusals and disclosure fields.
- If a published number comes to depend on WindKit, its version goes into `ENGINE_VERSION`.
