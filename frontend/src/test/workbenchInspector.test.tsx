import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { SelectionSection } from "../workbench/inspector/SelectionSection";
import { useSelection } from "../workbench/selection/store";
import { sensorRows, speedChannels } from "../workbench/sensors";

const SELECTION_BASIS = "records outside the selection are treated as missing";

function summary(selection: string) {
  const selected = selection !== "";
  return {
    records: 1000,
    channels: { Spd_100m: { valid: selected ? 240 : 990, mean: selected ? 9.5 : 7.25, min: 0.4, max: 21.0 } },
    selection: selected ? { name: null, inline: true, records: 250, of_records: 1000, basis: SELECTION_BASIS } : null,
  };
}

describe("the inspector's selection section", () => {
  const requests: Array<{ url: string; body: { channels: string; selection: string } }> = [];

  beforeEach(() => {
    requests.length = 0;
    vi.stubGlobal(
      "fetch",
      vi.fn(async (input: Request) => {
        const body = (await input.json()) as { channels: string; selection: string };
        requests.push({ url: input.url, body });
        return new Response(JSON.stringify(summary(body.selection)), {
          status: 200,
          headers: { "Content-Type": "application/json" },
        });
      }),
    );
  });

  afterEach(() => {
    useSelection.getState().clearAll();
    vi.unstubAllGlobals();
  });

  function mount() {
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    return render(
      <QueryClientProvider client={client}>
        <SelectionSection sessionId="s1" channels={["Spd_100m"]} />
      </QueryClientProvider>,
    );
  }

  it("says how to select until a view draws a term", async () => {
    mount();
    expect(screen.getByText(/Select on any chart/)).toBeTruthy();
    await waitFor(() => expect(screen.getByRole("cell", { name: "7.25" })).toBeTruthy());
    expect(requests.every((request) => request.body.selection === "")).toBe(true);
  });

  it("counts the records of the crossfilter, compares the means and clears a term", async () => {
    mount();
    act(() => {
      useSelection.getState().draw("timeline", { kind: "time_range", start: "2023-03-01T00:00:00Z", end: "2023-03-08T00:00:00Z" });
      useSelection.getState().draw("rose", { kind: "sector", channel: "Dir_100m", from_deg: 240, to_deg: 300 });
    });
    await waitFor(() => expect(screen.getByText("250")).toBeTruthy());
    expect(screen.getByText("of 1000 records")).toBeTruthy();
    expect(screen.getByRole("cell", { name: "9.50" })).toBeTruthy();

    const sent = requests.find((request) => request.body.selection !== "");
    expect(sent?.url).toContain("/api/sessions/s1/operations/summarise_channels");
    expect(JSON.parse(sent?.body.selection ?? "")).toEqual({
      kind: "intersection",
      of: [
        { kind: "time_range", start: "2023-03-01T00:00:00Z", end: "2023-03-08T00:00:00Z" },
        { kind: "sector", channel: "Dir_100m", from_deg: 240, to_deg: 300 },
      ],
    });

    expect(screen.getByText("Dir_100m 240° to 300°")).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "Clear the direction term" }));
    expect(useSelection.getState().terms).toEqual({
      timeline: { kind: "time_range", start: "2023-03-01T00:00:00Z", end: "2023-03-08T00:00:00Z" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Clear selection" }));
    expect(useSelection.getState().terms).toEqual({});
  });
});

describe("the sensors route's rows", () => {
  it("are read field by field and give the speeds highest first", () => {
    const rows = sensorRows({
      sensors: [
        { name: "Spd_60m", height_m: 60, sensor_type: "wind_speed" },
        { name: "Dir_100m", height_m: 100, sensor_type: "wind_direction" },
        { name: "Spd_100m", height_m: 100, sensor_type: "wind_speed" },
        { height_m: 80 },
      ],
    });
    expect(rows.map((row) => row.name)).toEqual(["Spd_60m", "Dir_100m", "Spd_100m"]);
    expect(speedChannels(rows)).toEqual(["Spd_100m", "Spd_60m"]);
    expect(sensorRows({ detail: "x" })).toEqual([]);
  });
});
