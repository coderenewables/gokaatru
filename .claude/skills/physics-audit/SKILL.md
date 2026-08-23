---
name: physics-audit
description: Extend or re-open GoKaatru's physics/logic audit — investigate a suspected defect in the wind-resource math, register a finding, and fix it following the project's established audit methodology. Use when asked to review, audit, or dig into the correctness of a specific calculation, formula, or statistical method in server/core or server/tools.
---

# Physics/logic audit methodology

GoKaatru completed a 10-step audit (`docs/audit/00-plan.md`) targeting physics validity,
methodological defensibility, and numerical correctness "under adversarial-but-realistic
data" — the framing was always "what would a bank's technical advisor attack," not a typo
hunt. This skill is how to extend that work correctly, whether resuming the formal audit or
investigating one specific suspicion.

## Before starting

Read `docs/audit-verification-report.md` §4 ("Still open — the complete list") — it names
seven genuinely unresolved finding IDs (F-09, F-15, F-16, F-23, F-24, F-25, F-26) that were
never scheduled for a fix round. If your task overlaps one of these, start there instead of
re-deriving it from scratch. Also check the relevant `docs/audit/NN-*.md` step document for
prior analysis of the area you're touching — a lot of ground has already been covered and
re-investigating a "measured away to nothing" finding (F-06, F-13) wastes effort.

## Method

1. **State the adversarial question precisely.** Not "is this shear calculation right" but
   "what data shape would make this calculation wrong, and by how much." The step documents
   model this well — read one for the pattern (e.g. `docs/audit/05-vertical-profile.md`).

2. **Build or reuse an independent oracle.** `tests/oracles.py` deliberately imports nothing
   from `server/` — it's a from-scratch reference implementation of closed-form physics/stats
   so the production code can be checked against something that couldn't have inherited its
   bug. If the finding is in an area with an existing oracle, use it; if not, consider adding
   one before trusting a fix.

3. **Measure the magnitude, don't just assert direction.** Every entry in
   `docs/audit/FIXES.md` reports a measured effect size on real or realistic synthetic data —
   "±5.4% overshoot", "−1.74% on hub density", "0.24% spread". A finding without a measured
   magnitude is not actionable: a reviewer (including a future you) can't tell if it's the
   next high-severity fix or noise.

4. **Decide fix vs. disclose vs. non-finding.** Three outcomes, all legitimate:
   - **Fix it**, if there's a clearly more-correct approach (most findings). Use the
     `disclosure-check` skill for the response-field/README part of the fix.
   - **Disclose it**, if it's a genuine methodology trade-off with no clearly-better answer
     (e.g. F-38 regression variance attenuation — inherent to slope-based methods, not a bug;
     the fix was to report `variance_ratio_to_reference` so the trade-off is visible).
   - **Measure it away**, if investigation shows the "finding" isn't actually wrong (F-13 —
     the MoMM sample floor initially looked like a 24× overstatement; measuring it showed the
     floor was the *correct* denominator). Record the measurement in a test so it's not
     re-investigated.

5. **Write a reproducing test**, ideally against `tests/oracles.py`, that pins the corrected
   behavior — so a regression flips the assertion, per the convention stated at the top of
   `docs/audit/FIXES.md`.

6. **Record the finding.** If working the formal audit, add a register entry to the relevant
   `docs/audit/NN-*.md` with a severity (does it change a reported number, and by how much?).
   Either way, apply the `disclosure-check` skill's three-part pattern for the fix itself, and
   update README's "Known limitations" if the outcome is "disclose, not fix."

## A caution from the audit's own history

`docs/audit-verification-report.md` §5 records a case where a verification pass repeated a
prior explanation of a test failure ("stale assertion, behavior correct") without
independently checking it — and the explanation was wrong, concealing a real bug. When
verifying someone else's fix (including a past Claude session's), read the code the test
exercises yourself rather than trusting the note that dismisses it.
