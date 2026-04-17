import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { analysisApi, healthApi, uploadsApi, workflowApi } from "./api";

describe("api client", () => {
  const fetchMock = vi.fn<typeof fetch>();

  beforeEach(() => {
    vi.stubGlobal("fetch", fetchMock);
  });

  afterEach(() => {
    fetchMock.mockReset();
  });

  it("requests API health without a session header", async () => {
    fetchMock.mockResolvedValue(
      new Response(JSON.stringify({ status: "ok", service: "gokaatru-api" }), {
        status: 200,
        headers: { "Content-Type": "application/json" },
      }),
    );

    const result = await healthApi.get();

    expect(result.service).toBe("gokaatru-api");
    expect(fetchMock).toHaveBeenCalledWith(
      "/api/health",
      expect.objectContaining({
        headers: expect.any(Headers),
      }),
    );

    const headers = fetchMock.mock.calls[0]?.[1]?.headers as Headers;
    expect(headers.get("X-GoKaatru-Session")).toBeNull();
    expect(headers.get("Content-Type")).toBe("application/json");
  });

  it("sends cleaning requests with session header and JSON body", async () => {
    fetchMock.mockResolvedValue(
      new Response(JSON.stringify({ status: "ok", rule: "range_check", sensor: "Wind_80m", records_affected: 12 }), {
        status: 200,
        headers: { "Content-Type": "application/json" },
      }),
    );

    await analysisApi.applyCleaning("session-123", {
      rule_type: "range_check",
      sensor: "Wind_80m",
      params: { min: 0, max: 50 },
      start_date: "2024-01-01",
      end_date: "2024-01-31",
    });

    expect(fetchMock).toHaveBeenCalledWith(
      "/api/sessions/session-123/cleaning/apply",
      expect.objectContaining({
        method: "POST",
        body: JSON.stringify({
          rule_type: "range_check",
          sensor: "Wind_80m",
          params: { min: 0, max: 50 },
          start_date: "2024-01-01",
          end_date: "2024-01-31",
        }),
      }),
    );

    const headers = fetchMock.mock.calls[0]?.[1]?.headers as Headers;
    expect(headers.get("X-GoKaatru-Session")).toBe("session-123");
    expect(headers.get("Content-Type")).toBe("application/json");
  });

  it("uploads timeseries files with form data", async () => {
    fetchMock.mockResolvedValue(
      new Response(JSON.stringify({ status: "ok", file_path: "data/uploads/timeseries.csv" }), {
        status: 200,
        headers: { "Content-Type": "application/json" },
      }),
    );

    const file = new File(["speed\n8.1"], "timeseries.csv", { type: "text/csv" });
    await uploadsApi.uploadTimeseries("session-456", file, file.name);

    expect(fetchMock).toHaveBeenCalledWith(
      "/api/sessions/session-456/uploads/timeseries",
      expect.objectContaining({
        method: "POST",
        body: expect.any(FormData),
      }),
    );

    const headers = fetchMock.mock.calls[0]?.[1]?.headers as Headers;
    expect(headers.get("X-GoKaatru-Session")).toBe("session-456");
    expect(headers.get("Content-Type")).toBeNull();
  });

  it("requests workflow capabilities with session header", async () => {
    fetchMock.mockResolvedValue(
      new Response(JSON.stringify({ capabilities: [] }), {
        status: 200,
        headers: { "Content-Type": "application/json" },
      }),
    );

    await workflowApi.getCapabilities("session-cap");

    expect(fetchMock).toHaveBeenCalledWith(
      "/api/sessions/session-cap/workflow/capabilities",
      expect.objectContaining({
        headers: expect.any(Headers),
      }),
    );

    const headers = fetchMock.mock.calls[0]?.[1]?.headers as Headers;
    expect(headers.get("X-GoKaatru-Session")).toBe("session-cap");
    expect(headers.get("Content-Type")).toBe("application/json");
  });
});