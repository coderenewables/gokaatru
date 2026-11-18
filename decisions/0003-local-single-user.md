# 0003. Local, single-user deployment; actor recorded on every action; no authentication

**Status:** Accepted (owner), 2026-11-16. Platform and form: owner, 2026-11-17.

## Decision

- The application runs on the analyst's own machine: a local server opened in the browser.
  Windows first; macOS and Linux through Docker.
- No authentication is built. The session id remains the only credential, as the README's
  "Deployment model" section states.
- Every operation records its **actor** (the user, the assistant with its model name, or a
  plugin with its identity), so logins can be added later without redesigning the history.
- Every network listener binds to `127.0.0.1`. An MCP network transport additionally requires
  a token once one is built; until then the README says what binding to `0.0.0.0` exposes.

## Evidence

`startup.ps1 -IncludeMcp` bound the unauthenticated MCP SSE transport to `0.0.0.0`, exposing
all 232 tools to the local network. Fixed in P0-1 (`e04446e`).

## Consequences

- A hosted or team deployment is a new decision, not a configuration change: it needs
  authentication, per-user isolation and a security review first.
