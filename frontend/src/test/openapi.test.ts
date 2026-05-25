import { extractWindKitTools, resolveSchema, type OpenApiSpec } from "../lib/openapi";

const spec: OpenApiSpec = {
  openapi: "3.1.0",
  paths: {
    "/api/windkit/wind/wind_speed": {
      post: {
        summary: "Wind speed",
        requestBody: {
          content: {
            "application/json": {
              schema: { $ref: "#/components/schemas/VectorComponentsRequest" },
            },
          },
        },
      },
    },
    "/api/windkit/topography/add_landcover_table": {
      post: {
        requestBody: {
          content: {
            "application/json": {
              schema: {
                type: "object",
                required: ["geojson_data", "lctable"],
                properties: {
                  geojson_data: { type: "object" },
                  lctable: { type: "object" },
                },
              },
            },
          },
        },
      },
    },
  },
  components: {
    schemas: {
      VectorComponentsRequest: {
        type: "object",
        required: ["u", "v"],
        properties: {
          u: { type: "array", items: { type: "number" } },
          v: { type: "array", items: { type: "number" } },
        },
      },
    },
  },
};

describe("openapi windkit extraction", () => {
  it("resolves refs and extracts windkit tool fields", () => {
    const tools = extractWindKitTools(spec);
    const windTool = tools.find((tool) => tool.path === "/api/windkit/wind/wind_speed");
    const topoTool = tools.find((tool) => tool.path === "/api/windkit/topography/add_landcover_table");

    expect(windTool?.fields.map((field) => field.name)).toEqual(["u", "v"]);
    expect(topoTool?.fields.find((field) => field.name === "geojson_data")?.inputKind).toBe("asset-json");
  });

  it("returns object defaults for missing schemas", () => {
    expect(resolveSchema(spec, undefined).type).toBe("object");
  });
});