# 0004. Methods are traced to public standards material; no conformance claim

**Status:** Accepted (owner). 2026-11-16: work from publicly available material; purchased
texts and an external benchmark are not required. 2026-11-17: trace to IEC and MEASNET only.

## Context

No certification exists for wind resource software. What a lender's technical advisor
checks is traceability: which clause a method draws on, the test that shows it, and every
deviation. The repository claimed it "follows IEC 61400-12-1 / 61400-12-2 conventions";
nothing relates to 61400-12-2 and the clause numbers in docstrings were never checked
against the text.

## Decision

- The only permitted wording is "traced to". Never "compliant with" or "follows".
- A traceability file in the repository holds one row per requirement: clause, source
  actually consulted (edition, and whether the clause text or a secondary source was read),
  the operation that implements it, the test that proves it, and a status (implemented,
  deviates with the reason, or not applicable).
- A citation that could not be checked against the clause text says so.
- Scope: IEC 61400 parts and MEASNET site assessment. National guidelines (FGW TR6 and
  others) are out of scope unless a project needs them.

## Evidence

- The conformance sentence was removed in P0-1 (`e04446e`).
- The air-density labels were found inverted (F1) and corrected in P0-2 (`ee24eac`), on the
  basis of a public ECN/TNO report that applies the rule and cites the standard. The clause
  text itself was not read, and the docstring says so.

## Consequences

- The traceability file and its tests are built in Phase 6; every operation's declaration
  ([0009](0009-operation-registry.md)) carries its clause references so the file and the
  report's methods section come from one source.
