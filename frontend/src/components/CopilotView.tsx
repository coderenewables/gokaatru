import { useEffect, useState } from "react";

import { loadMcpCatalog, type McpCatalog } from "../lib/mcpClient";
import { useWorkspaceStore } from "../store/useWorkspaceStore";

const promptSuggestions = [
  "Summarize the current analysis readiness and missing workflow steps.",
  "Which sensors should I use for a first-pass shear calculation at 120m?",
  "Suggest a clean LTC run order using the current config and available reanalysis data.",
] as const;

export function CopilotView() {
  const chatSettings = useWorkspaceStore((state) => state.chatSettings);
  const setChatSettings = useWorkspaceStore((state) => state.setChatSettings);
  const chatMessages = useWorkspaceStore((state) => state.chatMessages);
  const sendChatMessage = useWorkspaceStore((state) => state.sendChatMessage);
  const summary = useWorkspaceStore((state) => state.summary);
  const assets = useWorkspaceStore((state) => state.assets);

  const [provider, setProvider] = useState(chatSettings.provider);
  const [model, setModel] = useState(chatSettings.model);
  const [apiKey, setApiKey] = useState(chatSettings.apiKey);
  const [draft, setDraft] = useState("");
  const [mcpCatalog, setMcpCatalog] = useState<McpCatalog | null>(null);
  const [mcpStatus, setMcpStatus] = useState<"loading" | "ready" | "error">("loading");
  const [mcpError, setMcpError] = useState("");

  useEffect(() => {
    let active = true;

    setMcpStatus("loading");
    void loadMcpCatalog()
      .then((catalog) => {
        if (!active) {
          return;
        }
        setMcpCatalog(catalog);
        setMcpStatus("ready");
        setMcpError("");
      })
      .catch((error) => {
        if (!active) {
          return;
        }
        setMcpCatalog(null);
        setMcpStatus("error");
        setMcpError(error instanceof Error ? error.message : String(error));
      });

    return () => {
      active = false;
    };
  }, []);

  return (
    <div className="copilot-layout">
      <section className="panel">
        <div className="panel-header">
          <div>
            <p className="panel-kicker">Phase 3</p>
            <h2>BYOK settings</h2>
          </div>
        </div>
        <div className="form-grid">
          <label>
            <span>Provider</span>
            <input onChange={(event) => setProvider(event.target.value)} placeholder="openai, anthropic, openrouter, groq, together, or https://..." type="text" value={provider} />
          </label>
          <label>
            <span>Model</span>
            <input onChange={(event) => setModel(event.target.value)} type="text" value={model} />
          </label>
          <label className="field-span-2">
            <span>API key</span>
            <input onChange={(event) => setApiKey(event.target.value)} type="password" value={apiKey} />
          </label>
        </div>
        <button className="primary-button" onClick={() => setChatSettings({ provider, model, apiKey })} type="button">
          Save local settings
        </button>
        <p className="muted-text">
          Keys are stored in browser local storage only and sent directly from the browser to the selected LLM provider during streaming copilot runs.
        </p>
      </section>

      <section className="panel copilot-thread-panel">
        <div className="panel-header">
          <div>
            <p className="panel-kicker">Chat</p>
            <h2>Config-aware analysis assistant</h2>
          </div>
        </div>
        <div className="chat-thread">
          {chatMessages.length === 0 ? <p className="muted-text">Ask the copilot to inspect the runconfig, execute tools, or explain analysis deltas.</p> : null}
          {chatMessages.map((message) => (
            <article className={`chat-bubble chat-bubble-${message.role}`} key={message.id}>
              <div className="button-row">
                <strong>{message.role === "user" ? "You" : "GoKaatru"}</strong>
                {message.role === "assistant" ? (
                  <span className={`status-pill ${message.status === "streaming" ? "status-pill-busy" : ""}`}>
                    {message.status === "streaming" ? "Streaming" : message.status === "error" ? "Error" : "Complete"}
                  </span>
                ) : null}
              </div>
              <p>{message.content || (message.status === "streaming" ? "Working through the next tool step..." : "")}</p>
              {message.toolCalls.length > 0 ? (
                <div className="selection-list">
                  {message.toolCalls.map((toolCall) => (
                    <article className="asset-card" key={toolCall.id}>
                      <div className="asset-card-header">
                        <h3>{toolCall.name}</h3>
                        <span className={`status-pill ${toolCall.status === "requested" ? "status-pill-busy" : ""}`}>
                          {toolCall.status === "requested" ? "Running" : toolCall.status === "error" ? "Error" : "Done"}
                        </span>
                      </div>
                      <pre>{JSON.stringify({ input: toolCall.input, output: toolCall.output ?? null }, null, 2)}</pre>
                    </article>
                  ))}
                </div>
              ) : null}
              {message.reasoning ? (
                <details>
                  <summary>Reasoning trace</summary>
                  <pre>{message.reasoning}</pre>
                </details>
              ) : null}
            </article>
          ))}
        </div>
        <div className="suggestion-row">
          {promptSuggestions.map((prompt) => (
            <button className="secondary-button" key={prompt} onClick={() => setDraft(prompt)} type="button">
              {prompt}
            </button>
          ))}
        </div>
        <label>
          <span>Prompt</span>
          <textarea onChange={(event) => setDraft(event.target.value)} rows={5} value={draft} />
        </label>
        <button
          className="primary-button"
          disabled={draft.trim().length === 0 || apiKey.trim().length === 0}
          onClick={() => {
            void sendChatMessage(draft.trim());
            setDraft("");
          }}
          type="button"
        >
          Stream to copilot
        </button>
      </section>

      <section className="panel">
        <div className="panel-header">
          <div>
            <p className="panel-kicker">Context</p>
            <h2>Agent resources</h2>
          </div>
        </div>
        <div className="summary-grid">
          <article className="metric-card">
            <span>Project</span>
            <strong>{summary?.project_name ?? "Untitled"}</strong>
          </article>
          <article className="metric-card">
            <span>Normalized assets</span>
            <strong>{assets.length}</strong>
          </article>
          <article className="metric-card">
            <span>Sensor count</span>
            <strong>{summary?.sensor_count ?? 0}</strong>
          </article>
          <article className="metric-card">
            <span>Scenarios</span>
            <strong>{summary?.scenario_count ?? 0}</strong>
          </article>
        </div>
        <div className="sensor-summary">
          <p className="panel-kicker">MCP catalog</p>
          <p>
            {mcpStatus === "loading"
              ? "Connecting to the MCP server catalog..."
              : mcpStatus === "error"
                ? `MCP catalog unavailable: ${mcpError}`
                : `${mcpCatalog?.serverName ?? "GoKaatru MCP"} v${mcpCatalog?.serverVersion ?? "unknown"}`}
          </p>
          {mcpCatalog ? (
            <>
              <p className="muted-text">{mcpCatalog.tools.length} tool(s), {mcpCatalog.resources.length} resource(s)</p>
              <div className="selection-list">
                {mcpCatalog.tools.slice(0, 6).map((tool) => (
                  <article className="asset-card" key={tool.name}>
                    <div className="asset-card-header">
                      <h3>{tool.name}</h3>
                      <span className="status-pill">MCP</span>
                    </div>
                    <p>{tool.description || "No description provided."}</p>
                  </article>
                ))}
              </div>
              <p className="muted-text">
                The frontend now loads the MCP catalog through the web API by default so browser transport and CORS issues do not block discovery. Session-bound workflow mutations still use the active workspace APIs so they operate on your current browser session.
              </p>
            </>
          ) : null}
        </div>
      </section>
    </div>
  );
}