// WindKit tool extraction from the backend OpenAPI spec (spec §2.1 / Phase G).
//
// The backend exposes ~95 POST endpoints under /api/windkit/{category}/{function}.
// This module parses the OpenAPI document and yields a categorized tool list for
// the WindKit explorer UI.
export interface WindKitToolDefinition {
  path: string;
  category: string;
  name: string;
  method: string;
  summary: string;
}

const WINDKIT_PREFIX = "/api/windkit/";

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

export function extractWindKitTools(spec: unknown): WindKitToolDefinition[] {
  if (!isRecord(spec) || !isRecord(spec.paths)) return [];
  const tools: WindKitToolDefinition[] = [];
  for (const [path, pathItem] of Object.entries(spec.paths)) {
    if (!path.startsWith(WINDKIT_PREFIX)) continue;
    if (!isRecord(pathItem)) continue;
    const relativePath = path.slice(WINDKIT_PREFIX.length);
    const [category, name] = relativePath.split("/");
    if (!category || !name) continue;
    // Prefer POST (WindKit routes are all POST), fall back to first method.
    const post = isRecord(pathItem.post) ? pathItem.post : null;
    const method = post ? "POST" : Object.keys(pathItem)[0]?.toUpperCase() ?? "POST";
    const summary =
      (post && typeof post.summary === "string" && post.summary) ||
      (isRecord(pathItem.get) && typeof pathItem.get.summary === "string" && pathItem.get.summary) ||
      "";
    tools.push({ path, category, name, method, summary });
  }
  return tools.sort((a, b) =>
    a.category === b.category ? a.name.localeCompare(b.name) : a.category.localeCompare(b.category),
  );
}

export function groupWindKitToolsByCategory(
  tools: WindKitToolDefinition[],
): Record<string, WindKitToolDefinition[]> {
  const grouped: Record<string, WindKitToolDefinition[]> = {};
  for (const tool of tools) {
    (grouped[tool.category] ??= []).push(tool);
  }
  return grouped;
}
