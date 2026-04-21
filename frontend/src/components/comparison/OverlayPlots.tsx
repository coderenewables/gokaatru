import { PlotlyFigure } from "../common/PlotlyFigure";

import type { WorkflowComparePlots } from "../../lib/types";

type OverlayPlotsProps = {
  plots: WorkflowComparePlots;
};

export function OverlayPlots({ plots }: OverlayPlotsProps) {
  return (
    <div className="workflow-compare-plot-grid">
      <article className="workflow-compare-plot-card">
        <h3>Weibull Overlay</h3>
        <PlotlyFigure plot={plots.weibull} emptyTitle="No Weibull comparison" emptyDetail="Run comparison after branch execution." />
      </article>

      <article className="workflow-compare-plot-card">
        <h3>LTC Scatter Overlay</h3>
        <PlotlyFigure plot={plots.ltc_scatter} emptyTitle="No LTC scatter comparison" emptyDetail="Run LTC in compared branches first." />
      </article>

      <article className="workflow-compare-plot-card">
        <h3>Uncertainty Tornado</h3>
        <PlotlyFigure
          plot={plots.uncertainty_tornado}
          emptyTitle="No uncertainty comparison"
          emptyDetail="Calculate uncertainty in compared branches first."
        />
      </article>

      <article className="workflow-compare-plot-card">
        <h3>Windrose Plots</h3>
        <div className="workflow-compare-windrose-stack">
          {plots.windrose.length === 0 ? <p className="muted-text">No windrose plots available.</p> : null}
          {plots.windrose.map((plot, index) => (
            <PlotlyFigure
              key={`windrose-${index + 1}`}
              plot={plot}
              emptyTitle="No windrose data"
              emptyDetail="Direction and speed data is required."
            />
          ))}
        </div>
      </article>
    </div>
  );
}
