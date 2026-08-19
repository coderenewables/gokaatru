// The disclosure panel is the only route by which the logic audit's findings reach a
// screen, so these tests use payload shapes taken from the real tool responses rather
// than invented ones.
import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { Disclosure, collectDisclosure } from "../components/common/Disclosure";

describe("collectDisclosure", () => {
  it("finds warnings, notes and basis labels nested one level down", () => {
    // Shape of a real calculate_uncertainty response.
    const uncertainty = {
      total_uncertainty_pct: 5.66,
      basis: "wind_speed",
      combination: {
        method: "root_sum_square",
        component_correlation: 0,
        note: "Components are combined in quadrature assuming independence.",
      },
      mcp_sampling_cap: {
        cap_applied: true,
        note: "The MCP sampling term is 3/sqrt(concurrent months), capped.",
        warning: "36.0 concurrent months were supplied and 12 were used.",
      },
      energy_sensitivity: { available: false, reason: "No long-term corrected series yet." },
    };

    const items = collectDisclosure(uncertainty);
    const paths = items.map((item) => item.path);

    expect(paths).toContain("mcp_sampling_cap.warning");
    expect(paths).toContain("combination.note");
    expect(paths).toContain("energy_sensitivity.reason");
    expect(paths).toContain("basis");
    // Warnings sort ahead of flags, which sort ahead of notes.
    expect(items[0].kind).toBe("warning");
    expect(items.find((item) => item.path === "mcp_sampling_cap.cap_applied")?.kind).toBe("flag");
  });

  it("reports a flag only when it is true", () => {
    expect(collectDisclosure({ weight_basis_is_mixed: true })).toHaveLength(1);
    expect(collectDisclosure({ weight_basis_is_mixed: false })).toHaveLength(0);
  });

  it("returns nothing for a clean response, a null, or a primitive", () => {
    expect(collectDisclosure({ total_uncertainty_pct: 5.66, p50: 1.0 })).toEqual([]);
    expect(collectDisclosure(null)).toEqual([]);
    expect(collectDisclosure("not an object")).toEqual([]);
    expect(collectDisclosure([1, 2, 3])).toEqual([]);
  });

  it("ignores empty strings so a blank field does not render a bare label", () => {
    expect(collectDisclosure({ warning: "   " })).toEqual([]);
  });

  it("stops recursing past the nesting the responses actually use", () => {
    const deep = { a: { b: { c: { warning: "too deep to matter" } } } };
    expect(collectDisclosure(deep)).toEqual([]);
  });
});

describe("Disclosure", () => {
  it("renders nothing at all when a result carries no caveats", () => {
    const { container } = render(<Disclosure source={{ mean_speed: 7.6 }} />);
    expect(container).toBeEmptyDOMElement();
  });

  it("shows warnings immediately and hides methodology notes behind a toggle", () => {
    // Shape of a real compute_turbulence_analysis response on a low-wind campaign.
    const turbulence = {
      iec_ti_at_15ms: 0.21,
      iec_ti_bin_mps: 10,
      ti_basis: "sigma/U over records above 3 m/s",
      warning: "The campaign never reached 15 m/s, so the nearest available bin is 10 m/s.",
    };

    render(<Disclosure source={turbulence} />);

    // The warning is not behind anything — it changes whether the number may be used.
    expect(screen.getByText(/never reached 15 m\/s/)).toBeInTheDocument();
    expect(screen.queryByText(/sigma\/U over records/)).not.toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: /methodology note/ }));
    expect(screen.getByText(/sigma\/U over records/)).toBeInTheDocument();
  });

  it("counts the items a reader has to act on", () => {
    render(
      <Disclosure
        source={{
          warning: "Fitted to the measured campaign rather than the long-term series.",
          screening_only: true,
          gev: { available: false, reason: "Only 2 annual maxima are available." },
        }}
      />,
    );
    // Two warnings-or-flags; the GEV reason is a note.
    expect(screen.getByLabelText("2 to check")).toBeInTheDocument();
  });
});

describe("withheld GEV fit", () => {
  it("renders the reason instead of crashing when the fit was not performed", () => {
    // Below ten annual maxima the backend omits every GEV field but `available` and
    // `reason`. The panel used to read `gev.wind_50_year` unconditionally, which would
    // have thrown the moment a short campaign was opened.
    const extremes = {
      sample_years: 2,
      screening_only: true,
      series_basis: "measured:Spd_58m",
      gev: {
        available: false,
        reason:
          "A generalised extreme value fit estimates three parameters and only 2 annual " +
          "maxima are available; at least 10 are needed for the fit to be identifiable.",
      },
      gumbel: { location: 35.9, scale: 1.8, wind_50_year: 42.8, wind_100_year: 44.1 },
      warning: "2 annual maxima is a screening basis only, not a design value.",
    };

    render(<Disclosure source={extremes} collapsedByDefault={false} />);

    expect(screen.getByText(/screening basis only/)).toBeInTheDocument();
    expect(screen.getByText(/at least 10 are needed/)).toBeInTheDocument();
    // The withheld fit is disclosed; no number is invented for it.
    expect(screen.queryByText(/wind_50_year/)).not.toBeInTheDocument();
  });
});
