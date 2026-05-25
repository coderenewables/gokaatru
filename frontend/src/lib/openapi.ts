export interface OpenApiSchema {
  $ref?: string;
  type?: string;
  title?: string;
  description?: string;
  format?: string;
  enum?: Array<string | number | boolean>;
  required?: string[];
  properties?: Record<string, OpenApiSchema>;
  items?: OpenApiSchema;
  anyOf?: OpenApiSchema[];
  oneOf?: OpenApiSchema[];
  allOf?: OpenApiSchema[];
  nullable?: boolean;
  additionalProperties?: boolean | OpenApiSchema;
  default?: unknown;
}

export interface OpenApiOperation {
  summary?: string;
  description?: string;
  requestBody?: {
    content?: {
      "application/json"?: {
        schema?: OpenApiSchema;
      };
    };
  };
}

export interface OpenApiSpec {
  openapi?: string;
  paths: Record<string, Record<string, OpenApiOperation>>;
  components?: {
    schemas?: Record<string, OpenApiSchema>;
  };
}

export interface WindKitToolField {
  name: string;
  label: string;
  required: boolean;
  schema: OpenApiSchema;
  inputKind: "text" | "number" | "boolean" | "enum" | "json" | "asset-json";
}

export interface WindKitToolDefinition {
  id: string;
  path: string;
  category: string;
  summary: string;
  description: string;
  requestSchema: OpenApiSchema;
  fields: WindKitToolField[];
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function labelize(name: string): string {
  return name
    .replace(/_/g, " ")
    .replace(/\b\w/g, (match) => match.toUpperCase());
}

function mergeSchemas(base: OpenApiSchema, override: OpenApiSchema): OpenApiSchema {
  return {
    ...base,
    ...override,
    properties: {
      ...(base.properties ?? {}),
      ...(override.properties ?? {}),
    },
    required: [...new Set([...(base.required ?? []), ...(override.required ?? [])])],
  };
}

export function resolveSchema(spec: OpenApiSpec, schema: OpenApiSchema | undefined): OpenApiSchema {
  if (!schema) {
    return { type: "object", properties: {} };
  }
  if (schema.$ref) {
    const refName = schema.$ref.split("/").pop() ?? "";
    return resolveSchema(spec, spec.components?.schemas?.[refName]);
  }
  if (schema.allOf && schema.allOf.length > 0) {
    return schema.allOf.reduce((accumulator, item) => mergeSchemas(accumulator, resolveSchema(spec, item)), {
      type: "object",
      properties: {},
      required: [],
    });
  }
  if (schema.oneOf && schema.oneOf.length > 0) {
    return resolveSchema(spec, schema.oneOf.find((item) => item.type !== "null") ?? schema.oneOf[0]);
  }
  if (schema.anyOf && schema.anyOf.length > 0) {
    return resolveSchema(spec, schema.anyOf.find((item) => item.type !== "null") ?? schema.anyOf[0]);
  }
  return {
    ...schema,
    properties: Object.fromEntries(
      Object.entries(schema.properties ?? {}).map(([key, value]) => [key, resolveSchema(spec, value)]),
    ),
    items: schema.items ? resolveSchema(spec, schema.items) : undefined,
  };
}

function inferFieldKind(fieldName: string, schema: OpenApiSchema): WindKitToolField["inputKind"] {
  const lower = fieldName.toLowerCase();
  if (Array.isArray(schema.enum) && schema.enum.length > 0) {
    return "enum";
  }
  if (schema.type === "boolean") {
    return "boolean";
  }
  if (schema.type === "number" || schema.type === "integer") {
    return "number";
  }
  if (
    lower.includes("dataset")
    || lower.includes("geojson")
    || lower === "data"
    || lower.endsWith("_data")
    || lower.includes("wind_speed_data")
    || lower.includes("wind_direction_data")
  ) {
    return "asset-json";
  }
  if (schema.type === "object" || schema.type === "array") {
    return "json";
  }
  return "text";
}

export function buildToolFields(spec: OpenApiSpec, schema: OpenApiSchema): WindKitToolField[] {
  const resolved = resolveSchema(spec, schema);
  if (!isRecord(resolved.properties)) {
    return [];
  }
  const required = new Set(resolved.required ?? []);
  return Object.entries(resolved.properties).map(([name, property]) => ({
    name,
    label: labelize(name),
    required: required.has(name),
    schema: property,
    inputKind: inferFieldKind(name, property),
  }));
}

export function extractWindKitTools(spec: OpenApiSpec): WindKitToolDefinition[] {
  const tools: WindKitToolDefinition[] = [];

  for (const [path, methods] of Object.entries(spec.paths ?? {})) {
    if (!path.startsWith("/api/windkit/")) {
      continue;
    }
    const operation = methods.post;
    if (!operation) {
      continue;
    }
    const requestSchema = resolveSchema(spec, operation.requestBody?.content?.["application/json"]?.schema);
    const category = path.replace("/api/windkit/", "").split("/")[0] ?? "windkit";
    tools.push({
      id: path,
      path,
      category,
      summary: operation.summary ?? labelize(path.split("/").slice(-1)[0] ?? path),
      description: operation.description ?? "",
      requestSchema,
      fields: buildToolFields(spec, requestSchema),
    });
  }

  return tools.sort((a, b) => a.path.localeCompare(b.path));
}