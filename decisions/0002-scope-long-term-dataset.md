# 0002. The product's output is a long-term-corrected dataset, not an energy yield

**Status:** Accepted (owner). 2026-11-16: no energy chain ("long-term-corrected data is the
goal"). 2026-11-17: the dataset carries wind speed, wind direction and temperature for at
least one hub height. 2026-11-17: the existing indicative energy figures are kept, labelled
indicative, and not extended.

## Context

The plan proposed reversing the recorded "no energy yield" decision and building losses,
net energy and energy-basis P50/P90. The owner declined. What the product hands on is the
wind resource, for an energy tool downstream to consume.

## Decision

- **Deliverable:** a long-term-corrected, hub-height dataset with wind speed, direction and
  temperature, its frequency table, its uncertainty budget and its full provenance (input
  file hashes, operations, engine version, methods and their constants).
- **Formats:** CSV and Parquet time series and a WAsP TAB frequency table (owner,
  2026-11-17). A written HTML/PDF report comes late (Phase 7).
- **Not built:** project power curve import, loss model, wakes, net energy, energy-basis
  P50/P90.
- **Kept as they are:** the sweep's indicative gross AEP and capacity factor off a generic
  curve, and the energy sensitivity factor, labelled indicative.

## Consequences

- Only speed is long-term corrected today. Direction and temperature need methods designed,
  measured and disclosed before they are built: `docs/design/long-term-direction-temperature.md`
  (local), with six owner decisions open.
- The README "Known limitations" entry on energy was corrected in P0-7 (`6748e02`).
