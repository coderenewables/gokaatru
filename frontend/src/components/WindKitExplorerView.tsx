// WindKit explorer (spec §2.1 / Phase G). Advanced tool surface over /api/windkit/*.
//
// Categories + tools are discovered from the backend OpenAPI spec at runtime.
// Selecting a tool loads a JSON payload editor; the result renders below.
import { useEffect, useMemo, useState } from "react";

import { useWorkspaceStore } from "../store/useWorkspaceStore";
import { groupWindKitToolsByCategory } from "../lib/openapi";
import { RunButton } from "./common/RunButton";

export function WindKitExplorerView() {
  const windkitTools = useWorkspaceStore((state) => state.windkitTools);
  const windkitResponse = useWorkspaceStore((state) => state.windkitResponse);
  const refreshWindKitTools = useWorkspaceStore((state) => state.refreshWindKitTools);
  const invokeWindKitRoute = useWorkspaceStore((state) => state.invokeWindKitRoute);

  const grouped = useMemo(() => groupWindKitToolsByCategory(windkitTools), [windkitTools]);
  const categories = Object.keys(grouped);

  const [selectedPath, setSelectedPath] = useState<string>("");
  const [payload, setPayload] = useState<string>("{}");

  useEffect(() => {
    refreshWindKitTools();
  }, [refreshWindKitTools]);

  const run = () => {
    let parsed: unknown = {};
    try {
      parsed = JSON.parse(payload);
    } catch {
      parsed = {};
    }
    if (selectedPath) void invokeWindKitRoute(selectedPath, parsed);
  };

  return (
    <div className="windkit-view">
      <section className="path-panel">
        <h3>WindKit tools</h3>
        <p className="muted">
          {windkitTools.length} tools discovered from the backend OpenAPI spec. Select one to compose a
          JSON payload and run it.
        </p>
        {categories.length === 0 ? (
          <p className="muted">No tools loaded. Ensure the backend is reachable.</p>
        ) : (
          <div className="windkit-categories">
            {categories.map((cat) => (
              <details key={cat} className="windkit-category" open={categories.indexOf(cat) === 0}>
                <summary>
                  {cat} <span className="muted">({grouped[cat].length})</span>
                </summary>
                <ul className="windkit-tool-list">
                  {grouped[cat].map((tool) => (
                    <li key={tool.path}>
                      <button
                        type="button"
                        className={selectedPath === tool.path ? "windkit-tool active" : "windkit-tool"}
                        onClick={() => setSelectedPath(tool.path)}
                        title={tool.summary}
                      >
                        <span className="windkit-tool-name">{tool.name}</span>
                        {tool.summary ? <span className="muted">{tool.summary}</span> : null}
                      </button>
                    </li>
                  ))}
                </ul>
              </details>
            ))}
          </div>
        )}
      </section>

      {selectedPath ? (
        <section className="path-panel">
          <h3>Run · {selectedPath}</h3>
          <label className="form-field">
            <span>Payload (JSON)</span>
            <textarea
              className="windkit-payload"
              value={payload}
              onChange={(e) => setPayload(e.target.value)}
              rows={8}
              spellCheck={false}
            />
          </label>
          <div className="path-actions">
            <RunButton label="Run tool" onClick={run} />
          </div>
        </section>
      ) : null}

      {windkitResponse != null ? (
        <section className="path-panel">
          <h3>Result</h3>
          <pre className="preview-payload">{JSON.stringify(windkitResponse, null, 2)}</pre>
        </section>
      ) : null}
    </div>
  );
}
