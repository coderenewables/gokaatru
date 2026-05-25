import { createAnthropic } from "@ai-sdk/anthropic";
import { createOpenAI } from "@ai-sdk/openai";
import { dynamicTool, stepCountIs, streamText, zodSchema } from "ai";
import { z } from "zod";

import type { AnalysisSummary, HttpMethod, ScenarioSnapshot } from "./api";
import type { NormalizedAsset } from "./normalization";
import type { WindKitToolDefinition } from "./openapi";
import type { WindAnalysisConfig } from "../types/analysis";

export interface CopilotSettings {
  provider: string;
  model: string;
  apiKey: string;
}

export interface CopilotWorkspaceContext {
  summary: AnalysisSummary | null;
  config: WindAnalysisConfig;
  sensors: Array<Record<string, unknown>>;
  assets: NormalizedAsset[];
  scenarios: ScenarioSnapshot[];
  windkitTools: WindKitToolDefinition[];
}

export interface CopilotToolEvent {
  id: string;
  name: string;
  status: "requested" | "completed" | "error";
  input: unknown;
  output?: unknown;
}

export interface CopilotStreamCallbacks {
  onTextDelta: (delta: string) => void;
  onReasoningDelta: (delta: string) => void;
  onToolEvent: (event: CopilotToolEvent) => void;
}

export interface CopilotToolHandlers {
  getWorkspaceContext: () => Promise<unknown>;
  updateRunconfigField: (input: { key: string; value: unknown }) => Promise<unknown>;
  callSessionRoute: (input: { label: string; method: HttpMethod; path: string; body?: unknown }) => Promise<unknown>;
  callWindKitRoute: (input: { routePath: string; payload?: unknown }) => Promise<unknown>;
  listScenarios: () => Promise<unknown>;
}

const providerBaseUrls: Record<string, string> = {
  openrouter: "https://openrouter.ai/api/v1",
  groq: "https://api.groq.com/openai/v1",
  together: "https://api.together.xyz/v1",
};

const defaultModels: Record<string, string> = {
  openai: "gpt-4o",
  openrouter: "openai/gpt-4o",
  groq: "llama-3.3-70b-versatile",
  together: "meta-llama/Meta-Llama-3.1-70B-Instruct-Turbo",
  anthropic: "claude-3-7-sonnet-latest",
};

function asErrorMessage(error: unknown): string {
  if (error instanceof Error) {
    return error.message;
  }
  return String(error);
}

function trimObject<T>(value: T, limit: number): T {
  if (Array.isArray(value)) {
    return value.slice(0, limit) as T;
  }
  return value;
}

function buildWorkspaceSummary(context: CopilotWorkspaceContext): string {
  const sensorNames = context.sensors
    .map((sensor) => String(sensor.name ?? sensor.sensor_name ?? sensor.label ?? ""))
    .filter(Boolean)
    .slice(0, 12);
  const assetSummary = context.assets.slice(0, 12).map((asset) => ({
    id: asset.id,
    label: asset.label,
    format: asset.format,
    compatibility: asset.compatibility,
  }));
  const scenarioSummary = context.scenarios.slice(0, 8).map((scenario) => ({
    name: scenario.name,
    created_at: scenario.created_at,
    results: trimObject(scenario.results, 8),
  }));
  const windkitSummary = context.windkitTools.slice(0, 24).map((tool) => ({
    label: tool.summary,
    routePath: tool.path,
    category: tool.category,
  }));

  return JSON.stringify(
    {
      summary: context.summary,
      config: context.config,
      sensorNames,
      assets: assetSummary,
      scenarios: scenarioSummary,
      windkitTools: windkitSummary,
    },
    null,
    2,
  );
}

function buildSystemPrompt(context: CopilotWorkspaceContext): string {
  return [
    "You are GoKaatru, a wind resource assessment copilot running in the browser with direct BYOK model access.",
    "Use tools when they help inspect session state, mutate runconfig, run workflow operations, fetch WindKit routes, or list saved scenarios.",
    "Always explain what you are doing, mention the tool names you used, and keep the response grounded in the session outputs.",
    "Prefer the targeted helper tools first. Use call_session_route when you need a session API path that is not already covered by a more specific tool.",
    "Available session route patterns include: /summary, /config, /cleaning/apply, /shear/calculate, /shear/table, /extrapolation/hub, /era5/nodes, /era5/extract, /era5/interpolate, /ltc/{algorithm}, /ensemble, /uncertainty, /brighthub/reanalysis/nodes, /brighthub/reanalysis/download, /workflow/execute, /workflow/execute/step.",
    "For WindKit tools, call_windkit_route expects the concrete route path from the current tool catalog.",
    "Current workspace context:",
    buildWorkspaceSummary(context),
  ].join("\n\n");
}

function resolveModel(settings: CopilotSettings) {
  const provider = settings.provider.trim().toLowerCase() || "openai";
  const model = settings.model.trim() || defaultModels[provider] || defaultModels.openai;

  if (provider === "anthropic") {
    return createAnthropic({ apiKey: settings.apiKey })(model);
  }

  if (provider.startsWith("https://")) {
    return createOpenAI({ apiKey: settings.apiKey, baseURL: provider, name: "custom-openai" })(model);
  }

  const baseURL = providerBaseUrls[provider];
  if (baseURL) {
    return createOpenAI({ apiKey: settings.apiKey, baseURL, name: provider })(model);
  }

  return createOpenAI({ apiKey: settings.apiKey })(model);
}

export async function streamCopilotReply(options: {
  prompt: string;
  settings: CopilotSettings;
  context: CopilotWorkspaceContext;
  handlers: CopilotToolHandlers;
  callbacks: CopilotStreamCallbacks;
}): Promise<{ text: string; reasoning: string }> {
  const updateRunconfigSchema = z.object({
    key: z.string().min(1),
    value: z.unknown(),
  });
  const sessionRouteSchema = z.object({
    label: z.string().min(1).default("Session operation"),
    method: z.enum(["GET", "POST", "PUT", "DELETE"]),
    path: z.string().startsWith("/"),
    body: z.unknown().optional(),
  });
  const windkitRouteSchema = z.object({
    routePath: z.string().startsWith("/"),
    payload: z.unknown().optional(),
  });

  const result = streamText({
    model: resolveModel(options.settings),
    system: buildSystemPrompt(options.context),
    prompt: options.prompt,
    stopWhen: stepCountIs(8),
    tools: {
      get_workspace_context: dynamicTool({
        description: "Return the current summary, run configuration, sensor inventory, normalized assets, scenarios, and WindKit tool catalog.",
        inputSchema: zodSchema(z.object({})),
        execute: async () => options.handlers.getWorkspaceContext(),
      }),
      update_runconfig_field: dynamicTool({
        description: "Update one dotted runconfig field on the active session and return the saved response.",
        inputSchema: zodSchema(updateRunconfigSchema),
        execute: async (input) => {
          const payload = input as { key: string; value: unknown };
          return options.handlers.updateRunconfigField(payload);
        },
      }),
      call_session_route: dynamicTool({
        description: "Call a session-scoped API route on the active workspace. Use this for analysis or workflow operations not covered by a dedicated tool.",
        inputSchema: zodSchema(sessionRouteSchema),
        execute: async (input) => options.handlers.callSessionRoute(input as z.infer<typeof sessionRouteSchema>),
      }),
      call_windkit_route: dynamicTool({
        description: "Call a WindKit route using a concrete route path from the current WindKit catalog.",
        inputSchema: zodSchema(windkitRouteSchema),
        execute: async (input) => options.handlers.callWindKitRoute(input as z.infer<typeof windkitRouteSchema>),
      }),
      list_saved_scenarios: dynamicTool({
        description: "Return all saved run-history scenarios for the active session.",
        inputSchema: zodSchema(z.object({})),
        execute: async () => options.handlers.listScenarios(),
      }),
    },
  });

  let text = "";
  let reasoning = "";

  try {
    for await (const part of result.fullStream) {
      switch (part.type) {
        case "text-delta": {
          text += part.text;
          options.callbacks.onTextDelta(part.text);
          break;
        }
        case "reasoning-delta": {
          reasoning += part.text;
          options.callbacks.onReasoningDelta(part.text);
          break;
        }
        case "tool-call": {
          options.callbacks.onToolEvent({
            id: part.toolCallId,
            name: part.toolName,
            status: "requested",
            input: part.input,
          });
          break;
        }
        case "tool-result": {
          options.callbacks.onToolEvent({
            id: part.toolCallId,
            name: part.toolName,
            status: "completed",
            input: part.input,
            output: part.output,
          });
          break;
        }
        case "tool-error": {
          options.callbacks.onToolEvent({
            id: part.toolCallId,
            name: part.toolName,
            status: "error",
            input: part.input,
            output: { error: asErrorMessage(part.error) },
          });
          break;
        }
        default:
          break;
      }
    }
  } catch (error) {
    throw new Error(asErrorMessage(error));
  }

  return {
    text: text || (await result.text),
    reasoning,
  };
}
