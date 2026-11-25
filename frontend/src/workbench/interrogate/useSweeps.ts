import { useQuery } from "@tanstack/react-query";
import { useEffect, useLayoutEffect, useState } from "react";

import { api, unwrap } from "../api";
import { useCampaign } from "../shell/context";
import { type SweepRow, useInterrogate } from "./store";

export interface SweepListing {
  sweep_id: string;
  started_at: string | null;
  finished_at: string | null;
  counts: { planned?: number; completed?: number; failed?: number };
  in_progress: boolean;
}

export const sweepsKey = (sessionId: string) => ["sweeps", sessionId] as const;

/** The campaign's persisted sweeps, newest first as the server lists them. */
export function useSweepList() {
  const { sessionId } = useCampaign();
  return useQuery({
    queryKey: sweepsKey(sessionId),
    queryFn: async () => {
      const body = unwrap(await api.GET("/api/sessions/{session_id}/sweep", { params: { path: { session_id: sessionId } } }));
      return (body as unknown as { sweeps: SweepListing[] }).sweeps;
    },
  });
}

/** The open sweep's rows, kept in the store for the panels that read the filtered rows. */
export function useOpenSweep() {
  const { sessionId } = useCampaign();
  const sweepId = useInterrogate((state) => state.sweepId);
  const setRows = useInterrogate((state) => state.setRows);
  const query = useQuery({
    queryKey: ["sweep", sessionId, sweepId],
    enabled: sweepId !== null,
    queryFn: async () => {
      const body = unwrap(
        await api.GET("/api/sessions/{session_id}/sweep/{sweep_id}", {
          params: { path: { session_id: sessionId, sweep_id: sweepId ?? "" } },
        }),
      );
      return (body as unknown as { results: SweepRow[] }).results;
    },
  });
  const rows = query.data;
  useEffect(() => {
    if (rows) setRows(rows);
  }, [rows, setRows]);
  return query;
}

/** The width an element is laid out at, for drawing an SVG at its pixel size. */
export function useWidth<T extends HTMLElement>(fallback = 480) {
  // A callback ref: the chart is not in the tree until a sweep is open, so the element can
  // arrive after the first render.
  const [element, setElement] = useState<T | null>(null);
  const [width, setWidth] = useState(fallback);
  useLayoutEffect(() => {
    if (!element) return;
    const measure = () => setWidth(Math.max(240, Math.floor(element.clientWidth)));
    measure();
    const observer = new ResizeObserver(measure);
    observer.observe(element);
    return () => observer.disconnect();
  }, [element]);
  return [setElement, width] as const;
}
