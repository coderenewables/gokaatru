// Centralized plot renderer (spec §2.6 / §10 Phase B).
//
// Fetches a PlotResult from the backend via store.fetchPlot and renders the
// Plotly figure. Falls back to the PNG representation when present and the
// JSON figure can't be parsed, and shows loading/error states.
import { useEffect, useMemo, useState } from "react";
import Plot from "react-plotly.js";

import { useWorkspaceStore } from "../../store/useWorkspaceStore";
import type { PlotName, PlotRequest, PlotResult } from "../../types/analysis";

interface PlotFrameProps {
  plotName: PlotName;
  params: PlotRequest;
  /** Optional fixed result; when provided, no fetch is performed. */
  result?: PlotResult;
  /** Height of the plot container (default 420px). */
  height?: number;
  /** Whether to re-fetch when params change (default true). */
  autoFetch?: boolean;
}

interface ParsedFigure {
  data: unknown[];
  layout: unknown;
}

function parseFigure(plotlyJson: string): ParsedFigure | null {
  try {
    const parsed = JSON.parse(plotlyJson) as unknown;
    if (parsed && typeof parsed === "object" && !Array.isArray(parsed)) {
      const obj = parsed as Record<string, unknown>;
      return {
        data: Array.isArray(obj.data) ? obj.data : [],
        layout: obj.layout ?? {},
      };
    }
  } catch {
    /* fall through */
  }
  return null;
}

export function PlotFrame({ plotName, params, result, height = 420, autoFetch = true }: PlotFrameProps) {
  const fetchPlot = useWorkspaceStore((state) => state.fetchPlot);
  const busyLabel = useWorkspaceStore((state) => state.busyLabel);
  const [data, setData] = useState<PlotResult | null>(result ?? null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (result) {
      setData(result);
      setError(null);
      return;
    }
    if (!autoFetch) return;
    let cancelled = false;
    setError(null);
    fetchPlot(plotName, params)
      .then((value) => {
        if (!cancelled) setData(value);
      })
      .catch((err: unknown) => {
        if (!cancelled) {
          setError(err instanceof Error ? err.message : String(err));
          setData(null);
        }
      });
    return () => {
      cancelled = true;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [plotName, JSON.stringify(params), result, autoFetch]);

  const figure = useMemo(() => (data ? parseFigure(data.plotly_json) : null), [data]);

  const isLoading = !result && !data && !error && Boolean(busyLabel);

  if (error) {
    return (
      <div className="plot-frame plot-error" style={{ minHeight: height }}>
        <p className="plot-error-title">{plotName}</p>
        <p className="plot-error-detail">{error}</p>
        <button
          type="button"
          className="secondary-button"
          onClick={() => void fetchPlot(plotName, params)}
        >
          Retry
        </button>
      </div>
    );
  }

  if (isLoading) {
    return (
      <div className="plot-frame plot-loading" style={{ minHeight: height }}>
        <span className="busy-dot" aria-hidden="true" />
        <span>Rendering {plotName}…</span>
      </div>
    );
  }

  if (!data) {
    return (
      <div className="plot-frame plot-empty" style={{ minHeight: height }}>
        <span>No plot data.</span>
      </div>
    );
  }

  // PNG fallback when the figure JSON can't be parsed.
  if (!figure) {
    if (data.png_base64) {
      return (
        <div className="plot-frame plot-png" style={{ minHeight: height }}>
          <p className="plot-frame-title">{data.title}</p>
          <img
            src={`data:image/png;base64,${data.png_base64}`}
            alt={data.title}
            style={{ maxWidth: "100%" }}
          />
        </div>
      );
    }
    return (
      <div className="plot-frame plot-error" style={{ minHeight: height }}>
        <p className="plot-error-title">{data.title}</p>
        <p className="plot-error-detail">Plotly figure could not be parsed.</p>
      </div>
    );
  }

  return (
    <div className="plot-frame" style={{ minHeight: height }}>
      <Plot
        data={figure.data}
        layout={{ autosize: true, title: data.title, ...(figure.layout as object) }}
        config={{ displaylogo: false, responsive: true }}
        style={{ width: "100%", height: `${height}px` }}
        useResizeHandler
      />
    </div>
  );
}
