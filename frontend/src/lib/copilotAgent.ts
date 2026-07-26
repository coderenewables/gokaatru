// BYOK copilot agent (spec §6).
//
// The backend POST /api/sessions/{id}/chat endpoint is OpenAI-compatible and
// runs server-side tool execution against the MCP tool registry (up to 12
// rounds). This module wraps it as a streaming-style call: it feeds the user
// prompt + a workspace-context system message, invokes chatSession, and emits
// the final reply + executed tool calls via callbacks.
//
// For providers where the backend's {provider,model} mapping isn't desired,
// callers can pass a custom baseUrl/model — but the default path uses the
// backend proxy so API keys never reach an unintended third party.
import { chatSession, type ChatMessage } from "./api";
import type { AnalysisSummary, WindAnalysisConfig, SensorRow, ScenarioSnapshot } from "../types/analysis";

export interface CopilotSettings {
  provider: string;
  model: string;
  apiKey: string;
}

export interface CopilotMessage {
  id: string;
  role: "user" | "assistant";
  content: string;
  status: "streaming" | "complete" | "error";
  toolCalls: CopilotToolEvent[];
}

const CHAT_SETTINGS_KEY = "gokaatru-chat-settings";

export function readChatSettings(): CopilotSettings {
  if (typeof window === "undefined") return { provider: "openai", model: "gpt-4o", apiKey: "" };
  try {
    const raw = window.localStorage.getItem(CHAT_SETTINGS_KEY);
    if (!raw) return { provider: "openai", model: "gpt-4o", apiKey: "" };
    const parsed = JSON.parse(raw) as Partial<CopilotSettings>;
    return {
      provider: typeof parsed.provider === "string" ? parsed.provider : "openai",
      model: typeof parsed.model === "string" ? parsed.model : "gpt-4o",
      apiKey: typeof parsed.apiKey === "string" ? parsed.apiKey : "",
    };
  } catch {
    return { provider: "openai", model: "gpt-4o", apiKey: "" };
  }
}

export function writeChatSettings(settings: CopilotSettings): void {
  if (typeof window === "undefined") return;
  window.localStorage.setItem(CHAT_SETTINGS_KEY, JSON.stringify(settings));
}

export function defaultModelForProvider(provider: string): string {
  switch (provider) {
    case "anthropic":
      return "claude-3-5-sonnet-latest";
    case "openrouter":
      return "openai/gpt-4o";
    case "groq":
      return "llama-3.3-70b-versatile";
    case "together":
      return "meta-llama/Meta-Llama-3.1-70B-Instruct-Turbo";
    case "openai":
    default:
      return "gpt-4o";
  }
}

export interface CopilotWorkspaceContext {
  summary: AnalysisSummary | null;
  config: WindAnalysisConfig;
  sensors: SensorRow[];
  scenarios: ScenarioSnapshot[];
}

export interface CopilotToolEvent {
  id: string;
  toolName: string;
  arguments: Record<string, unknown>;
  status: "running" | "complete" | "error";
  result?: unknown;
  error?: string;
}

export interface CopilotHandlers {
  onUpdateRunconfigField?: (payload: { key: string; value: unknown }) => Promise<unknown>;
  onCallSessionRoute?: (payload: { label: string; method: string; path: string; body?: unknown }) => Promise<unknown>;
}

export interface CopilotCallbacks {
  onTextDelta?: (delta: string) => void;
  onToolEvent?: (event: CopilotToolEvent) => void;
}

export interface CopilotResponse {
  text: string;
  toolCalls: CopilotToolEvent[];
}

const SYSTEM_PROMPT = `You are the GoKaatru wind-resource-assessment copilot. You help the analyst:
- inspect loaded data, sensors, and analysis progress;
- run workflow operations (cleaning, shear, extrapolation, ERA5, LTC, ensemble, uncertainty);
- interpret results and recommend next steps.

The backend executes tools server-side; you decide which tool to call and explain the outcome.
Be concise. Prefer tables or short lists over prose. When the analyst asks to change a setting,
call updateRunconfigField. When they ask to run an operation, call callSessionRoute.`;

function describeContext(ctx: CopilotWorkspaceContext): string {
  const parts: string[] = [];
  if (ctx.summary) {
    const s = ctx.summary;
    parts.push(
      `Progress: ${(s.completed_steps ?? []).join(", ") || "none"}. Hub height: ${s.hub_height_m ?? "?"}m. ` +
        `Sensors: ${s.sensor_count ?? 0}. LTC algorithms run: ${(s.ltc_algorithms_run ?? []).join(", ") || "none"}. ` +
        `Ensemble ready: ${s.ensemble_ready ?? false}.`,
    );
  }
  if (ctx.sensors.length > 0) {
    parts.push(
      `Speed sensors: ${ctx.sensors
        .filter((sn) => sn.sensor_type === "wind_speed")
        .map((sn) => `${sn.name}(${sn.height_m}m,${sn.data_coverage_pct.toFixed(0)}%)`)
        .join(", ")}.`,
    );
  }
  if (ctx.scenarios.length > 0) {
    parts.push(`Saved scenarios: ${ctx.scenarios.map((sc) => sc.name).join(", ")}.`);
  }
  return parts.join(" ");
}

export async function streamCopilotReply(args: {
  prompt: string;
  settings: CopilotSettings;
  sessionId: string;
  apiBaseUrl: string;
  context: CopilotWorkspaceContext;
  handlers: CopilotHandlers;
  callbacks: CopilotCallbacks;
  history?: ChatMessage[];
}): Promise<CopilotResponse> {
  const { prompt, settings, sessionId, apiBaseUrl, context, handlers, callbacks, history = [] } = args;

  const messages: ChatMessage[] = [
    { role: "system", content: `${SYSTEM_PROMPT}\n\nWorkspace context: ${describeContext(context)}` },
    ...history,
    { role: "user", content: prompt },
  ];

  // Pre-scan the prompt for simple config mutations the analyst may phrase
  // imperatively ("set hub height to 140"). These are handled locally via the
  // updateRunconfigField handler; everything else is deferred to the backend.
  const toolCalls: CopilotToolEvent[] = [];
  const localMutation = matchLocalMutation(prompt);
  let text = "";

  if (localMutation && handlers.onUpdateRunconfigField) {
    const evt: CopilotToolEvent = {
      id: `tc-${Date.now()}`,
      toolName: "updateRunconfigField",
      arguments: localMutation,
      status: "running",
    };
    callbacks.onToolEvent?.(evt);
    try {
      await handlers.onUpdateRunconfigField(localMutation);
      evt.status = "complete";
      callbacks.onToolEvent?.({ ...evt });
      toolCalls.push(evt);
      text = `Updated ${localMutation.key} to ${JSON.stringify(localMutation.value)}.`;
      callbacks.onTextDelta?.(text);
      return { text, toolCalls };
    } catch (err) {
      evt.status = "error";
      evt.error = err instanceof Error ? err.message : String(err);
      callbacks.onToolEvent?.({ ...evt });
      toolCalls.push(evt);
    }
  }

  // Defer to the backend chat proxy for everything else.
  try {
    const response = await chatSession(apiBaseUrl, sessionId, {
      api_key: settings.apiKey,
      provider: settings.provider,
      model: settings.model,
      messages,
    });
    text = response.reply || "(no reply)";
    callbacks.onTextDelta?.(text);
    for (const tc of response.tool_calls_executed ?? []) {
      const evt: CopilotToolEvent = {
        id: `tc-${tc.tool_name}-${Date.now()}-${Math.random().toString(36).slice(2, 6)}`,
        toolName: tc.tool_name,
        arguments: tc.arguments,
        status: "complete",
        result: tc.result,
      };
      callbacks.onToolEvent?.(evt);
      toolCalls.push(evt);
    }
  } catch (err) {
    text = err instanceof Error ? `Chat failed: ${err.message}` : "Chat failed.";
    callbacks.onTextDelta?.(text);
  }

  return { text, toolCalls };
}

// ---------------------------------------------------------------------------
// Local config-mutation detection (best-effort, keeps simple asks client-side)
// ---------------------------------------------------------------------------

function matchLocalMutation(
  prompt: string,
): { key: string; value: unknown } | null {
  const lower = prompt.toLowerCase();

  // "set hub height to 140" / "hub height = 140m"
  const hubMatch = lower.match(/hub\s*height\s*(?:to|=|:)\s*(\d+(?:\.\d+)?)/);
  if (hubMatch) {
    return { key: "site.hubHeightM", value: Number(hubMatch[1]) };
  }

  // "rename project to X" / "project name = X"
  const renameMatch = prompt.match(/(?:rename|set)\s+project\s+(?:name\s+)?(?:to|=)\s*["']?([^"'\n]+?)["']?$/i);
  if (renameMatch) {
    return { key: "project.name", value: renameMatch[1].trim() };
  }

  return null;
}
