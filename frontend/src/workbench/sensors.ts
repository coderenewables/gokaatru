import { useQuery } from "@tanstack/react-query";

import { api, unwrap } from "./api";

export interface SensorRow {
  name: string;
  height_m: number | null;
  sensor_type: string;
}

/** The rows of GET /sessions/{id}/sensors, a hand-written route whose response is untyped in
 * the schema, checked field by field. An empty session answers an empty list (P1-18). */
export function sensorRows(data: unknown): SensorRow[] {
  const rows = data && typeof data === "object" ? (data as { sensors?: unknown }).sensors : undefined;
  if (!Array.isArray(rows)) return [];
  return rows.flatMap((row) => {
    if (!row || typeof row !== "object") return [];
    const { name, height_m: height, sensor_type: type } = row as Record<string, unknown>;
    if (typeof name !== "string") return [];
    return [{ name, height_m: typeof height === "number" ? height : null, sensor_type: typeof type === "string" ? type : "" }];
  });
}

export function useSensors(sessionId: string) {
  return useQuery({
    queryKey: ["sensors", sessionId],
    queryFn: async () =>
      sensorRows(unwrap(await api.GET("/api/sessions/{session_id}/sensors", { params: { path: { session_id: sessionId } } }))),
  });
}

/** The wind speed channels, highest first, as the inspector compares them. */
export function speedChannels(rows: SensorRow[]): string[] {
  return rows
    .filter((row) => row.sensor_type === "wind_speed")
    .sort((a, b) => (b.height_m ?? -Infinity) - (a.height_m ?? -Infinity))
    .map((row) => row.name);
}
