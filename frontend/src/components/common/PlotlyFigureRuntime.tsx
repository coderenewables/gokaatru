import { useCallback, useState } from "react";
import createPlotlyComponent from "react-plotly.js/factory";

import type { PlotResult } from "../../lib/types";
import { Plotly } from "../../lib/plotly";

const Plot = createPlotlyComponent(Plotly);

type PlotlyFigureRuntimeProps = {
  plot: PlotResult;
};

export function PlotlyFigureRuntime({ plot }: PlotlyFigureRuntimeProps) {
  const [expanded, setExpanded] = useState(false);

  const figure = JSON.parse(plot.plotly_json) as {
    data?: unknown[];
    layout?: Record<string, unknown>;
    config?: Record<string, unknown>;
  };

  const open = useCallback(() => setExpanded(true), []);
  const close = useCallback(() => setExpanded(false), []);

  const plotElement = (minHeight: number) => (
    <Plot
      data={(figure.data ?? []) as never[]}
      layout={{ autosize: true, paper_bgcolor: "transparent", plot_bgcolor: "transparent", ...(figure.layout ?? {}) } as never}
      config={{ responsive: true, displaylogo: false, ...(figure.config ?? {}) } as never}
      useResizeHandler
      style={{ width: "100%", height: "100%", minHeight }}
    />
  );

  return (
    <>
      <div className="plot-card">
        <div className="plot-header">
          <strong>{plot.title}</strong>
          <button className="btn-expand-chart" onClick={open} title="Expand chart" aria-label="Expand chart">
            <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
              <polyline points="15 3 21 3 21 9" /><line x1="21" y1="3" x2="14" y2="10" />
              <polyline points="9 21 3 21 3 15" /><line x1="3" y1="21" x2="10" y2="14" />
            </svg>
          </button>
        </div>
        {plotElement(480)}
      </div>

      {expanded && (
        <div className="plot-modal-overlay" onClick={close}>
          <div className="plot-modal" onClick={(e) => e.stopPropagation()}>
            <div className="plot-modal-header">
              <strong>{plot.title}</strong>
              <button className="btn-expand-chart" onClick={close} title="Close" aria-label="Close expanded chart">
                <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                  <line x1="18" y1="6" x2="6" y2="18" /><line x1="6" y1="6" x2="18" y2="18" />
                </svg>
              </button>
            </div>
            <div className="plot-modal-body">
              {plotElement(600)}
            </div>
          </div>
        </div>
      )}
    </>
  );
}