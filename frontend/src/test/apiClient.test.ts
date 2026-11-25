import { describe, expect, it } from "vitest";

import { createApiClient, SESSION_HEADER, type Schemas } from "../api/client";

describe("generated API client", () => {
  it("posts an operation's parameters and reads its typed result", async () => {
    const seen: Request[] = [];
    const result: Schemas["ComputeWeibullParamsResult"] = {
      sensor: "Spd_100m",
      k: 2.1,
      A: 9.0,
      mean_speed: 8.0,
      record_count: 10,
      record_count_total: 12,
      calm_fraction: 0.01,
      fit_excludes_calms: true,
      fit_method: "wasp_m1_m3",
      selection: null,
    };
    const fetchImpl = async (input: RequestInfo | URL, init?: RequestInit) => {
      const request = input instanceof Request ? input : new Request(input, init);
      seen.push(request);
      return new Response(JSON.stringify(result), { status: 200, headers: { "Content-Type": "application/json" } });
    };
    const client = createApiClient("http://localhost", fetchImpl as typeof fetch);

    const { data, error } = await client.POST("/api/sessions/{session_id}/operations/compute_weibull_params", {
      params: { path: { session_id: "abc 1" } },
      body: { sensor_name: "Spd_100m", selection: "north" },
    });

    expect(error).toBeUndefined();
    expect(data?.k).toBe(2.1);
    expect(seen).toHaveLength(1);
    expect(new URL(seen[0].url).pathname).toBe("/api/sessions/abc%201/operations/compute_weibull_params");
    expect(seen[0].headers.get(SESSION_HEADER)).toBe("abc 1");
    expect(await seen[0].json()).toEqual({ sensor_name: "Spd_100m", selection: "north" });
  });

  it("returns a refusal as the typed error detail", async () => {
    const fetchImpl = async () =>
      new Response(JSON.stringify({ detail: "No selection named 'x'" }), {
        status: 400,
        headers: { "Content-Type": "application/json" },
      });
    const client = createApiClient("http://localhost", fetchImpl as typeof fetch);
    const { data, error } = await client.POST("/api/sessions/{session_id}/operations/resolve_selection", {
      params: { path: { session_id: "s" } },
      body: { name: "x" },
    });
    expect(data).toBeUndefined();
    expect(error?.detail).toBe("No selection named 'x'");
  });

  it("leaves a route outside a session without the header", async () => {
    const seen: Request[] = [];
    const fetchImpl = async (input: RequestInfo | URL, init?: RequestInit) => {
      seen.push(input instanceof Request ? input : new Request(input, init));
      return new Response(JSON.stringify([]), { status: 200, headers: { "Content-Type": "application/json" } });
    };
    const client = createApiClient("http://localhost", fetchImpl as typeof fetch);
    await client.GET("/api/operations");
    expect(seen[0].headers.has(SESSION_HEADER)).toBe(false);
  });
});
