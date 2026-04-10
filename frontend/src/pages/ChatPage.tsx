import { useCallback, useRef, useState } from "react";
import { useMutation } from "@tanstack/react-query";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";

import { chatApi } from "../lib/api";
import type { ChatMessage, ChatResponse, ChatToolCallResult } from "../lib/types";
import { useWorkspaceStore } from "../stores/workspaceStore";
import { PageHeader } from "../components/common/PageHeader";
import { EmptyState } from "../components/common/EmptyState";

const PROVIDERS = [
  { value: "openai", label: "OpenAI" },
  { value: "openrouter", label: "OpenRouter" },
  { value: "groq", label: "Groq" },
  { value: "together", label: "Together AI" },
];

interface DisplayMessage {
  role: "user" | "assistant";
  content: string;
  toolCalls?: ChatToolCallResult[];
}

export function ChatPage() {
  const sessionId = useWorkspaceStore((s) => s.sessionId);

  const [apiKey, setApiKey] = useState("");
  const [provider, setProvider] = useState("openai");
  const [model, setModel] = useState("");
  const [input, setInput] = useState("");
  const [messages, setMessages] = useState<DisplayMessage[]>([]);
  const [conversationHistory, setConversationHistory] = useState<ChatMessage[]>([]);
  const messagesEndRef = useRef<HTMLDivElement>(null);

  const scrollToBottom = useCallback(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: "smooth" });
  }, []);

  const chatMutation = useMutation({
    mutationFn: (userMessage: string) => {
      const newHistory: ChatMessage[] = [...conversationHistory, { role: "user", content: userMessage }];
      return chatApi.send(sessionId ?? "", {
        api_key: apiKey,
        provider,
        model,
        messages: newHistory,
      });
    },
    onSuccess: (response: ChatResponse, userMessage: string) => {
      const updatedHistory: ChatMessage[] = [
        ...conversationHistory,
        { role: "user", content: userMessage },
        { role: "assistant", content: response.reply },
      ];
      setConversationHistory(updatedHistory);
      setMessages((prev) => [
        ...prev,
        { role: "user", content: userMessage },
        { role: "assistant", content: response.reply, toolCalls: response.tool_calls_executed },
      ]);
      setTimeout(scrollToBottom, 50);
    },
  });

  const handleSend = useCallback(() => {
    const trimmed = input.trim();
    if (!trimmed || !sessionId || !apiKey) return;
    setInput("");
    chatMutation.mutate(trimmed);
  }, [input, sessionId, apiKey, chatMutation]);

  const handleKeyDown = useCallback(
    (e: React.KeyboardEvent) => {
      if (e.key === "Enter" && !e.shiftKey) {
        e.preventDefault();
        handleSend();
      }
    },
    [handleSend],
  );

  if (!sessionId) {
    return (
      <>
        <PageHeader title="Chat" detail="Ask questions about your wind data using an AI assistant." />
        <EmptyState title="No session active" detail="Create or select a session to start chatting." />
      </>
    );
  }

  return (
    <>
      <PageHeader title="Chat" detail="Ask questions about your wind data using an AI assistant with MCP tools." />

      {/* Settings bar */}
      <article className="content-card" style={{ marginBottom: "1rem" }}>
        <div style={{ display: "flex", gap: "0.75rem", flexWrap: "wrap", alignItems: "end" }}>
          <label style={{ display: "flex", flexDirection: "column", gap: "0.25rem", flex: "1 1 200px" }}>
            <span className="eyebrow">API Key</span>
            <input
              type="password"
              value={apiKey}
              onChange={(e) => setApiKey(e.target.value)}
              placeholder="sk-... or your provider key"
              className="text-input"
            />
          </label>
          <label style={{ display: "flex", flexDirection: "column", gap: "0.25rem" }}>
            <span className="eyebrow">Provider</span>
            <select value={provider} onChange={(e) => setProvider(e.target.value)} className="text-input">
              {PROVIDERS.map((p) => (
                <option key={p.value} value={p.value}>
                  {p.label}
                </option>
              ))}
            </select>
          </label>
          <label style={{ display: "flex", flexDirection: "column", gap: "0.25rem", flex: "0 1 200px" }}>
            <span className="eyebrow">Model (optional)</span>
            <input
              type="text"
              value={model}
              onChange={(e) => setModel(e.target.value)}
              placeholder="Default for provider"
              className="text-input"
            />
          </label>
        </div>
      </article>

      {/* Chat messages */}
      <article
        className="content-card"
        style={{ minHeight: "400px", maxHeight: "60vh", overflowY: "auto", display: "flex", flexDirection: "column" }}
      >
        {messages.length === 0 && (
          <div style={{ flex: 1, display: "flex", alignItems: "center", justifyContent: "center" }}>
            <p className="muted-text">Send a message to start the conversation.</p>
          </div>
        )}
        <div style={{ flex: 1 }}>
          {messages.map((msg, idx) => (
            <div
              key={idx}
              style={{
                marginBottom: "1rem",
                padding: "0.75rem",
                borderRadius: "8px",
                background: msg.role === "user" ? "var(--surface-2, #f0f0f0)" : "var(--surface-1, #fff)",
                border: msg.role === "assistant" ? "1px solid var(--border, #ddd)" : "none",
              }}
            >
              <div style={{ fontWeight: 600, marginBottom: "0.25rem", fontSize: "0.8rem", textTransform: "uppercase" }}>
                {msg.role === "user" ? "You" : "GoKaatru"}
              </div>
              {msg.role === "assistant" ? (
                <div className="markdown-body">
                  <ReactMarkdown remarkPlugins={[remarkGfm]}>{msg.content}</ReactMarkdown>
                </div>
              ) : (
                <div style={{ whiteSpace: "pre-wrap" }}>{msg.content}</div>
              )}
              {msg.toolCalls && msg.toolCalls.length > 0 && (
                <details style={{ marginTop: "0.5rem" }}>
                  <summary style={{ cursor: "pointer", fontSize: "0.85rem", color: "var(--accent, #0066cc)" }}>
                    {msg.toolCalls.length} tool call{msg.toolCalls.length > 1 ? "s" : ""} executed
                  </summary>
                  <div style={{ marginTop: "0.5rem" }}>
                    {msg.toolCalls.map((tc, tcIdx) => (
                      <div key={tcIdx} style={{ marginBottom: "0.5rem", fontSize: "0.85rem" }}>
                        <strong>{tc.tool_name}</strong>
                        <pre
                          style={{
                            background: "var(--surface-2, #f0f0f0)",
                            padding: "0.5rem",
                            borderRadius: "4px",
                            overflow: "auto",
                            maxHeight: "200px",
                            fontSize: "0.75rem",
                          }}
                        >
                          {JSON.stringify(tc.arguments, null, 2)}
                        </pre>
                      </div>
                    ))}
                  </div>
                </details>
              )}
            </div>
          ))}
          {chatMutation.isPending && (
            <div style={{ padding: "0.75rem", color: "var(--muted, #888)" }}>
              <em>Thinking...</em>
            </div>
          )}
          <div ref={messagesEndRef} />
        </div>
      </article>

      {/* Input area */}
      <article className="content-card" style={{ marginTop: "1rem" }}>
        {chatMutation.isError && (
          <div style={{ color: "var(--danger, red)", marginBottom: "0.5rem", fontSize: "0.85rem" }}>
            Error: {chatMutation.error instanceof Error ? chatMutation.error.message : "Request failed"}
          </div>
        )}
        <div style={{ display: "flex", gap: "0.5rem" }}>
          <textarea
            value={input}
            onChange={(e) => setInput(e.target.value)}
            onKeyDown={handleKeyDown}
            placeholder={apiKey ? "Ask about your wind data..." : "Enter your API key above first"}
            disabled={!apiKey || chatMutation.isPending}
            className="text-input"
            rows={2}
            style={{ flex: 1, resize: "vertical" }}
          />
          <button
            className="primary-button"
            type="button"
            onClick={handleSend}
            disabled={!input.trim() || !apiKey || chatMutation.isPending}
          >
            Send
          </button>
        </div>
      </article>
    </>
  );
}
