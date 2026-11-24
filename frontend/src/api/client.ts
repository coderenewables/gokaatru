// The API client generated from the server's OpenAPI schema (decisions/0012, P1-20).
//
// `schema.d.ts` is generated from `openapi.json` by `npm run generate:api`; neither is edited
// by hand. Every request and response is typed from the server's own models, including each
// operation's result (`server/schemas/results`). A float in a result may be null: the server
// sends NaN and infinity as null.
import createClient, { type Client, type Middleware } from "openapi-fetch";

import type { components, paths } from "./schema";

export type { components, paths };
export type Schemas = components["schemas"];

export const SESSION_HEADER = "X-GoKaatru-Session";
const SESSION_PATH = /\/api\/sessions\/([^/]+)/;

// Every session route requires the session header; it is the id already in the path.
const sessionHeader: Middleware = {
  onRequest({ request }) {
    const match = new URL(request.url).pathname.match(SESSION_PATH);
    if (match && !request.headers.has(SESSION_HEADER)) {
      request.headers.set(SESSION_HEADER, decodeURIComponent(match[1]));
    }
    return request;
  },
};

export function createApiClient(baseUrl = "", fetchImpl?: typeof fetch): Client<paths> {
  const client = createClient<paths>({ baseUrl, ...(fetchImpl ? { fetch: fetchImpl } : {}) });
  client.use(sessionHeader);
  return client;
}
