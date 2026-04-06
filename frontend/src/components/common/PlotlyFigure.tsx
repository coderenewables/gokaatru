import { Suspense, lazy } from "react";

import type { PlotResult } from "../../lib/types";
import { EmptyState } from "./EmptyState";
import { LoadingState } from "./LoadingState";

const PlotlyFigureRuntime = lazy(async () => ({
  default: (await import("./PlotlyFigureRuntime")).PlotlyFigureRuntime,
}));

type PlotlyFigureProps = {
  plot: PlotResult | null | undefined;
  emptyTitle: string;
  emptyDetail: string;
};

export function PlotlyFigure({ plot, emptyTitle, emptyDetail }: PlotlyFigureProps) {
  if (!plot) {
    return <EmptyState title={emptyTitle} detail={emptyDetail} />;
  }

  return (
    <Suspense fallback={<LoadingState label="Loading chart" />}>
      <PlotlyFigureRuntime plot={plot} />
    </Suspense>
  );
}