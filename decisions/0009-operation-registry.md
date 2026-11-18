# 0009. One operation registry generates every surface

**Status:** Proposed. Designed in the build plan; to be confirmed before Phase 1 starts.

## Context

Today an analysis capability is written by hand in several places: the MCP tool in
`server/main.py`, the HTTP route in `server/api/routes/`, the executor's
`TOOL_MODULE_PATHS`, the chat tool tiers in `server/api/routes/chat.py`, the sweep's axis
lists, and about nine frontend copies of the method list. Three defects in this session's
audit came from copies drifting: the Copilot offering a provider the backend refused (F3),
the readiness diagnostic using a floor the correction did not (F7), and the QC diagnostic
using bounds the range rule did not (F8).

## Proposal

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
today's 232 tools until a change is deliberate.

## To decide

- Whether WindKit's roughly 180 pass-through wrappers become operations, or stay outside
  the registry as a tool set the assistant cannot call by default.
