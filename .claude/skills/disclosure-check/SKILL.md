---
name: disclosure-check
description: Apply GoKaatru's disclosure convention when adding or changing a default, clamp, threshold, or fallback that affects a reported number. Use whenever a code change introduces or modifies a magic number, bound, or silent substitution in server/core or server/tools.
---

# Disclosure convention

GoKaatru's audit trail (`docs/audit/FIXES.md`) is ~30 rounds of finding exactly this pattern:
a constant or fallback quietly changes a reported number and nothing says so. The fix is
always the same three-part shape. Apply it proactively rather than waiting for an audit to
catch it.

## The three parts, every time

1. **Named constant, not an inline literal.**
   ```python
   # not this:
   if alpha > 1.0 or alpha < -1.0: alpha = clip(alpha, -1, 1)
   # this:
   SHEAR_ALPHA_BOUND = 1.0  # module-level, with a one-line comment on provenance if non-obvious
   ```
   If the value should be user-overridable (most methodology constants should), make it a
   parameter with the current value as its default — existing numbers stay unchanged, but the
   assumption becomes visible and movable. This is the pattern behind
   `concurrent_months_cap`, `project_life_years`, `min_window_years`,
   `CLIMATE_DEVIATION_EXPONENT`, etc.

2. **A response field reporting whether/how it fired.** Not just "the clamp exists" — how
   often did it actually bite on this data. Look at existing examples for the shape:
   `records_clamped` / `clamped_fraction` (shear), `filled_cells` / `filled_fraction`
   (table fill), `alpha_reclamped_records` (extrapolation), `duplicate_timestamps`
   (ingest). Add a `warning` field when the rate crosses a meaningful threshold (the
   convention across the codebase is roughly 5% for "worth flagging").

3. **A README row.** Add to whichever table fits:
   - **"Defaults that affect results"** — for a constant/threshold with a default value.
   - **"Disclosure fields — read these before trusting a number"** — for the response field
     itself, naming which tool response it appears in and what it means.
   Match the terse, precise style of existing rows — state the number, the direction of the
   effect, and (if measured) the magnitude on real data. Don't editorialize; let the measured
   number make the point.

## When magnitude matters

If you're not sure whether a substitution/clamp is consequential, measure it — run the
affected function on the bundled fixtures in `data/uploads/` or synthetic data spanning the
edge case, and report the actual percentage effect. This is the dominant pattern in
`docs/audit/FIXES.md`: almost every fix entry states a measured number
("−1.74%", "+94.5%", "0.24% spread") rather than asserting severity qualitatively. A
measured magnitude is far more useful to a future reader than "this could matter."

## When NOT to add disclosure

Don't over-apply this to genuinely inconsequential internal constants (loop bounds, retry
counts, UI debounce timers). The convention exists for anything that changes a **reported
physical/statistical number** a wind analyst would read and trust. If you're unsure whether
something qualifies, ask: "would a bank's technical advisor need to know this to reconcile
our number against WAsP/Windographer?" If yes, disclose it.
