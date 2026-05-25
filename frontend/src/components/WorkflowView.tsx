import { useMemo, useState } from "react";
import { addEdge, applyEdgeChanges, applyNodeChanges, Background, Controls, MiniMap, ReactFlow, type Connection, type EdgeChange, type NodeChange } from "@xyflow/react";
import "@xyflow/react/dist/style.css";

import type { WorkflowCanvasEdge, WorkflowCanvasNode } from "../lib/workflow";
import { useWorkspaceStore } from "../store/useWorkspaceStore";
import type { WindAnalysisConfig } from "../types/analysis";

type ShearFormState = {
  heightSensors: string;
  aggregation: WindAnalysisConfig["shear"]["aggregation"];
  hubHeightM: number;
  model: WindAnalysisConfig["shear"]["method"];
};

type LtcFormState = {
  algorithm: WindAnalysisConfig["ltc"]["algorithms"][number];
  shortColumn: string;
  longColumn: string;
  shortDirectionColumn: string;
  longDirectionColumn: string;
  measuredColumn: string;
  mcpRSquared: number;
  concurrentHours: number;
};

export function WorkflowView() {
  const workflowNodes = useWorkspaceStore((state) => state.workflowNodes);
  const workflowEdges = useWorkspaceStore((state) => state.workflowEdges);
  const capabilities = useWorkspaceStore((state) => state.capabilities);
  const workflowSnapshots = useWorkspaceStore((state) => state.workflowSnapshots);
  const workflowStatus = useWorkspaceStore((state) => state.workflowStatus);
  const sensors = useWorkspaceStore((state) => state.sensors);
  const lastOperation = useWorkspaceStore((state) => state.lastOperation);
  const activity = useWorkspaceStore((state) => state.activity);
  const brighthubReanalysis = useWorkspaceStore((state) => state.brighthubReanalysis);
  const setWorkflowGraph = useWorkspaceStore((state) => state.setWorkflowGraph);
  const updateWorkflowNode = useWorkspaceStore((state) => state.updateWorkflowNode);
  const executeWorkflow = useWorkspaceStore((state) => state.executeWorkflow);
  const saveSnapshot = useWorkspaceStore((state) => state.saveSnapshot);
  const loadSnapshot = useWorkspaceStore((state) => state.loadSnapshot);
  const forkBranch = useWorkspaceStore((state) => state.forkBranch);
  const fetchBrightHubReanalysisNodes = useWorkspaceStore((state) => state.fetchBrightHubReanalysisNodes);
  const downloadBrightHubReanalysis = useWorkspaceStore((state) => state.downloadBrightHubReanalysis);
  const invokeSessionOperation = useWorkspaceStore((state) => state.invokeSessionOperation);
  const config = useWorkspaceStore((state) => state.config);

  const [selectedNodeId, setSelectedNodeId] = useState<string | null>(workflowNodes[0]?.id ?? null);
  const [snapshotName, setSnapshotName] = useState(config.workflow.snapshotName);
  const [branchName, setBranchName] = useState("Run 2");
  const [cleaningForm, setCleaningForm] = useState({ ruleType: "range_filter", sensor: "", params: "{}", startDate: "", endDate: "" });
  const [shearForm, setShearForm] = useState<ShearFormState>({ heightSensors: "", aggregation: config.shear.aggregation, hubHeightM: config.site.hubHeightM, model: config.shear.method });
  const [era5Form, setEra5Form] = useState({
    latitude: config.reanalysis.searchLatitude,
    longitude: config.reanalysis.searchLongitude,
    startDate: config.reanalysis.startDate,
    endDate: config.reanalysis.endDate,
  });
  const [reanalysisMode, setReanalysisMode] = useState<"session-era5" | "brighthub" | "earthdatahub">("session-era5");
  const [reanalysisDataset, setReanalysisDataset] = useState<"ERA5" | "MERRA-2">("ERA5");
  const [ltcForm, setLtcForm] = useState<LtcFormState>({
    algorithm: config.ltc.algorithms[0] ?? "speedsort",
    shortColumn: config.ltc.shortColumn,
    longColumn: config.ltc.longColumn,
    shortDirectionColumn: config.ltc.shortDirectionColumn,
    longDirectionColumn: config.ltc.longDirectionColumn,
    measuredColumn: config.ltc.measuredColumn,
    mcpRSquared: config.ltc.uncertainty.mcpRSquared,
    concurrentHours: config.ltc.uncertainty.concurrentHours,
  });

  const selectedNode = useMemo(
    () => workflowNodes.find((node) => node.id === selectedNodeId) ?? workflowNodes[0] ?? null,
    [selectedNodeId, workflowNodes],
  );
  const selectedCapability = useMemo(
    () => capabilities.find((capability) => capability.template_id === selectedNode?.data.templateId),
    [capabilities, selectedNode?.data.templateId],
  );

  const handleNodeChanges = (changes: NodeChange<WorkflowCanvasNode>[]) => {
    setWorkflowGraph(applyNodeChanges<WorkflowCanvasNode>(changes, workflowNodes), workflowEdges);
  };

  const handleEdgeChanges = (changes: EdgeChange<WorkflowCanvasEdge>[]) => {
    setWorkflowGraph(workflowNodes, applyEdgeChanges<WorkflowCanvasEdge>(changes, workflowEdges));
  };

  const handleConnect = (connection: Connection) => {
    setWorkflowGraph(workflowNodes, addEdge<WorkflowCanvasEdge>(connection, workflowEdges));
  };

  return (
    <div className="workflow-layout">
      <section className="panel workflow-actions-panel">
        <div className="panel-header">
          <div>
            <p className="panel-kicker">Phase 2</p>
            <h2>Linear wizard actions</h2>
          </div>
        </div>

        <div className="step-list">
          <article className="step-card">
            <h3>Cleaning</h3>
            <label>
              <span>Rule type</span>
              <select onChange={(event) => setCleaningForm((state) => ({ ...state, ruleType: event.target.value }))} value={cleaningForm.ruleType}>
                <option value="range_filter">Range filter</option>
                <option value="outlier_filter">Outlier filter</option>
                <option value="icing_filter">Icing filter</option>
                <option value="time_window">Time window</option>
                <option value="custom">Custom</option>
              </select>
            </label>
            <label>
              <span>Sensor</span>
              <input onChange={(event) => setCleaningForm((state) => ({ ...state, sensor: event.target.value }))} type="text" value={cleaningForm.sensor} />
            </label>
            <label>
              <span>Params JSON</span>
              <textarea onChange={(event) => setCleaningForm((state) => ({ ...state, params: event.target.value }))} rows={3} value={cleaningForm.params} />
            </label>
            <button
              className="primary-button"
              onClick={() => {
                let parsedParams: Record<string, unknown> = {};
                try {
                  parsedParams = JSON.parse(cleaningForm.params) as Record<string, unknown>;
                } catch {
                  parsedParams = {};
                }
                void invokeSessionOperation("Apply cleaning rule", "POST", "/cleaning/apply", {
                  rule_type: cleaningForm.ruleType,
                  sensor: cleaningForm.sensor,
                  params: parsedParams,
                  start_date: cleaningForm.startDate,
                  end_date: cleaningForm.endDate,
                });
              }}
              type="button"
            >
              Apply cleaning rule
            </button>
          </article>

          <article className="step-card">
            <h3>Shear and hub height</h3>
            <label>
              <span>Height sensors</span>
              <input onChange={(event) => setShearForm((state) => ({ ...state, heightSensors: event.target.value }))} type="text" value={shearForm.heightSensors} />
            </label>
            <label>
              <span>Aggregation</span>
              <select onChange={(event) => setShearForm((state) => ({ ...state, aggregation: event.target.value as ShearFormState["aggregation"] }))} value={shearForm.aggregation}>
                <option value="mean">Mean</option>
                <option value="median">Median</option>
                <option value="p90">P90</option>
              </select>
            </label>
            <div className="button-row">
              <button className="secondary-button" onClick={() => void invokeSessionOperation("Calculate shear", "POST", "/shear/calculate", { height_sensors: shearForm.heightSensors })} type="button">
                Calculate shear
              </button>
              <button className="secondary-button" onClick={() => void invokeSessionOperation("Build shear table", "POST", "/shear/table", { aggregation: shearForm.aggregation })} type="button">
                Build table
              </button>
              <button className="primary-button" onClick={() => void invokeSessionOperation("Extrapolate hub height", "POST", "/extrapolation/hub", { hub_height_m: shearForm.hubHeightM, shear_model: shearForm.model })} type="button">
                Extrapolate hub
              </button>
            </div>
          </article>

          <article className="step-card">
            <h3>Reanalysis</h3>
            <label>
              <span>Source</span>
              <select onChange={(event) => setReanalysisMode(event.target.value as "session-era5" | "brighthub" | "earthdatahub")} value={reanalysisMode}>
                <option value="session-era5">Built-in ERA5</option>
                <option value="brighthub">BrightHub</option>
                <option value="earthdatahub">EarthDataHub ERA5</option>
              </select>
            </label>
            <label>
              <span>Dataset</span>
              <select onChange={(event) => setReanalysisDataset(event.target.value as "ERA5" | "MERRA-2")} value={reanalysisDataset}>
                <option value="ERA5">ERA5</option>
                <option value="MERRA-2">MERRA-2</option>
              </select>
            </label>
            <label>
              <span>Latitude</span>
              <input onChange={(event) => setEra5Form((state) => ({ ...state, latitude: Number(event.target.value) }))} type="number" value={era5Form.latitude} />
            </label>
            <label>
              <span>Longitude</span>
              <input onChange={(event) => setEra5Form((state) => ({ ...state, longitude: Number(event.target.value) }))} type="number" value={era5Form.longitude} />
            </label>
            <label>
              <span>Start date</span>
              <input onChange={(event) => setEra5Form((state) => ({ ...state, startDate: event.target.value }))} type="date" value={era5Form.startDate} />
            </label>
            <label>
              <span>End date</span>
              <input onChange={(event) => setEra5Form((state) => ({ ...state, endDate: event.target.value }))} type="date" value={era5Form.endDate} />
            </label>
            <div className="button-row">
              <button
                className="secondary-button"
                onClick={() =>
                  reanalysisMode === "session-era5"
                    ? void invokeSessionOperation("Find ERA5 nodes", "POST", "/era5/nodes", { latitude: era5Form.latitude, longitude: era5Form.longitude })
                    : void fetchBrightHubReanalysisNodes({ latitude: era5Form.latitude, longitude: era5Form.longitude })
                }
                type="button"
              >
                Find nodes
              </button>
              {reanalysisMode === "session-era5" ? (
                <>
                  <button className="secondary-button" onClick={() => void invokeSessionOperation("Extract ERA5", "POST", "/era5/extract", { latitude: era5Form.latitude, longitude: era5Form.longitude, start_date: era5Form.startDate, end_date: era5Form.endDate })} type="button">
                    Extract
                  </button>
                  <button className="primary-button" onClick={() => void invokeSessionOperation("Interpolate ERA5", "POST", "/era5/interpolate")} type="button">
                    Interpolate
                  </button>
                </>
              ) : (
                <>
                  <button
                    className="secondary-button"
                    onClick={() =>
                      void downloadBrightHubReanalysis({
                        dataset: reanalysisDataset,
                        source: reanalysisMode === "earthdatahub" ? "earthdatahub" : "brighthub",
                        useNodes: reanalysisDataset === "MERRA-2" ? "merra2" : "era5",
                      })
                    }
                    type="button"
                  >
                    Download data
                  </button>
                  {reanalysisDataset === "ERA5" ? (
                    <button className="primary-button" onClick={() => void invokeSessionOperation("Interpolate ERA5", "POST", "/era5/interpolate")} type="button">
                      Interpolate site ERA5
                    </button>
                  ) : null}
                </>
              )}
            </div>
            <p className="muted-text">
              {reanalysisMode === "session-era5"
                ? "Use the built-in ERA5 workflow for direct node search, extraction, and interpolation."
                : reanalysisDataset === "MERRA-2"
                  ? "MERRA-2 downloads are stored in the session and picked up later by hub-height extrapolation after the shear table is ready."
                  : "BrightHub and EarthDataHub can supply ERA5 nodes for the same interpolation flow used by the standard tools."}
            </p>
            {brighthubReanalysis ? (
              <p className="muted-text">
                BrightHub node cache: {brighthubReanalysis.era5_nodes.length} ERA5 node(s), {brighthubReanalysis.merra2_nodes.length} MERRA-2 node(s).
              </p>
            ) : null}
          </article>

          <article className="step-card">
            <h3>LTC and uncertainty</h3>
            <label>
              <span>Algorithm</span>
              <select onChange={(event) => setLtcForm((state) => ({ ...state, algorithm: event.target.value as LtcFormState["algorithm"] }))} value={ltcForm.algorithm}>
                <option value="speedsort">SpeedSort</option>
                <option value="linear_least_squares">Linear least squares</option>
                <option value="total_least_squares">Total least squares</option>
                <option value="variance_ratio">Variance ratio</option>
                <option value="xgboost">XGBoost</option>
              </select>
            </label>
            <label>
              <span>Short column</span>
              <input onChange={(event) => setLtcForm((state) => ({ ...state, shortColumn: event.target.value }))} type="text" value={ltcForm.shortColumn} />
            </label>
            <label>
              <span>Long column</span>
              <input onChange={(event) => setLtcForm((state) => ({ ...state, longColumn: event.target.value }))} type="text" value={ltcForm.longColumn} />
            </label>
            <div className="button-row">
              <button className="secondary-button" onClick={() => void invokeSessionOperation(`Run ${ltcForm.algorithm}`, "POST", `/ltc/${ltcForm.algorithm}`, { short_col: ltcForm.shortColumn, long_col: ltcForm.longColumn, short_dir_col: ltcForm.shortDirectionColumn, long_dir_col: ltcForm.longDirectionColumn })} type="button">
                Run LTC
              </button>
              <button className="secondary-button" onClick={() => void invokeSessionOperation("Run ensemble", "POST", "/ensemble", { measured_col: ltcForm.measuredColumn })} type="button">
                Run ensemble
              </button>
              <button
                className="primary-button"
                onClick={() =>
                  void invokeSessionOperation("Calculate uncertainty", "POST", "/uncertainty", {
                    measurement_uncertainty_pct: config.ltc.uncertainty.measurementUncertaintyPct,
                    measurement_height_m: config.ltc.uncertainty.measurementHeightM,
                    hub_height_m: config.ltc.uncertainty.hubHeightM,
                    shear_method: config.ltc.uncertainty.shearMethod,
                    mcp_r_squared: ltcForm.mcpRSquared,
                    concurrent_hours: ltcForm.concurrentHours,
                    algorithm: ltcForm.algorithm,
                    iav_pct: config.ltc.uncertainty.iavPct,
                    shear_std: config.ltc.uncertainty.shearStd,
                    is_interpolation: config.ltc.uncertainty.isInterpolation,
                  })
                }
                type="button"
              >
                Uncertainty
              </button>
            </div>
          </article>
        </div>
      </section>

      <section className="panel workflow-canvas-panel">
        <div className="panel-header">
          <div>
            <p className="panel-kicker">Phase 2</p>
            <h2>Workflow canvas</h2>
          </div>
          <div className="button-row">
            <button className="secondary-button" onClick={() => void executeWorkflow("manual")} type="button">
              Run next node
            </button>
            <button className="primary-button" onClick={() => void executeWorkflow("auto")} type="button">
              Run workflow
            </button>
          </div>
        </div>

        <div className="workflow-canvas-shell">
          <ReactFlow<WorkflowCanvasNode, WorkflowCanvasEdge>
            edges={workflowEdges}
            fitView
            nodes={workflowNodes}
            onConnect={handleConnect}
            onEdgesChange={handleEdgeChanges}
            onNodeClick={(_, node) => setSelectedNodeId(node.id)}
            onNodesChange={handleNodeChanges}
          >
            <Background gap={18} />
            <MiniMap />
            <Controls />
          </ReactFlow>
        </div>
      </section>

      <section className="panel workflow-side-panel">
        <div className="panel-header">
          <div>
            <p className="panel-kicker">Node inspector</p>
            <h2>{selectedNode?.data.label ?? "Select a node"}</h2>
          </div>
        </div>

        {selectedNode ? (
          <div className="node-inspector">
            <label>
              <span>Template id</span>
              <select
                onChange={(event) =>
                  updateWorkflowNode(selectedNode.id, (node) => ({
                    ...node,
                    data: {
                      ...node.data,
                      templateId: event.target.value,
                      requiredParams: capabilities.find((capability) => capability.template_id === event.target.value)?.required_params ?? [],
                      optionalParams: capabilities.find((capability) => capability.template_id === event.target.value)?.optional_params ?? [],
                    },
                  }))
                }
                value={selectedNode.data.templateId}
              >
                <option value="">Choose capability</option>
                {capabilities.map((capability) => (
                  <option key={capability.template_id} value={capability.template_id}>
                    {capability.template_id}
                  </option>
                ))}
              </select>
            </label>
            <p className="muted-text">{selectedNode.data.summary}</p>
            <label>
              <span>Params JSON</span>
              <textarea
                onChange={(event) =>
                  updateWorkflowNode(selectedNode.id, (node) => ({
                    ...node,
                    data: {
                      ...node.data,
                      paramsJson: event.target.value,
                    },
                  }))
                }
                rows={12}
                value={selectedNode.data.paramsJson}
              />
            </label>
            {selectedCapability ? (
              <div className="capability-hint">
                <strong>Required</strong>
                <p>{selectedCapability.required_params.join(", ") || "None"}</p>
                <strong>Optional</strong>
                <p>{selectedCapability.optional_params.join(", ") || "None"}</p>
              </div>
            ) : null}

            <label>
              <span>Snapshot name</span>
              <input onChange={(event) => setSnapshotName(event.target.value)} type="text" value={snapshotName} />
            </label>
            <div className="button-row">
              <button className="secondary-button" onClick={() => void saveSnapshot(snapshotName)} type="button">
                Save snapshot
              </button>
              <button className="secondary-button" onClick={() => void forkBranch(branchName, selectedNode.id)} type="button">
                Fork branch
              </button>
            </div>

            <label>
              <span>Branch name</span>
              <input onChange={(event) => setBranchName(event.target.value)} type="text" value={branchName} />
            </label>
          </div>
        ) : (
          <p className="muted-text">Select a workflow node to edit its template and parameters.</p>
        )}

        <div className="snapshot-list">
          <h3>Saved snapshots</h3>
          {workflowSnapshots.length === 0 ? <p className="muted-text">No snapshots saved yet.</p> : null}
          {workflowSnapshots.map((snapshot) => (
            <button className="snapshot-button" key={snapshot.name} onClick={() => void loadSnapshot(snapshot.name)} type="button">
              <span>{snapshot.name}</span>
              <small>{new Date(snapshot.saved_at).toLocaleString()}</small>
            </button>
          ))}
        </div>

        <div className="status-stack">
          <h3>Workflow status</h3>
          <pre>{JSON.stringify(workflowStatus, null, 2)}</pre>
          <h3>Last operation</h3>
          <pre>{JSON.stringify(lastOperation, null, 2)}</pre>
          <h3>Recent activity</h3>
          <ul className="activity-list">
            {activity.slice(0, 6).map((entry) => (
              <li key={entry.id}>
                <strong>{entry.label}</strong>
                <span>{entry.detail}</span>
              </li>
            ))}
          </ul>
          <h3>Sensor names</h3>
          <p className="muted-text">{sensors.map((sensor) => String(sensor.name ?? sensor.sensor_name ?? sensor.label ?? "")).filter(Boolean).join(", ") || "No sensors loaded"}</p>
        </div>
      </section>
    </div>
  );
}