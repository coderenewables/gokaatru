# 0008. Your own models: Python plugin and ONNX file first; pickle refused

**Status:** Accepted (owner), 2026-11-17. The first bring-your-own item is an analyst-loaded
long-term reference series (owner, 2026-11-17).

## Decision

- **Python plugin,** installed in the environment and discovered by entry point, implementing
  a small declared contract (for a long-term-correction method: fit on concurrent data,
  predict on the reference, return the standard metrics). It runs with full access to the
  machine, which is acceptable for a local single-user install ([0003](0003-local-single-user.md)).
- **ONNX model file** with a feature manifest, loaded without running foreign code.
- **Pickle and joblib files are refused,** because loading one runs arbitrary code.
- A remote method behind an MCP server or HTTP endpoint comes later.
- Every route gets a per-scenario timeout with failure contained to that scenario, a contract
  test suite the plugin must pass before it is offered, and an **identity hash** (code or
  weights) folded into the scenario's config hash and the manifest, so two models never look
  like one.
- The same contract pattern then applies to shear models, reference sources and QC rules.
- **First item:** an analyst-supplied reference series, registered as a reference source
  beside ERA5 and MERRA-2.

## Consequences

- A third reference source is what lets the sweep's reference-source uncertainty term apply:
  under the three-level rule of P0-6 (`100928f`), two reanalyses cannot produce one.
