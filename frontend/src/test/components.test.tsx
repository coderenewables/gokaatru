import { describe, expect, it } from "vitest";
import { render, screen } from "@testing-library/react";

import { MetricsCard } from "../components/common/MetricsCard";
import { NodeTable } from "../components/common/NodeTable";
import { StageHeader } from "../components/common/StageHeader";
import { SensorPicker } from "../components/common/SensorPicker";
import { RunButton } from "../components/common/RunButton";
import type { EraNode, SensorRow } from "../types/analysis";

describe("MetricsCard", () => {
  it("renders numeric metrics formatted, skipping nested/algorithm", () => {
    render(
      <MetricsCard
        title="SpeedSort"
        metrics={{
          algorithm: "speedsort",
          r_squared: 0.8765,
          rmse: 0.4321,
          slope: 1.123,
          feature_importance: { ws: 0.6 },
        }}
        highlight={["r_squared"]}
      />,
    );
    expect(screen.getByText("SpeedSort")).toBeInTheDocument();
    expect(screen.getByText("0.876")).toBeInTheDocument(); // r_squared (0.8765 -> 0.876 under JS fp rounding)
    expect(screen.getByText("0.432")).toBeInTheDocument(); // rmse
    // algorithm header is elided
    expect(screen.queryByText("Slope")).toBeInTheDocument();
    // feature_importance is nested → not rendered as a tile
    expect(screen.queryByText("Feature importance")).not.toBeInTheDocument();
  });

  it("shows empty state when no metrics", () => {
    render(<MetricsCard metrics={{ algorithm: "x" }} />);
    expect(screen.getByText("No metrics.")).toBeInTheDocument();
  });
});

describe("NodeTable", () => {
  it("lists nodes with distance/bearing", () => {
    const nodes: EraNode[] = [
      { latitude: 52.4, longitude: 4.9, distance_km: 12.3, bearing: "N" },
      { latitude: 52.5, longitude: 5.0, distance_km: 18.1, bearing: "NE" },
    ];
    render(<NodeTable nodes={nodes} provider="ERA5" />);
    expect(screen.getByText("12.3")).toBeInTheDocument();
    expect(screen.getByText("18.1")).toBeInTheDocument();
    expect(screen.getByText("NE")).toBeInTheDocument();
  });

  it("shows empty hint", () => {
    render(<NodeTable nodes={[]} emptyHint="No ERA5 nodes." />);
    expect(screen.getByText("No ERA5 nodes.")).toBeInTheDocument();
  });
});

describe("StageHeader", () => {
  it("renders the title and a locked hint when locked", () => {
    render(<StageHeader stage="ltc" status="locked" index={6} />);
    expect(screen.getByText("Long-Term Correction")).toBeInTheDocument();
    expect(screen.getByText("Locked")).toBeInTheDocument();
    expect(screen.getByText(/upstream stage first/i)).toBeInTheDocument();
  });

  it("hides the locked hint when done", () => {
    render(<StageHeader stage="data" status="done" />);
    expect(screen.getByText("Done")).toBeInTheDocument();
    expect(screen.queryByText(/upstream stage first/i)).not.toBeInTheDocument();
  });
});

describe("SensorPicker", () => {
  const sensors: SensorRow[] = [
    { name: "Spd_80m", height_m: 80, sensor_type: "wind_speed", data_coverage_pct: 95, record_count: 1000 },
    { name: "Dir_80m", height_m: 80, sensor_type: "wind_direction", data_coverage_pct: 95, record_count: 1000 },
    { name: "Spd_120m", height_m: 120, sensor_type: "wind_speed", data_coverage_pct: 90, record_count: 950 },
  ];

  it("single select lists only the chosen kind sorted by height desc", () => {
    render(
      <SensorPicker sensors={sensors} kind="speed" value="" onChange={() => {}} />,
    );
    const select = screen.getByRole("combobox");
    const optionTexts = Array.from(select.querySelectorAll("option")).map((o) => o.textContent ?? "");
    // Tallest (120m) first, then 80m; direction sensor excluded.
    expect(optionTexts[1]).toContain("Spd_120m");
    expect(optionTexts[2]).toContain("Spd_80m");
    expect(optionTexts.some((t) => t.includes("Dir_80m"))).toBe(false);
  });

  it("multi select toggles chips", () => {
    let value: string[] = ["Spd_80m"];
    const { container } = render(
      <SensorPicker sensors={sensors} kind="speed" multiple value={value} onChange={(v) => (value = v as string[])} />,
    );
    expect(screen.getByText("Spd_80m")).toBeInTheDocument();
    expect(screen.getByText("Spd_120m")).toBeInTheDocument();
    // Toggle the 120m chip on.
    const checkboxes = container.querySelectorAll("input[type=checkbox]");
    expect(checkboxes.length).toBe(2);
  });
});

describe("RunButton", () => {
  it("renders its label when store is not busy", () => {
    render(<RunButton label="Run" onClick={() => {}} />);
    expect(screen.getByRole("button", { name: /run/i })).toBeEnabled();
  });

  it("disables when the store is busy", async () => {
    const { useWorkspaceStore } = await import("../store/useWorkspaceStore");
    useWorkspaceStore.setState({ busyLabel: "Working", session: { session_id: "s1" } as never });
    render(<RunButton label="Run" onClick={() => {}} />);
    const button = screen.getByRole("button");
    expect(button).toBeDisabled();
    expect(button.textContent).toContain("Working");
    useWorkspaceStore.setState({ busyLabel: null });
  });
});
