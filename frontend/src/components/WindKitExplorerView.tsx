import { useDeferredValue, useEffect, useMemo, useState } from "react";

import { assetFitsField, previewAssetJson } from "../lib/normalization";
import type { WindKitToolField } from "../lib/openapi";
import { useWorkspaceStore } from "../store/useWorkspaceStore";

function defaultFieldValue(field: WindKitToolField): string {
  if (field.schema.default !== undefined) {
    return typeof field.schema.default === "string" ? field.schema.default : JSON.stringify(field.schema.default);
  }
  if (field.inputKind === "boolean") {
    return "false";
  }
  return field.inputKind === "json" || field.inputKind === "asset-json" ? "{}" : "";
}

function parseFieldValue(field: WindKitToolField, rawValue: string): unknown {
  if (field.inputKind === "number") {
    return Number(rawValue);
  }
  if (field.inputKind === "boolean") {
    return rawValue === "true";
  }
  if (field.inputKind === "json" || field.inputKind === "asset-json") {
    return JSON.parse(rawValue);
  }
  return rawValue;
}

export function WindKitExplorerView() {
  const windkitTools = useWorkspaceStore((state) => state.windkitTools);
  const assets = useWorkspaceStore((state) => state.assets);
  const windkitResponse = useWorkspaceStore((state) => state.windkitResponse);
  const invokeWindKitTool = useWorkspaceStore((state) => state.invokeWindKitTool);

  const [search, setSearch] = useState("");
  const [selectedToolPath, setSelectedToolPath] = useState("");
  const [rawValues, setRawValues] = useState<Record<string, string>>({});
  const [assetBindings, setAssetBindings] = useState<Record<string, string>>({});
  const [error, setError] = useState<string | null>(null);
  const deferredSearch = useDeferredValue(search);

  const filteredTools = useMemo(() => {
    const query = deferredSearch.trim().toLowerCase();
    if (!query) {
      return windkitTools;
    }
    return windkitTools.filter((tool) => {
      return (
        tool.path.toLowerCase().includes(query)
        || tool.summary.toLowerCase().includes(query)
        || tool.category.toLowerCase().includes(query)
      );
    });
  }, [deferredSearch, windkitTools]);

  const selectedTool = useMemo(
    () => filteredTools.find((tool) => tool.path === selectedToolPath) ?? filteredTools[0] ?? null,
    [filteredTools, selectedToolPath],
  );

  useEffect(() => {
    if (!selectedTool && filteredTools.length === 0) {
      return;
    }
    if (!selectedTool || selectedTool.path !== selectedToolPath) {
      setSelectedToolPath(filteredTools[0]?.path ?? "");
    }
  }, [filteredTools, selectedTool, selectedToolPath]);

  useEffect(() => {
    if (!selectedTool) {
      return;
    }
    setRawValues(
      Object.fromEntries(selectedTool.fields.map((field) => [field.name, defaultFieldValue(field)])),
    );
    setAssetBindings({});
    setError(null);
  }, [selectedTool?.path]);

  const categories = useMemo(() => {
    return Array.from(new Set(windkitTools.map((tool) => tool.category))).sort();
  }, [windkitTools]);

  return (
    <div className="windkit-layout">
      <section className="panel windkit-tool-list">
        <div className="panel-header">
          <div>
            <p className="panel-kicker">Phase 3</p>
            <h2>WindKit explorer</h2>
          </div>
        </div>
        <label>
          <span>Search tools</span>
          <input onChange={(event) => setSearch(event.target.value)} placeholder="wind speed, topography, ltc..." type="search" value={search} />
        </label>
        <div className="category-chip-row">
          {categories.map((category) => (
            <span className="status-pill" key={category}>
              {category}
            </span>
          ))}
        </div>
        <div className="tool-list">
          {filteredTools.map((tool) => (
            <button
              className={`tool-list-item ${selectedTool?.path === tool.path ? "tool-list-item-active" : ""}`}
              key={tool.path}
              onClick={() => setSelectedToolPath(tool.path)}
              type="button"
            >
              <strong>{tool.summary}</strong>
              <span>{tool.path}</span>
            </button>
          ))}
        </div>
      </section>

      <section className="panel windkit-form-panel">
        <div className="panel-header">
          <div>
            <p className="panel-kicker">Dynamic request form</p>
            <h2>{selectedTool?.summary ?? "Select a WindKit tool"}</h2>
          </div>
          {selectedTool ? <span className="status-pill">{selectedTool.category}</span> : null}
        </div>

        {selectedTool ? (
          <div className="windkit-form-grid">
            {selectedTool.fields.map((field) => {
              const compatibleAssets = assets.filter((asset) => assetFitsField(asset, field.name));
              const boundAsset = compatibleAssets.find((asset) => asset.id === assetBindings[field.name]) ?? null;

              return (
                <div className="tool-field" key={field.name}>
                  <label>
                    <span>
                      {field.label}
                      {field.required ? " *" : ""}
                    </span>
                    {field.inputKind === "enum" ? (
                      <select
                        onChange={(event) => setRawValues((state) => ({ ...state, [field.name]: event.target.value }))}
                        value={rawValues[field.name] ?? ""}
                      >
                        {(field.schema.enum ?? []).map((option) => (
                          <option key={String(option)} value={String(option)}>
                            {String(option)}
                          </option>
                        ))}
                      </select>
                    ) : null}

                    {field.inputKind === "boolean" ? (
                      <select
                        onChange={(event) => setRawValues((state) => ({ ...state, [field.name]: event.target.value }))}
                        value={rawValues[field.name] ?? "false"}
                      >
                        <option value="false">False</option>
                        <option value="true">True</option>
                      </select>
                    ) : null}

                    {field.inputKind === "number" ? (
                      <input
                        onChange={(event) => setRawValues((state) => ({ ...state, [field.name]: event.target.value }))}
                        type="number"
                        value={rawValues[field.name] ?? ""}
                      />
                    ) : null}

                    {field.inputKind === "text" ? (
                      <input
                        onChange={(event) => setRawValues((state) => ({ ...state, [field.name]: event.target.value }))}
                        type="text"
                        value={rawValues[field.name] ?? ""}
                      />
                    ) : null}

                    {field.inputKind === "json" || field.inputKind === "asset-json" ? (
                      <>
                        {field.inputKind === "asset-json" ? (
                          <select
                            onChange={(event) => setAssetBindings((state) => ({ ...state, [field.name]: event.target.value }))}
                            value={assetBindings[field.name] ?? ""}
                          >
                            <option value="">Use raw JSON</option>
                            {compatibleAssets.map((asset) => (
                              <option key={asset.id} value={asset.id}>
                                {asset.label}
                              </option>
                            ))}
                          </select>
                        ) : null}
                        <textarea
                          onChange={(event) => setRawValues((state) => ({ ...state, [field.name]: event.target.value }))}
                          rows={6}
                          value={rawValues[field.name] ?? "{}"}
                        />
                        {boundAsset ? <pre>{previewAssetJson(boundAsset)}</pre> : null}
                      </>
                    ) : null}
                  </label>
                  <p className="muted-text">{field.schema.description ?? `Request field ${field.name}`}</p>
                </div>
              );
            })}

            <div className="button-row">
              <button
                className="primary-button"
                onClick={() => {
                  if (!selectedTool) {
                    return;
                  }
                  try {
                    const payload = Object.fromEntries(
                      selectedTool.fields
                        .map((field) => {
                          const assetId = assetBindings[field.name];
                          const boundAsset = assets.find((asset) => asset.id === assetId && assetFitsField(asset, field.name));
                          const value = boundAsset ? boundAsset.payload : parseFieldValue(field, rawValues[field.name] ?? defaultFieldValue(field));
                          return [field.name, value] as const;
                        })
                        .filter((entry) => entry[1] !== undefined),
                    );
                    setError(null);
                    void invokeWindKitTool(selectedTool.path, payload);
                  } catch (caughtError) {
                    setError(caughtError instanceof Error ? caughtError.message : String(caughtError));
                  }
                }}
                type="button"
              >
                Run WindKit tool
              </button>
            </div>
            {error ? <p className="error-text">{error}</p> : null}
          </div>
        ) : (
          <p className="muted-text">No WindKit tools were discovered from the backend OpenAPI specification.</p>
        )}
      </section>

      <section className="panel windkit-response-panel">
        <div className="panel-header">
          <div>
            <p className="panel-kicker">Normalized result</p>
            <h2>Latest WindKit response</h2>
          </div>
        </div>
        {windkitResponse ? <pre>{JSON.stringify(windkitResponse, null, 2)}</pre> : <p className="muted-text">Run a WindKit tool to inspect the standardized response envelope.</p>}
      </section>
    </div>
  );
}