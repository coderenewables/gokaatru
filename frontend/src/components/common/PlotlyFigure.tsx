import Plot from "react-plotly.js";

import type { PlotResult } from "../../lib/types";
import { EmptyState } from "./EmptyState";

type PlotlyFigureProps = {
  plot: PlotResult | null | undefined;
  emptyTitle: string;
  emptyDetail: string;
};

export function PlotlyFigure({ plot, emptyTitle, emptyDetail }: PlotlyFigureProps) {
  if (!plot) {
    return <EmptyState title={emptyTitle} detail={emptyDetail} />;
  }

  const figure = JSON.parse(plot.plotly_json) as {
    data?: unknown[];
    layout?: Record<string, unknown>;
    config?: Record<string, unknown>;
  };

  return (
    <div className="plot-card">
      <div className="plot-header">
        <strong>{plot.title}</strong>
      </div>
      <Plot
        data={(figure.data ?? []) as never[]}
        layout={{ autosize: true, paper_bgcolor: "transparent", plot_bgcolor: "transparent", ...(figure.layout ?? {}) } as never}
        config={{ responsive: true, displaylogo: false, ...(figure.config ?? {}) } as never}
        useResizeHandler
        style={{ width: "100%", height: "100%", minHeight: 360 }}
      />
    </div>
  );
}