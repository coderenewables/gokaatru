# 0013. Long-term direction, temperature and air density in the dataset

**Status:** Accepted (owner), 2026-11-19. Methods to be chosen by measurement before they are
built (Phase 6).

## Context

The product's deliverable is a long-term-corrected dataset carrying wind speed, wind
direction and temperature for at least one hub height ([0002](0002-scope-long-term-dataset.md)).
Only speed is long-term corrected today. Direction is read from the reference and used only
as a sector key (SpeedSort) or a feature (XGBoost). Temperature is interpolated from the
reference and used only for air density.

Candidate methods, from the design note (local, `docs/design/long-term-direction-temperature.md`):

- **Direction:** a per-sector circular-mean offset between site and reference, interpolated
  between sector centres (D-A); one offset for all directions (D-C); the reference unchanged
  (D-B, the baseline). Fitted only on records above a speed threshold, because a vane in calm
  air reports noise.
- **Temperature:** a 12×24 month-by-hour bias table (T-A, the same shape as the shear
  table); a linear regression on the reference (T-B); a lapse rate alone (T-C, the
  baseline).

## Decision

1. **Direction height.** Direction is reported at the height of the vane nearest the hub,
   with that height and its gap to hub height disclosed. Veer is not extrapolated. If two
   vanes bracket the hub, interpolation between them is allowed and disclosed.
2. **Temperature to hub.** With one temperature height, the standard-atmosphere lapse rate
   of 6.5 K/km carries it to hub height, as a named constant whose use is reported. With
   two heights, the measured gradient is used.
3. **Method choice by measurement.** The default for each parameter is the method that wins
   a held-out test on the three reference campaigns against ERA5 and MERRA-2: fit on
   alternating calendar months, predict the others, swap and pool. Direction is scored by
   circular bias, circular absolute error and the error in sector frequencies; temperature by
   bias and absolute error, overall and by month. No method is fixed before that.
4. **Missing sensor.** With no direction or no temperature sensor, the dataset is still
   exported with the parameters that exist, and the missing one is marked unavailable with
   the reason. It is never filled in from the reference unchanged.
5. **Air density.** Long-term air density at hub height is a fourth column, after speed,
   direction and temperature, from the long-term temperature and the reference's pressure
   and dew point.
6. **Not in the sweep, and said so.** Direction and temperature are not sweep axes at first;
   they are computed once, for the scenario the analyst exports. The exclusion is stated
   explicitly wherever a result could be read as covering them: the sweep manifest and
   summary, the Interrogate page and the exported dataset's provenance. Air density follows
   temperature and is likewise not swept.

## Consequences

- Direction and temperature each carry their own accuracy from the held-out test (circular
  RMSE in degrees, RMSE in kelvin), reported beside the series. Neither enters the
  wind-speed uncertainty budget.
- Every constant (the direction speed threshold, the thin-sector minimum, the lapse rate)
  gets a named constant, a response field saying whether it fired, and a README row with its
  measured basis.
- WindKit's direction interpolation is a candidate for the bracketing case in decision 1,
  measured first ([0009](0009-operation-registry.md)).
