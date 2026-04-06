import { Suspense, lazy, useMemo } from "react";

import type { SiteMapResponse } from "../../lib/types";
import { EmptyState } from "./EmptyState";
import { LoadingState } from "./LoadingState";

const GeoJsonMapRuntime = lazy(async () => ({
  default: (await import("./GeoJsonMapRuntime")).GeoJsonMapRuntime,
}));

type GeoJsonMapProps = {
  featureCollection: SiteMapResponse | null | undefined;
  emptyTitle: string;
  emptyDetail: string;
};

export function GeoJsonMap({ featureCollection, emptyTitle, emptyDetail }: GeoJsonMapProps) {
  const geoJson = useMemo(() => featureCollection ?? null, [featureCollection]);

  if (!geoJson || geoJson.features.length === 0) {
    return <EmptyState title={emptyTitle} detail={emptyDetail} />;
  }

  return (
    <Suspense fallback={<LoadingState label="Loading map" />}>
      <GeoJsonMapRuntime featureCollection={geoJson} />
    </Suspense>
  );
}