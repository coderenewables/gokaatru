import { useEffect, useMemo, useRef } from "react";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { ApiError, configApi, uploadsApi, workflowApi } from "../../lib/api";
import type { NodeConfigField } from "../../lib/nodeRegistry";
import { parseLooseJson } from "../../lib/paramsJson";
import type { JsonValue, SensorRecord, WorkflowDispatchCapability } from "../../lib/types";
import { useWorkflowUiStore } from "../../stores/workflowUiStore";
import type { WorkflowNode } from "../../stores/workflowStore";
import { useWorkflowStore } from "../../stores/workflowStore";
import { useWorkspaceStore } from "../../stores/workspaceStore";

function renderValue(value: string | number | boolean) {
  if (typeof value === "boolean") {
    return value ? "Enabled" : "Disabled";
  }
  return String(value);
}

const PARAM_ALIASES: Record<string, string[]> = {
  file_path: ["path", "timeseries_path", "timeseries_file", "datamodel_path", "datamodel_file"],
  sensor_name: ["sensor"],
  entry_index: ["index"],
  height_sensors: ["sensors", "height_map"],
  direction_sensor: ["dir_sensor"],
  sensor_names: ["sensors"],
  nodes_json: ["nodes"],
  params: ["rule_params", "parameters"],
  west_east: ["we"],
  south_north: ["sn"],
  height: ["h"],
};

function hasValue(value: unknown): boolean {
  if (value === null || value === undefined) {
    return false;
  }
  if (typeof value === "string") {
    return value.trim() !== "";
  }
  return true;
}

function configKeysFromNode(node: WorkflowNode): { keys: Set<string>; parseError: string | null } {
  const keys = new Set<string>();
  if (node.data.kind !== "operation" || !node.data.config) {
    return { keys, parseError: null };
  }

  for (const [key, value] of Object.entries(node.data.config)) {
    if (key === "params_json") {
      continue;
    }
    if (hasValue(value)) {
      keys.add(key);
    }
  }

  const rawParams = node.data.config.params_json;
  let parseError: string | null = null;
  if (typeof rawParams === "string" && rawParams.trim() !== "" && rawParams.trim() !== "{}") {
    const result = parseLooseJson(rawParams);
    if (result.ok) {
      const parsed = result.value;
      if (parsed && typeof parsed === "object" && !Array.isArray(parsed)) {
        for (const [key, value] of Object.entries(parsed as Record<string, unknown>)) {
          if (hasValue(value)) {
            keys.add(key);
          }
        }
      }
    } else {
      parseError = result.error;
    }
  }

  return { keys, parseError };
}

function requiredParamStatus(required: string, configuredKeys: Set<string>) {
  if (configuredKeys.has(required)) {
    return true;
  }
  const aliases = PARAM_ALIASES[required] ?? [];
  return aliases.some((alias) => configuredKeys.has(alias));
}

function validationSummary(capability: WorkflowDispatchCapability | null, configuredKeys: Set<string>) {
  if (!capability) {
    return { missing: [], present: [] };
  }
  const present: string[] = [];
  const missing: string[] = [];
  for (const required of capability.required_params) {
    if (requiredParamStatus(required, configuredKeys)) {
      present.push(required);
    } else {
      missing.push(required);
    }
  }
  return { missing, present };
}

function sampleValueForParam(name: string): JsonValue {
  const normalized = name.toLowerCase();

  if (normalized === "params" || normalized === "rule_params" || normalized === "parameters") {
    return { example_key: "value" };
  }

  if (normalized === "nodes" || normalized === "nodes_json") {
    return [{ id: "node-1", label: "Example node" }];
  }

  if (normalized === "sensor" || normalized === "sensor_name" || normalized === "direction_sensor") {
    return "Spd_100m";
  }

  if (normalized === "sensor_names" || normalized === "sensors" || normalized === "height_sensors") {
    return ["Spd_100m", "Dir_100m"];
  }

  if (normalized.endsWith("_path") || normalized.endsWith("_file") || normalized === "file_path") {
    return "uploads/example-input.json";
  }

  if (normalized.includes("latitude")) {
    return 52.4;
  }

  if (normalized.includes("longitude")) {
    return 4.8;
  }

  if (normalized.includes("elevation")) {
    return 0;
  }

  if (normalized.endsWith("_date")) {
    return normalized.startsWith("end") ? "2024-12-31" : "2024-01-01";
  }

  if (normalized === "start") {
    return 0;
  }

  if (normalized === "end") {
    return 360;
  }

  if (normalized === "bins" || normalized.includes("sector_count")) {
    return 12;
  }

  if (normalized.endsWith("_index") || normalized === "index" || normalized.endsWith("_count") || normalized === "count") {
    return 0;
  }

  if (normalized.includes("height") || normalized.endsWith("_m")) {
    return 100;
  }

  if (normalized.startsWith("is_") || normalized.startsWith("has_") || normalized.startsWith("use_") || normalized.endsWith("_enabled")) {
    return true;
  }

  return `example_${name}`;
}

function buildSampleParams(capability: WorkflowDispatchCapability): Record<string, JsonValue> {
  const params: Record<string, JsonValue> = {};
  for (const name of [...capability.required_params, ...capability.optional_params]) {
    if (!(name in params)) {
      params[name] = sampleValueForParam(name);
    }
  }
  return params;
}

function isUntouchedParamsJson(value: unknown): boolean {
  if (typeof value !== "string") {
    return false;
  }

  const trimmed = value.trim();
  return trimmed === "" || trimmed === "{}";
}

function buildRunconfigUpdateKey(branchId: string, nodeId: string) {
  return `workflow.branches.${branchId}.nodes.${nodeId}`;
}

function humanizeParamName(name: string): string {
  return name
    .split("_")
    .map((token) => token.charAt(0).toUpperCase() + token.slice(1))
    .join(" ");
}

function parseParamsObject(raw: unknown): { params: Record<string, JsonValue>; parseError: string | null } {
  if (typeof raw !== "string" || raw.trim() === "") {
    return { params: {}, parseError: null };
  }

  const parsed = parseLooseJson(raw);
  if (!parsed.ok) {
    return { params: {}, parseError: parsed.error };
  }

  if (!parsed.value || typeof parsed.value !== "object" || Array.isArray(parsed.value)) {
    return { params: {}, parseError: "params_json must decode to a JSON object" };
  }

  return { params: parsed.value as Record<string, JsonValue>, parseError: null };
}

function valueForParam(params: Record<string, JsonValue>, name: string): JsonValue | undefined {
  if (name in params) {
    return params[name];
  }
  const aliases = PARAM_ALIASES[name] ?? [];
  for (const alias of aliases) {
    if (alias in params) {
      return params[alias];
    }
  }
  return undefined;
}

function withParamValue(params: Record<string, JsonValue>, name: string, value: JsonValue | undefined) {
  const next = { ...params };
  delete next[name];
  for (const alias of PARAM_ALIASES[name] ?? []) {
    delete next[alias];
  }

  if (value === undefined) {
    return next;
  }
  if (typeof value === "string" && value.trim() === "") {
    return next;
  }
  next[name] = value;
  return next;
}

function asStringArray(value: JsonValue | undefined): string[] {
  if (!Array.isArray(value)) {
    return [];
  }
  return value.map((item) => String(item));
}

function inferInputKind(paramName: string):
  | "text"
  | "number"
  | "boolean"
  | "json"
  | "sensor-single"
  | "sensor-multi"
  | "date" {
  const normalized = paramName.toLowerCase();

  if (normalized === "height_sensors" || normalized === "sensor_names" || normalized === "sensors") {
    return "sensor-multi";
  }
  if (normalized === "sensor" || normalized === "sensor_name" || normalized === "direction_sensor") {
    return "sensor-single";
  }
  if (normalized === "params" || normalized === "nodes_json") {
    return "json";
  }
  if (normalized.endsWith("_date")) {
    return "date";
  }
  if (normalized.startsWith("is_") || normalized.startsWith("has_") || normalized.startsWith("use_") || normalized.endsWith("_enabled")) {
    return "boolean";
  }
  if (normalized.endsWith("_index") || normalized.endsWith("_count") || normalized === "count" || normalized === "bins") {
    return "number";
  }
  if (normalized === "start" || normalized === "end") {
    return "number";
  }
  if (normalized === "height" || normalized.endsWith("_m")) {
    return "number";
  }
  return "text";
}

function sensorOptions(records: SensorRecord[]) {
  const all = records.map((sensor) => sensor.name);
  const speed = records
    .filter((sensor) => sensor.sensor_type === "wind_speed" || sensor.name.toLowerCase().startsWith("spd_"))
    .map((sensor) => sensor.name);
  const direction = records
    .filter((sensor) => sensor.sensor_type === "wind_direction" || sensor.name.toLowerCase().startsWith("dir_"))
    .map((sensor) => sensor.name);
  return {
    all,
    speed: speed.length > 0 ? speed : all,
    direction: direction.length > 0 ? direction : all,
  };
}

export function NodeInspector() {
  const workspaceSessionId = useWorkspaceStore((state) => state.sessionId);
  const activeBranchId = useWorkflowUiStore((state) => state.activeBranchId);
  const selectedNodeId = useWorkflowUiStore((state) => state.selectedNodeId);
  const setSelectedNodeId = useWorkflowUiStore((state) => state.setSelectedNodeId);
  const activeBranchSessionId = useWorkflowStore((state) => {
    const branch = state.branches.find((candidate) => candidate.id === activeBranchId);
    return branch?.sessionId ?? null;
  });
  const sessionId = activeBranchSessionId ?? workspaceSessionId;
  const branchState = useWorkflowStore((state) => state.branchStates[activeBranchId]);
  const updateNodeConfig = useWorkflowStore((state) => state.updateNodeConfig);
  const executionEvents = useWorkflowStore((state) => state.executionEvents);
  const queryClient = useQueryClient();
  const autoSeededNodeIdsRef = useRef<Set<string>>(new Set());
  const lastPersistedSignatureRef = useRef<string | null>(null);

  const close = () => setSelectedNodeId(null);

  // Close the inspector popup with Escape so it behaves like a standard modal.
  useEffect(() => {
    if (!selectedNodeId) {
      return;
    }
    const onKey = (event: KeyboardEvent) => {
      if (event.key === "Escape") {
        event.preventDefault();
        close();
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [selectedNodeId]);

  const capabilitiesQuery = useQuery({
    queryKey: ["workflow-dispatch-capabilities", sessionId],
    queryFn: () => workflowApi.getCapabilities(sessionId ?? ""),
    enabled: sessionId !== null,
    staleTime: 60_000,
  });

  const sensorsQuery = useQuery({
    queryKey: ["session-sensors", sessionId],
    queryFn: () => uploadsApi.getSensors(sessionId ?? ""),
    enabled: sessionId !== null,
    staleTime: 30_000,
  });

  const selectedNode = branchState.nodes.find((node) => node.id === selectedNodeId) ?? null;
  const nodeEvents = selectedNode
    ? executionEvents.filter((event) => event.node_id === selectedNode.id).slice(-8).reverse()
    : [];

  const selectedCapability =
    selectedNode?.data.kind === "operation" && selectedNode.data.templateId
      ? capabilitiesQuery.data?.capabilities.find((item) => item.template_id === selectedNode.data.templateId) ?? null
      : null;
  const { keys: configuredKeys, parseError: paramsJsonParseError } = selectedNode
    ? configKeysFromNode(selectedNode)
    : { keys: new Set<string>(), parseError: null };

  const parsedParams = selectedNode?.data.kind === "operation" ? parseParamsObject(selectedNode.data.config?.params_json) : { params: {}, parseError: null };
  const mergedParams = useMemo(() => {
    if (!selectedNode || selectedNode.data.kind !== "operation") {
      return {} as Record<string, JsonValue>;
    }
    const merged = { ...parsedParams.params };
    for (const [key, value] of Object.entries(selectedNode.data.config ?? {})) {
      if (key === "params_json") {
        continue;
      }
      if (!(key in merged) && (typeof value === "string" || typeof value === "number" || typeof value === "boolean")) {
        merged[key] = value;
      }
    }
    return merged;
  }, [parsedParams.params, selectedNode]);

  const sensorChoices = useMemo(() => sensorOptions(sensorsQuery.data?.sensors ?? []), [sensorsQuery.data?.sensors]);

  const updateParam = (paramName: string, value: JsonValue | undefined) => {
    if (!selectedNode || selectedNode.data.kind !== "operation") {
      return;
    }
    const next = withParamValue(mergedParams, paramName, value);
    updateNodeConfig(activeBranchId, selectedNode.id, "params_json", JSON.stringify(next, null, 2));
  };

  const validation = validationSummary(selectedCapability, configuredKeys);

  const persistNodeConfigMutation = useMutation({
    mutationFn: (payload: { key: string; value: JsonValue }) =>
      configApi.update(sessionId ?? "", {
        updates: [payload],
      }),
    onSuccess: () => {
      if (sessionId) {
        void queryClient.invalidateQueries({ queryKey: ["runconfig", sessionId] });
      }
    },
  });

  useEffect(() => {
    if (!selectedNode || selectedNode.data.kind !== "operation" || !selectedCapability) {
      return;
    }

    if (!selectedNode.data.fields?.some((field: NodeConfigField) => field.key === "params_json")) {
      return;
    }

    if (autoSeededNodeIdsRef.current.has(selectedNode.id)) {
      return;
    }

    const currentValue = selectedNode.data.config?.params_json;
    if (!isUntouchedParamsJson(currentValue)) {
      autoSeededNodeIdsRef.current.add(selectedNode.id);
      return;
    }

    autoSeededNodeIdsRef.current.add(selectedNode.id);
    updateNodeConfig(activeBranchId, selectedNode.id, "params_json", JSON.stringify(buildSampleParams(selectedCapability), null, 2));
  }, [selectedCapability, selectedNode, updateNodeConfig]);

  useEffect(() => {
    if (!sessionId || !selectedNode || selectedNode.data.kind !== "operation") {
      return;
    }

    const payload = {
      template_id: selectedNode.data.templateId ?? null,
      label: selectedNode.data.label,
      config: selectedNode.data.config ?? {},
    } satisfies JsonValue;

    const key = buildRunconfigUpdateKey(activeBranchId, selectedNode.id);
    const signature = JSON.stringify({ key, payload });
    if (lastPersistedSignatureRef.current === signature) {
      return;
    }

    const timeoutId = window.setTimeout(() => {
      lastPersistedSignatureRef.current = signature;
      persistNodeConfigMutation.mutate({ key, value: payload });
    }, 350);

    return () => window.clearTimeout(timeoutId);
  }, [activeBranchId, persistNodeConfigMutation, selectedNode, sessionId]);

  const capabilityErrorMessage =
    capabilitiesQuery.error instanceof ApiError
      ? capabilitiesQuery.error.message
      : capabilitiesQuery.error instanceof Error
        ? capabilitiesQuery.error.message
        : null;

  if (!selectedNode) {
    return null;
  }

  return (
    <div
      className="workflow-inspector-modal-backdrop"
      role="presentation"
      onClick={(event) => {
        if (event.target === event.currentTarget) {
          close();
        }
      }}
    >
      <div
        className="workflow-inspector-modal"
        role="dialog"
        aria-modal="true"
        aria-labelledby="workflow-inspector-modal-title"
      >
        <section className="workflow-panel-card workflow-inspector-card">
          <div className="workflow-panel-header">
            <div>
              <span className="eyebrow">Inspector</span>
              <h2 id="workflow-inspector-modal-title">{selectedNode.data.label}</h2>
            </div>
            <div className="workflow-inspector-modal-header-actions">
              <span className="workflow-phase-chip">Branch {activeBranchId}</span>
              <button
                type="button"
                className="workflow-inspector-modal-close"
                aria-label="Close inspector"
                onClick={close}
              >
                ×
              </button>
            </div>
          </div>
          <div className="workflow-inspector-fields">
            <p className="workflow-inspector-copy">{selectedNode.data.description}</p>
            {selectedNode.data.kind === "operation" && selectedNode.data.fields?.length ? (
              <div className="workflow-field-grid">
                {selectedNode.data.fields.map((field: NodeConfigField) => {
                  if (field.key === "params_json") {
                    return null;
                  }
                  const currentValue = selectedNode.data.config?.[field.key] ?? field.defaultValue;

                  return (
                    <label key={field.key} className="workflow-form-field">
                      <span>{field.label}</span>
                      {field.type === "select" ? (
                        <select
                          value={String(currentValue)}
                          onChange={(event) => updateNodeConfig(activeBranchId, selectedNode.id, field.key, event.target.value)}
                        >
                          {field.options?.map((option: { label: string; value: string }) => (
                            <option key={option.value} value={option.value}>
                              {option.label}
                            </option>
                          ))}
                        </select>
                      ) : field.type === "boolean" ? (
                        <button
                          type="button"
                          className={`workflow-toggle ${currentValue ? "workflow-toggle-on" : ""}`}
                          onClick={() => updateNodeConfig(activeBranchId, selectedNode.id, field.key, !Boolean(currentValue))}
                        >
                          {renderValue(Boolean(currentValue))}
                        </button>
                      ) : field.key === "params_json" ? (
                        <textarea
                          rows={8}
                          value={String(currentValue)}
                          placeholder={field.placeholder}
                          spellCheck={false}
                          onChange={(event) => updateNodeConfig(activeBranchId, selectedNode.id, field.key, event.target.value)}
                        />
                      ) : (
                        <input
                          type={field.type === "number" ? "number" : "text"}
                          value={String(currentValue)}
                          placeholder={field.placeholder}
                          onChange={(event) =>
                            updateNodeConfig(
                              activeBranchId,
                              selectedNode.id,
                              field.key,
                              field.type === "number" ? Number(event.target.value) : event.target.value,
                            )
                          }
                        />
                      )}
                    </label>
                  );
                })}
              </div>
            ) : (
              <p className="muted-text">This node does not expose editable settings in the foundation build.</p>
            )}

            {selectedNode.data.kind === "operation" && selectedCapability ? (
              <div className="workflow-dispatch-hints">
                <h3>Parameters</h3>
                <p className="muted-text">Fill required fields first. Optional fields can be left blank.</p>
                {sensorsQuery.isLoading ? <p className="muted-text">Loading sensor choices...</p> : null}
                {sensorsQuery.error ? (
                  <p className="workflow-error-text">Sensor list unavailable. You can still type values manually.</p>
                ) : null}

                <div className="workflow-field-grid">
                  {[...selectedCapability.required_params, ...selectedCapability.optional_params].map((paramName) => {
                    const required = selectedCapability.required_params.includes(paramName);
                    const currentValue = valueForParam(mergedParams, paramName);
                    const inputKind = inferInputKind(paramName);
                    const isDirectionParam = paramName.toLowerCase() === "direction_sensor";
                    const options =
                      inputKind === "sensor-multi"
                        ? sensorChoices.speed
                        : inputKind === "sensor-single"
                          ? isDirectionParam
                            ? sensorChoices.direction
                            : sensorChoices.all
                          : [];

                    return (
                      <label key={paramName} className="workflow-form-field">
                        <span>
                          {humanizeParamName(paramName)}
                          <span className={`workflow-validation-badge ${required ? "workflow-validation-badge-error" : "workflow-validation-badge-muted"}`}>
                            {required ? "Required" : "Optional"}
                          </span>
                        </span>

                        {paramName.toLowerCase().includes("file") || paramName.toLowerCase().includes("path") ? (
                          <small className="muted-text">File name or absolute path</small>
                        ) : null}

                        {inputKind === "sensor-single" ? (
                          <select
                            value={typeof currentValue === "string" ? currentValue : ""}
                            onChange={(event) => updateParam(paramName, event.target.value)}
                          >
                            <option value="">Select sensor...</option>
                            {options.map((option) => (
                              <option key={option} value={option}>
                                {option}
                              </option>
                            ))}
                          </select>
                        ) : null}

                        {inputKind === "sensor-multi" ? (
                          <select
                            multiple
                            size={Math.min(8, Math.max(3, options.length || 3))}
                            value={asStringArray(currentValue)}
                            onChange={(event) => {
                              const values = Array.from(event.target.selectedOptions).map((item) => item.value);
                              updateParam(paramName, values);
                            }}
                          >
                            {options.map((option) => (
                              <option key={option} value={option}>
                                {option}
                              </option>
                            ))}
                          </select>
                        ) : null}

                        {inputKind === "boolean" ? (
                          <button
                            type="button"
                            className={`workflow-toggle ${Boolean(currentValue) ? "workflow-toggle-on" : ""}`}
                            onClick={() => updateParam(paramName, !Boolean(currentValue))}
                          >
                            {renderValue(Boolean(currentValue))}
                          </button>
                        ) : null}

                        {inputKind === "number" ? (
                          <input
                            type="number"
                            value={typeof currentValue === "number" ? String(currentValue) : ""}
                            onChange={(event) => {
                              const raw = event.target.value;
                              updateParam(paramName, raw === "" ? undefined : Number(raw));
                            }}
                          />
                        ) : null}

                        {inputKind === "date" ? (
                          <input
                            type="date"
                            value={typeof currentValue === "string" ? currentValue : ""}
                            onChange={(event) => updateParam(paramName, event.target.value)}
                          />
                        ) : null}

                        {inputKind === "json" ? (
                          <textarea
                            rows={5}
                            value={typeof currentValue === "string" ? currentValue : JSON.stringify(currentValue ?? {}, null, 2)}
                            spellCheck={false}
                            onChange={(event) => {
                              const text = event.target.value;
                              const decoded = parseLooseJson(text);
                              if (decoded.ok) {
                                updateParam(paramName, decoded.value as JsonValue);
                              } else {
                                updateParam(paramName, text);
                              }
                            }}
                          />
                        ) : null}

                        {inputKind === "text" ? (
                          <input
                            type="text"
                            value={typeof currentValue === "string" || typeof currentValue === "number" ? String(currentValue) : ""}
                            onChange={(event) => updateParam(paramName, event.target.value)}
                          />
                        ) : null}
                      </label>
                    );
                  })}
                </div>
              </div>
            ) : null}

            {selectedNode.data.kind === "operation" ? (
              <div className="workflow-dispatch-hints">
                <h3>Dispatch parameters</h3>
                {paramsJsonParseError || parsedParams.parseError ? (
                  <p className="workflow-error-text">
                    Parameters JSON is invalid: {paramsJsonParseError ?? parsedParams.parseError}. Tip: on Windows, escape backslashes
                    (e.g. <code>{"D:\\\\path\\\\file.csv"}</code>) or use forward slashes.
                  </p>
                ) : null}
                {capabilitiesQuery.isLoading ? <p className="muted-text">Loading backend signature hints...</p> : null}
                {capabilityErrorMessage ? <p className="workflow-error-text">{capabilityErrorMessage}</p> : null}
                {selectedNode.data.templateId ? (
                  <p className="workflow-dispatch-template">Template: {selectedNode.data.templateId}</p>
                ) : (
                  <p className="muted-text">This operation node is missing a template identifier.</p>
                )}
                {selectedCapability ? (
                  <div className="workflow-dispatch-grid">
                    <div>
                      <strong>Required</strong>
                      <p>{selectedCapability.required_params.length ? selectedCapability.required_params.join(", ") : "None"}</p>
                    </div>
                    <div>
                      <strong>Optional</strong>
                      <p>{selectedCapability.optional_params.length ? selectedCapability.optional_params.join(", ") : "None"}</p>
                    </div>
                  </div>
                ) : null}
                {selectedCapability ? (
                  <div className="workflow-dispatch-validation">
                    <div className="workflow-dispatch-badges">
                      <span
                        className={`workflow-validation-badge ${validation.missing.length === 0 ? "workflow-validation-badge-ok" : "workflow-validation-badge-error"}`}
                      >
                        {validation.missing.length === 0
                          ? "Ready for dispatch"
                          : `${validation.missing.length} required param${validation.missing.length === 1 ? "" : "s"} missing`}
                      </span>
                      <span className="workflow-validation-badge workflow-validation-badge-muted">
                        {configuredKeys.size} configured key{configuredKeys.size === 1 ? "" : "s"}
                      </span>
                    </div>
                    <div className="workflow-param-checklist">
                      {selectedCapability.required_params.map((required) => {
                        const present = requiredParamStatus(required, configuredKeys);
                        return (
                          <div key={required} className="workflow-param-check-item">
                            <span>{required}</span>
                            <span
                              className={`workflow-validation-badge ${present ? "workflow-validation-badge-ok" : "workflow-validation-badge-error"}`}
                            >
                              {present ? "Set" : "Missing"}
                            </span>
                          </div>
                        );
                      })}
                    </div>
                  </div>
                ) : null}
                {!capabilitiesQuery.isLoading && !capabilityErrorMessage && selectedNode.data.templateId && !selectedCapability ? (
                  <p className="muted-text">No dispatch hints found for this template yet.</p>
                ) : null}
              </div>
            ) : null}

            <div className="workflow-execution-log">
              <h3>Execution log</h3>
              {nodeEvents.length === 0 ? <p className="muted-text">No run events yet for this node.</p> : null}
              {nodeEvents.map((event, index) => (
                <p key={`${event.run_id}-${event.event_type}-${index}`} className="workflow-execution-log-entry">
                  <strong>{event.event_type}</strong>
                  {event.message ? ` - ${event.message}` : ""}
                </p>
              ))}
            </div>
          </div>
        </section>
      </div>
    </div>
  );
}