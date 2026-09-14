import { describe, expect, it, vi, beforeEach, afterEach } from "vitest";
import { fireEvent, render, screen, within } from "@testing-library/react";

// Block real network calls — DataLoadView's panels auto-fetch on mount.
vi.spyOn(globalThis, "fetch").mockResolvedValue(
  new Response(JSON.stringify({ detail: "network disabled in test" }), { status: 500 }),
);

import { useWorkspaceStore } from "../store/useWorkspaceStore";
import { DataModelBuilder } from "../components/stages/DataModelBuilder";
import { DataLoadView } from "../components/stages/DataLoadView";
import type { DataModelDraft } from "../types/analysis";

const DRAFT: DataModelDraft = {
  basis: "header_inference",
  note: "Every reading below is drafted from the column name only.",
  detected_heights_m: [80],
  columns_needing_a_height: ["WindSpeed_60"],
  columns: [
    {
      name: "WS_80m_Avg",
      role: "measurement",
      measurement_type_id: "wind_speed",
      height_m: 80,
      statistic_type_id: null,
      parent: null,
      reason: null,
    },
    {
      name: "WS_80m_SD",
      role: "statistic",
      measurement_type_id: "wind_speed",
      height_m: 80,
      statistic_type_id: "sd",
      parent: "WS_80m_Avg",
      reason: null,
    },
    {
      name: "WindSpeed_60",
      role: "measurement",
      measurement_type_id: "wind_speed",
      height_m: null,
      statistic_type_id: null,
      parent: null,
      reason: "No height token in the header — declare the height in metres.",
    },
    {
      name: "Qual_WS_80m_quality",
      role: "ignored",
      measurement_type_id: null,
      height_m: null,
      statistic_type_id: null,
      parent: null,
      reason: "Header does not read as a wind speed, direction, temperature, pressure or humidity channel.",
    },
  ],
};

/** The editable declaration table, scoped away from the "columns not read" disclosure. */
function sensorRow(name: string | RegExp) {
  const table = screen.getByRole("table", { name: /declared sensors/i });
  return within(table).getByRole("row", { name });
}

const originalActions = {
  loadDataModelDraft: useWorkspaceStore.getState().loadDataModelDraft,
  buildDataModel: useWorkspaceStore.getState().buildDataModel,
};

function seed(overrides: Record<string, unknown> = {}) {
  useWorkspaceStore.setState({
    session: { session_id: "s1", session_id_short: "s1" } as never,
    busyLabel: null,
    sensors: [],
    summary: { completed_steps: ["timeseries"], timeseries_loaded: true } as never,
    dataModelDraft: DRAFT,
    ...overrides,
  } as never);
}

beforeEach(() => {
  seed();
});

afterEach(() => {
  // useWorkspaceStore is a module-level singleton shared across this spec file, so a
  // stubbed action stays stubbed for every later test unless it is put back.
  useWorkspaceStore.setState(originalActions as never);
});

describe("DataModelBuilder — drafting", () => {
  it("lists one editable row per drafted measurement column", () => {
    render(<DataModelBuilder />);

    expect(sensorRow(/WS_80m_Avg/)).toBeTruthy();
    expect(sensorRow(/WindSpeed_60/)).toBeTruthy();
    // A statistic belongs to its parent; it is not a sensor of its own. Asserted on the
    // include checkboxes rather than on row text, because the parent's row legitimately
    // *mentions* WS_80m_SD in its turbulence-column cell.
    const table = screen.getByRole("table", { name: /declared sensors/i });
    const declared = within(table)
      .getAllByRole("checkbox", { name: /^Include / })
      .map((box) => box.getAttribute("aria-label"));
    expect(declared).toEqual(["Include WS_80m_Avg", "Include WindSpeed_60"]);
  });

  it("prefills the inferred type and height without hiding that they were inferred", () => {
    render(<DataModelBuilder />);

    const row = sensorRow(/WS_80m_Avg/);
    expect(within(row).getByRole("combobox", { name: /measurement type/i })).toHaveValue("wind_speed");
    expect(within(row).getByRole("spinbutton", { name: /height/i })).toHaveValue(80);
    expect(screen.getByText(/drafted from the column name only/i)).toBeTruthy();
  });

  it("shows the turbulence column it paired with a speed sensor", () => {
    render(<DataModelBuilder />);

    const row = sensorRow(/WS_80m_Avg/);
    expect(within(row).getByText("WS_80m_SD")).toBeTruthy();
  });

  it("discloses the columns it decided to ignore, with the reason", () => {
    render(<DataModelBuilder />);

    fireEvent.click(screen.getByText(/columns not read as sensors/i));
    expect(screen.getByText(/Qual_WS_80m_quality/)).toBeTruthy();
    expect(screen.getByText(/does not read as a wind speed/i)).toBeTruthy();
  });
});

describe("DataModelBuilder — refusing to guess", () => {
  it("blocks the build while an included column has no height, naming it", () => {
    render(<DataModelBuilder />);

    const build = screen.getByRole("button", { name: /build data model/i });
    expect(build).toBeDisabled();
    // Named in the blocking message, not only in its own row.
    expect(screen.getByText(/Declare a measurement type and height for: WindSpeed_60/)).toBeTruthy();
  });

  it("enables the build once the missing height is declared", () => {
    render(<DataModelBuilder />);

    const row = sensorRow(/WindSpeed_60/);
    fireEvent.change(within(row).getByRole("spinbutton", { name: /height/i }), {
      target: { value: "60" },
    });

    expect(screen.getByRole("button", { name: /build data model/i })).not.toBeDisabled();
  });

  it("also enables the build when the incomplete column is excluded instead", () => {
    render(<DataModelBuilder />);

    const row = sensorRow(/WindSpeed_60/);
    fireEvent.click(within(row).getByRole("checkbox", { name: /include WindSpeed_60/i }));

    expect(screen.getByRole("button", { name: /build data model/i })).not.toBeDisabled();
  });
});

describe("DataModelBuilder — submitting", () => {
  it("sends only included columns, with their statistics and the declared timezone", async () => {
    const buildDataModel = vi.fn().mockResolvedValue(undefined);
    seed({ buildDataModel });
    render(<DataModelBuilder />);

    const incomplete = sensorRow(/WindSpeed_60/);
    fireEvent.click(within(incomplete).getByRole("checkbox", { name: /include WindSpeed_60/i }));
    fireEvent.change(screen.getByRole("spinbutton", { name: /utc offset/i }), {
      target: { value: "5.5" },
    });
    fireEvent.click(screen.getByRole("button", { name: /build data model/i }));

    expect(buildDataModel).toHaveBeenCalledTimes(1);
    const spec = buildDataModel.mock.calls[0][0];
    expect(spec.location.offset_from_utc_hrs).toBe(5.5);
    expect(spec.points).toEqual([
      {
        name: "WS_80m_Avg",
        measurement_type_id: "wind_speed",
        height_m: 80,
        statistics: [{ column_name: "WS_80m_SD", statistic_type_id: "sd" }],
      },
    ]);
  });

  it("carries boom orientation and the primary flag when the analyst sets them", () => {
    const buildDataModel = vi.fn().mockResolvedValue(undefined);
    seed({ buildDataModel });
    render(<DataModelBuilder />);

    const incomplete = sensorRow(/WindSpeed_60/);
    fireEvent.click(within(incomplete).getByRole("checkbox", { name: /include WindSpeed_60/i }));

    const row = sensorRow(/WS_80m_Avg/);
    fireEvent.change(within(row).getByRole("spinbutton", { name: /boom orientation/i }), {
      target: { value: "25" },
    });
    fireEvent.click(within(row).getByRole("checkbox", { name: /primary/i }));
    fireEvent.click(screen.getByRole("button", { name: /build data model/i }));

    const point = buildDataModel.mock.calls[0][0].points[0];
    expect(point.boom_orientation_deg).toBe(25);
    expect(point.is_primary).toBe(true);
  });
});

describe("DataLoadView integration", () => {
  it("offers the builder as a fourth import path", () => {
    render(<DataLoadView />);

    expect(screen.getByRole("tab", { name: /build data model/i })).toBeTruthy();
  });

  it("tells a CSV-only session that no data model is loaded yet", () => {
    // `summary` is the /summary payload (`_get_analysis_summary`), so the flag is
    // `sensor_mapping_loaded` — knowing which of the two summary shapes the store holds
    // is what makes this indicator correct.
    seed({ summary: { completed_steps: ["timeseries"], sensor_mapping_loaded: false } as never });
    render(<DataLoadView />);

    expect(screen.getByText(/Data model not yet loaded/i)).toBeTruthy();
  });
});
