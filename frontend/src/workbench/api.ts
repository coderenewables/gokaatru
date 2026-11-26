import { createApiClient } from "../api/client";

/** The generated client (decisions/0012) on the same origin; Vite proxies /api in development. */
export const api = createApiClient(window.location.origin, (input, init) => fetch(input, init));

/** The detail of a refused request, as the server worded it. */
export function refusal(error: unknown): string {
  if (error && typeof error === "object" && "detail" in error) {
    const detail = (error as { detail: unknown }).detail;
    if (typeof detail === "string") return detail;
    return JSON.stringify(detail);
  }
  return String(error);
}

/** The data of a generated-client response, or the server's refusal as an Error. */
export function unwrap<T>(response: { data?: T; error?: unknown }): T {
  if (response.error !== undefined || response.data === undefined) {
    throw new Error(refusal(response.error));
  }
  return response.data;
}
