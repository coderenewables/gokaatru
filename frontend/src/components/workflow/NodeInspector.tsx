import { useEffect, useRef, type ReactNode } from "react";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { ApiError, configApi, workflowApi } from "../../lib/api";
import type { NodeConfigField } from "../../lib/nodeRegistry";
import type { JsonValue, WorkflowDispatchCapability } from "../../lib/types";
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

function configKeysFromNode(node: WorkflowNode): Set<string> {
  const keys = new Set<string>();
  if (node.data.kind !== "operation" || !node.data.config) {
    return keys;
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
  if (typeof rawParams === "string") {
    try {
      const parsed = JSON.parse(rawParams);
      if (parsed && typeof parsed === "object" && !Array.isArray(parsed)) {
        for (const [key, value] of Object.entries(parsed)) {
          if (hasValue(value)) {
            keys.add(key);
          }
        }
      }
    } catch {
      // Ignore malformed params_json while still showing inspector state.
    }
  }

  return keys;
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

export function NodeInspector({ fallback }: { fallback: ReactNode }) {
  const sessionId = useWorkspaceStore((state) => state.sessionId);
  const activeBranchId = useWorkflowStore((state) => state.activeBranchId);
  const branchState = useWorkflowStore((state) => state.branchStates[state.activeBranchId]);
  const selectedNodeId = useWorkflowStore((state) => state.selectedNodeId);
  const updateNodeConfig = useWorkflowStore((state) => state.updateNodeConfig);
  const executionEvents = useWorkflowStore((state) => state.executionEvents);
  const queryClient = useQueryClient();
  const autoSeededNodeIdsRef = useRef<Set<string>>(new Set());
  const lastPersistedSignatureRef = useRef<string | null>(null);

  const capabilitiesQuery = useQuery({
    queryKey: ["workflow-dispatch-capabilities", sessionId],
    queryFn: () => workflowApi.getCapabilities(sessionId ?? ""),
    enabled: sessionId !== null,
    staleTime: 60_000,
  });

  const selectedNode = branchState.nodes.find((node) => node.id === selectedNodeId) ?? null;
  const nodeEvents = selectedNode
    ? executionEvents.filter((event) => event.node_id === selectedNode.id).slice(-8).reverse()
    : [];

  const selectedCapability =
    selectedNode?.data.kind === "operation" && selectedNode.data.templateId
      ? capabilitiesQuery.data?.capabilities.find((item) => item.template_id === selectedNode.data.templateId) ?? null
      : null;
  const configuredKeys = selectedNode ? configKeysFromNode(selectedNode) : new Set<string>();
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
    updateNodeConfig(selectedNode.id, "params_json", JSON.stringify(buildSampleParams(selectedCapability), null, 2));
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

  return (
    <div className="workflow-inspector-stack">
      <section className="workflow-panel-card workflow-inspector-card">
        <div className="workflow-panel-header">
          <div>
            <span className="eyebrow">Inspector</span>
            <h2>{selectedNode?.data.label ?? "Select a node"}</h2>
          </div>
          <span className="workflow-phase-chip">Branch {activeBranchId}</span>
        </div>
        {selectedNode ? (
          <div className="workflow-inspector-fields">
            <p className="workflow-inspector-copy">{selectedNode.data.description}</p>
            {selectedNode.data.kind === "operation" && selectedNode.data.fields?.length ? (
              <div className="workflow-field-grid">
                {selectedNode.data.fields.map((field: NodeConfigField) => {
                  const currentValue = selectedNode.data.config?.[field.key] ?? field.defaultValue;

                  return (
                    <label key={field.key} className="workflow-form-field">
                      <span>{field.label}</span>
                      {field.type === "select" ? (
                        <select
                          value={String(currentValue)}
                          onChange={(event) => updateNodeConfig(selectedNode.id, field.key, event.target.value)}
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
                          onClick={() => updateNodeConfig(selectedNode.id, field.key, !Boolean(currentValue))}
                        >
                          {renderValue(Boolean(currentValue))}
                        </button>
                      ) : field.key === "params_json" ? (
                        <textarea
                          rows={8}
                          value={String(currentValue)}
                          placeholder={field.placeholder}
                          spellCheck={false}
                          onChange={(event) => updateNodeConfig(selectedNode.id, field.key, event.target.value)}
                        />
                      ) : (
                        <input
                          type={field.type === "number" ? "number" : "text"}
                          value={String(currentValue)}
                          placeholder={field.placeholder}
                          onChange={(event) =>
                            updateNodeConfig(
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

            {selectedNode.data.kind === "operation" ? (
              <div className="workflow-dispatch-hints">
                <h3>Dispatch parameters</h3>
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
        ) : (
          <p className="muted-text">Click a node on the canvas to inspect its configuration and summary.</p>
        )}
      </section>

      <section className="workflow-panel-card workflow-detail-card">
        <div className="workflow-panel-header">
          <div>
            <span className="eyebrow">Detail route</span>
            <h2>Existing page content</h2>
          </div>
        </div>
        <div className="workflow-detail-content">{fallback}</div>
      </section>
    </div>
  );
}