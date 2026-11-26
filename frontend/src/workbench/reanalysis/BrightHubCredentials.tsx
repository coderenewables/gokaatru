import { useId, useState, type FormEvent } from "react";

import { api, unwrap } from "../api";

const message = (error: unknown): string => (error instanceof Error ? error.message : String(error));

/** Sign in to BrightHub for this session; the server holds the token, never the browser's
 * storage. Shown by the Reanalysis panel and by the Data panel's BrightHub import. */
export function BrightHubCredentials(props: {
  sessionId: string;
  authenticated: boolean;
  disabled: boolean;
  onChanged: () => void;
}) {
  const path = { params: { path: { session_id: props.sessionId } } };
  const headingId = useId();
  const [clientId, setClientId] = useState("");
  const [secret, setSecret] = useState("");
  const [error, setError] = useState<string | null>(null);

  async function login(event: FormEvent) {
    event.preventDefault();
    setError(null);
    try {
      unwrap(
        await api.POST("/api/sessions/{session_id}/operations/brighthub_login", {
          ...path,
          body: { client_id: clientId, client_secret: secret },
        }),
      );
      setSecret("");
      props.onChanged();
    } catch (failed) {
      setError(message(failed));
    }
  }

  async function logout() {
    setError(null);
    try {
      unwrap(await api.POST("/api/sessions/{session_id}/operations/brighthub_logout", { ...path, body: {} }));
      props.onChanged();
    } catch (failed) {
      setError(message(failed));
    }
  }

  return (
    <section aria-labelledby={headingId} className="gk-re-group">
      <h2 id={headingId}>BrightHub account</h2>
      {props.authenticated ? (
        <div className="gk-re-row">
          <span>Signed in for this session.</span>
          <button type="button" className="gk-button" onClick={() => void logout()} disabled={props.disabled}>
            Sign out
          </button>
        </div>
      ) : (
        <form onSubmit={(event) => void login(event)} className="gk-re-form">
          <label>
            Client ID
            <input type="text" value={clientId} onChange={(event) => setClientId(event.target.value)} autoComplete="off" />
          </label>
          <label>
            Client secret
            <input type="password" value={secret} onChange={(event) => setSecret(event.target.value)} autoComplete="off" />
          </label>
          <button type="submit" className="gk-button" disabled={props.disabled || clientId === "" || secret === ""}>
            Sign in
          </button>
        </form>
      )}
      {error && (
        <p role="alert" className="gk-re-failure">
          {error}
        </p>
      )}
      <p className="gk-muted gk-re-note">Held by the server for this session only.</p>
    </section>
  );
}
