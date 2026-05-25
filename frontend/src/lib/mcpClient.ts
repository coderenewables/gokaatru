import { Client } from "@modelcontextprotocol/sdk/client/index.js";
import { SSEClientTransport } from "@modelcontextprotocol/sdk/client/sse.js";
import { StreamableHTTPClientTransport } from "@modelcontextprotocol/sdk/client/streamableHttp.js";

import { getDefaultApiBaseUrl } from "./api";

export interface McpToolSummary {
  name: string;
  description: string;
  inputSchema: Record<string, unknown>;
}

export interface McpResourceSummary {
  uri: string;
  name: string;
  description?: string;
  mimeType?: string;
}

export interface McpCatalog {
  serverName: string;
  serverVersion: string;
  instructions: string;
  tools: McpToolSummary[];
  resources: McpResourceSummary[];
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

export function getDefaultMcpBaseUrl(): string {
  const env = import.meta.env.VITE_MCP_BASE_URL;
  return typeof env === "string" && env.length > 0 ? env : `${getDefaultApiBaseUrl()}/api/mcp/catalog`;
}

function createTransport(url: URL) {
  if (url.pathname.endsWith("/sse")) {
    return new SSEClientTransport(url);
  }
  return new StreamableHTTPClientTransport(url);
}

function isCatalogHttpEndpoint(url: URL): boolean {
  return url.pathname.endsWith("/catalog");
}

function normalizeCatalog(payload: unknown): McpCatalog {
  if (!isRecord(payload)) {
    throw new Error("Invalid MCP catalog response");
  }

  const tools = Array.isArray(payload.tools) ? payload.tools : [];
  const resources = Array.isArray(payload.resources) ? payload.resources : [];

  return {
    serverName: typeof payload.serverName === "string" ? payload.serverName : "GoKaatru MCP",
    serverVersion: typeof payload.serverVersion === "string" ? payload.serverVersion : "unknown",
    instructions: typeof payload.instructions === "string" ? payload.instructions : "",
    tools: tools
      .filter(isRecord)
      .map((tool) => ({
        name: typeof tool.name === "string" ? tool.name : "unknown",
        description: typeof tool.description === "string" ? tool.description : "",
        inputSchema: isRecord(tool.inputSchema) ? tool.inputSchema : {},
      })),
    resources: resources
      .filter(isRecord)
      .map((resource) => ({
        uri: typeof resource.uri === "string" ? resource.uri : "",
        name: typeof resource.name === "string" ? resource.name : typeof resource.uri === "string" ? resource.uri : "resource",
        description: typeof resource.description === "string" ? resource.description : undefined,
        mimeType: typeof resource.mimeType === "string" ? resource.mimeType : undefined,
      })),
  };
}

async function loadCatalogFromApi(baseUrl: string): Promise<McpCatalog> {
  const response = await fetch(baseUrl, {
    headers: { Accept: "application/json" },
  });

  if (!response.ok) {
    throw new Error(`MCP catalog request failed with status ${response.status}`);
  }

  return normalizeCatalog(await response.json());
}

async function loadCatalogFromTransport(baseUrl: string): Promise<McpCatalog> {
  const client = new Client({ name: "GoKaatru Frontend", version: "1.0.0" });
  const transport = createTransport(new URL(baseUrl));

  await client.connect(transport);
  try {
    const [toolsResponse, resourcesResponse] = await Promise.all([
      client.listTools().catch(() => ({ tools: [] })),
      client.listResources().catch(() => ({ resources: [] })),
    ]);
    const serverInfo = client.getServerVersion();
    return {
      serverName: serverInfo?.name ?? "GoKaatru MCP",
      serverVersion: serverInfo?.version ?? "unknown",
      instructions: client.getInstructions() ?? "",
      tools: toolsResponse.tools.map((tool) => ({
        name: tool.name,
        description: tool.description ?? "",
        inputSchema: tool.inputSchema,
      })),
      resources: resourcesResponse.resources.map((resource) => ({
        uri: resource.uri,
        name: resource.name,
        description: resource.description,
        mimeType: resource.mimeType,
      })),
    };
  } finally {
    await transport.close().catch(() => undefined);
  }
}

export async function loadMcpCatalog(baseUrl = getDefaultMcpBaseUrl()): Promise<McpCatalog> {
  const targetUrl = new URL(baseUrl);
  if (isCatalogHttpEndpoint(targetUrl)) {
    return loadCatalogFromApi(targetUrl.toString());
  }

  try {
    return await loadCatalogFromTransport(targetUrl.toString());
  } catch (transportError) {
    const fallbackUrl = `${getDefaultApiBaseUrl()}/api/mcp/catalog`;
    try {
      return await loadCatalogFromApi(fallbackUrl);
    } catch {
      throw transportError;
    }
  }
}
