import type { QueryClient } from "@tanstack/react-query";

/** After a change to a campaign's data every view of it reads again: each query key of a
 * campaign holds its session id. */
export function invalidateCampaign(client: QueryClient, sessionId: string): Promise<void> {
  return client.invalidateQueries({ predicate: (query) => query.queryKey.includes(sessionId) });
}
