// BYOK copilot chat (spec §6). Streaming chat with inline tool-call chips.
//
// API keys live only in localStorage (writeChatSettings). The backend
// /sessions/{id}/chat proxy executes MCP tools server-side; the local
// copilotAgent handles simple config mutations client-side and defers the rest.
import { useEffect, useRef, useState } from "react";

import { useWorkspaceStore } from "../store/useWorkspaceStore";
import {
  SUPPORTED_COPILOT_PROVIDERS,
  defaultModelForProvider,
  type CopilotToolEvent,
} from "../lib/copilotAgent";

const PROVIDER_LABELS: Record<(typeof SUPPORTED_COPILOT_PROVIDERS)[number], string> = {
  openai: "OpenAI",
  openrouter: "OpenRouter",
  groq: "Groq",
  together: "Together",
};

export function CopilotView() {
  const chatMessages = useWorkspaceStore((state) => state.chatMessages);
  const chatSettings = useWorkspaceStore((state) => state.chatSettings);
  const sendChatMessage = useWorkspaceStore((state) => state.sendChatMessage);
  const setChatSettings = useWorkspaceStore((state) => state.setChatSettings);
  const summary = useWorkspaceStore((state) => state.summary);

  const [draft, setDraft] = useState("");
  const [settingsOpen, setSettingsOpen] = useState(!chatSettings.apiKey || !!chatSettings.replacedProvider);
  const scrollRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    scrollRef.current?.scrollTo({ top: scrollRef.current.scrollHeight, behavior: "smooth" });
  }, [chatMessages]);

  const send = () => {
    const text = draft.trim();
    if (!text) return;
    setDraft("");
    void sendChatMessage(text);
  };

  return (
    <div className="copilot-view">
      <header className="copilot-header">
        <h3>Copilot</h3>
        <button type="button" className="link-button" onClick={() => setSettingsOpen((v) => !v)}>
          {chatSettings.apiKey ? "Settings" : "Add API key"}
        </button>
      </header>

      {settingsOpen ? (
        <SettingsDrawer
          settings={chatSettings}
          onSave={(s) => {
            setChatSettings(s);
            setSettingsOpen(false);
          }}
        />
      ) : null}

      <div className="copilot-thread" ref={scrollRef}>
        {chatMessages.length === 0 ? (
          <div className="copilot-empty">
            <p className="muted">
              Ask the copilot to inspect data, run operations, or explain results. Example:
              <em> “Set hub height to 140, then summarise sensor coverage.”</em>
            </p>
          </div>
        ) : (
          chatMessages.map((msg) => <Message key={msg.id} message={msg} />)
        )}
      </div>

      <form
        className="copilot-input"
        onSubmit={(e) => {
          e.preventDefault();
          send();
        }}
      >
        <input
          type="text"
          value={draft}
          onChange={(e) => setDraft(e.target.value)}
          placeholder={
            summary
              ? "Ask the copilot…"
              : "Create a session and load data to begin…"
          }
          disabled={!summary}
        />
        <button type="submit" className="primary-button" disabled={!draft.trim() || !summary}>
          Send
        </button>
      </form>
    </div>
  );
}

function SettingsDrawer({
  settings,
  onSave,
}: {
  settings: import("../lib/copilotAgent").CopilotSettings;
  onSave: (s: import("../lib/copilotAgent").CopilotSettings) => void;
}) {
  const [provider, setProvider] = useState(settings.provider);
  const [model, setModel] = useState(settings.model);
  const [apiKey, setApiKey] = useState(settings.apiKey);
  const [allowMutatingTools, setAllowMutatingTools] = useState(settings.allowMutatingTools === true);

  return (
    <div className="settings-drawer">
      <h4>BYOK settings</h4>
      <p className="muted">Keys are stored only in this browser's localStorage.</p>
      {settings.replacedProvider ? (
        <p className="muted">
          The saved provider "{settings.replacedProvider}" is not supported yet and was replaced with OpenAI.
        </p>
      ) : null}
      <div className="form-grid">
        <label className="form-field">
          <span>Provider</span>
          <select
            value={provider}
            onChange={(e) => {
              setProvider(e.target.value);
              setModel(defaultModelForProvider(e.target.value));
            }}
          >
            {SUPPORTED_COPILOT_PROVIDERS.map((p) => (
              <option key={p} value={p}>
                {PROVIDER_LABELS[p]}
              </option>
            ))}
          </select>
        </label>
        <label className="form-field">
          <span>Model</span>
          <input type="text" value={model} onChange={(e) => setModel(e.target.value)} />
        </label>
        <label className="form-field">
          <span>API key</span>
          <input
            type="password"
            value={apiKey}
            onChange={(e) => setApiKey(e.target.value)}
            placeholder="sk-…"
          />
        </label>
        <label className="form-field">
          <span>Allow the assistant to change session data</span>
          <input
            type="checkbox"
            checked={allowMutatingTools}
            onChange={(e) => setAllowMutatingTools(e.target.checked)}
          />
          <small className="muted">
            Off by default. When on, the assistant can change session data without asking for each change.
          </small>
        </label>
      </div>
      <button
        type="button"
        className="primary-button"
        onClick={() => onSave({ provider, model, apiKey, allowMutatingTools })}
        disabled={!apiKey}
      >
        Save
      </button>
    </div>
  );
}

function Message({ message }: { message: import("../lib/copilotAgent").CopilotMessage }) {
  const isUser = message.role === "user";
  return (
    <article className={`copilot-message ${message.role} status-${message.status}`}>
      <header>
        <strong>{isUser ? "You" : "Copilot"}</strong>
        {message.status === "streaming" ? <span className="muted">· typing…</span> : null}
        {message.status === "error" ? <span className="error-text">· error</span> : null}
      </header>
      <div className="copilot-message-body">{message.content || (message.status === "streaming" ? "…" : "")}</div>
      {message.toolCalls.length > 0 ? (
        <div className="tool-chips">
          {message.toolCalls.map((tc) => (
            <ToolChip key={tc.id} tool={tc} />
          ))}
        </div>
      ) : null}
    </article>
  );
}

function ToolChip({ tool }: { tool: CopilotToolEvent }) {
  const [expanded, setExpanded] = useState(false);
  const cls = `tool-chip tool-${tool.status}`;
  return (
    <div className={cls}>
      <button type="button" className="tool-chip-head" onClick={() => setExpanded((v) => !v)}>
        <span className="tool-chip-name">🔧 {tool.toolName}</span>
        <span className="tool-chip-status">{tool.status}</span>
      </button>
      {expanded ? (
        <pre className="tool-chip-detail">
          {JSON.stringify({ arguments: tool.arguments, result: tool.result, error: tool.error }, null, 2)}
        </pre>
      ) : null}
    </div>
  );
}
