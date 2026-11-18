# 0007. Assistant: bring your own key; every data change needs approval

**Status:** Accepted (owner), 2026-11-17.

## Decision

- **Providers, in order:** Anthropic (the native Messages API through the official SDK) and
  any OpenAI-compatible endpoint (OpenAI, OpenRouter, Groq, Together, local servers such as
  Ollama) first; Gemini later. A custom endpoint is accepted only after its address is
  resolved and checked; local addresses are an explicit opt-in.
- **Keys** are kept in the operating system's keychain, never in browser storage and never in
  a project file.
- **Read-only tools run freely. Every data change needs approval:** it arrives as a card
  showing its dry-run result, and the user approves, edits or rejects it. An "approve all
  for this session" switch exists and is off by default.
- **Conversations and tool results** go into the operation log, so a result can be traced to
  the conversation that produced it.
- **Untrusted content:** tool output and external MCP results are wrapped as data, size-capped,
  and never followed as instructions. Tools from an external MCP server start unclassified,
  which means not callable, until the user marks each one.
- The whole product, sweep included, is reachable over MCP so an outside agent can drive it.

## Evidence

- The Copilot listed Anthropic, which the backend refused with HTTP 400 (F3), and enabled
  data-changing tools by default with no per-action confirmation (F4). Until approval cards
  exist, the provider list is the working four and data-changing tools are off unless the
  user opts in: P0-5 (`ec5a0d5`).

## Consequences

- Approval cards depend on every data-changing operation having a dry run
  ([0009](0009-operation-registry.md)).
- The plan's earlier choice of holding the key in server memory only is replaced by the
  keychain, at the owner's choice.
