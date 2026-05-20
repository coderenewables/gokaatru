import { useEffect, useMemo, useState } from "react";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { ApiError, datasetsApi } from "../../lib/api";
import { useWorkflowUiStore } from "../../stores/workflowUiStore";
import { useWorkflowStore } from "../../stores/workflowStore";

function toErrorMessage(error: unknown): string {
  if (error instanceof ApiError) {
    return error.message;
  }
  if (error instanceof Error) {
    return error.message;
  }
  return "Unexpected dataset pool error";
}

function summarizeRange(start: string, end: string): string {
  const from = start.slice(0, 10);
  const to = end.slice(0, 10);
  if (from && to) {
    return `${from} to ${to}`;
  }
  return "Unknown period";
}

export function DatasetPool() {
  const activeBranchId = useWorkflowUiStore((state) => state.activeBranchId);
  const setSelectedNodeId = useWorkflowUiStore((state) => state.setSelectedNodeId);
  const sessionId = useWorkflowStore((state) => {
    const activeBranch = state.branches.find((branch) => branch.id === activeBranchId);
    return activeBranch?.sessionId ?? null;
  });
  const queryClient = useQueryClient();
  const [datasetName, setDatasetName] = useState("");
  const [timeseriesFile, setTimeseriesFile] = useState<File | null>(null);
  const [datamodelFile, setDatamodelFile] = useState<File | null>(null);
  const [uploadProgress, setUploadProgress] = useState<number>(0);
  const [fileInputRevision, setFileInputRevision] = useState(0);
  const [previewDatasetId, setPreviewDatasetId] = useState<string | null>(null);
  const [pendingDeleteDatasetId, setPendingDeleteDatasetId] = useState<string | null>(null);
  const [toastMessage, setToastMessage] = useState<string | null>(null);
  const [latestError, setLatestError] = useState<string | null>(null);

  const datasets = useWorkflowStore((state) => state.datasets);
  const setDatasets = useWorkflowStore((state) => state.setDatasets);
  const upsertDataset = useWorkflowStore((state) => state.upsertDataset);
  const removeDataset = useWorkflowStore((state) => state.removeDataset);
  const addDatasetNode = useWorkflowStore((state) => state.addDatasetNode);

  const datasetsQuery = useQuery({
    queryKey: ["dataset-pool"],
    queryFn: async () => (await datasetsApi.list()).datasets,
    staleTime: 15_000,
  });

  useEffect(() => {
    if (datasetsQuery.data) {
      setDatasets(datasetsQuery.data);
    }
  }, [datasetsQuery.data, setDatasets]);

  const previewQuery = useQuery({
    queryKey: ["dataset-preview", previewDatasetId],
    queryFn: () => datasetsApi.getPreview(previewDatasetId ?? "", 20),
    enabled: previewDatasetId !== null,
    staleTime: 30_000,
  });

  useEffect(() => {
    if (!toastMessage) {
      return;
    }
    const timeoutId = window.setTimeout(() => setToastMessage(null), 3500);
    return () => window.clearTimeout(timeoutId);
  }, [toastMessage]);

  const uploadMutation = useMutation({
    mutationFn: () => {
      if (!timeseriesFile || !datamodelFile) {
        throw new Error("Select both timeseries and datamodel files before uploading");
      }
      return datasetsApi.createWithProgress(
        {
        name: datasetName,
        timeseriesFile,
        datamodelFile,
        timeseriesFilename: timeseriesFile.name,
        datamodelFilename: datamodelFile.name,
        },
        (percent) => setUploadProgress(percent),
      );
    },
    onMutate: () => {
      setLatestError(null);
      setUploadProgress(0);
    },
    onSuccess: (dataset) => {
      setLatestError(null);
      upsertDataset(dataset);
      setDatasetName("");
      setTimeseriesFile(null);
      setDatamodelFile(null);
      setUploadProgress(100);
      setToastMessage(`Uploaded dataset ${dataset.name}`);
      setFileInputRevision((value) => value + 1);
      void queryClient.invalidateQueries({ queryKey: ["dataset-pool"] });
    },
    onError: (error) => setLatestError(toErrorMessage(error)),
    onSettled: () => {
      window.setTimeout(() => setUploadProgress(0), 400);
    },
  });

  const deleteMutation = useMutation({
    mutationFn: (datasetId: string) => datasetsApi.remove(datasetId),
    onSuccess: (_, datasetId) => {
      setLatestError(null);
      removeDataset(datasetId);
      setPendingDeleteDatasetId(null);
      if (previewDatasetId === datasetId) {
        setPreviewDatasetId(null);
      }
      setToastMessage("Dataset deleted");
      void queryClient.invalidateQueries({ queryKey: ["dataset-pool"] });
    },
    onError: (error) => setLatestError(toErrorMessage(error)),
  });

  const loadMutation = useMutation({
    mutationFn: (datasetId: string) => {
      if (!sessionId) {
        throw new Error("Create a session before loading datasets into analysis state");
      }
      return datasetsApi.loadIntoSession(sessionId, datasetId);
    },
    onSuccess: (_, datasetId) => {
      setLatestError(null);
      const datasetLabel = datasets.find((entry) => entry.id === datasetId)?.name ?? datasetId;
      setToastMessage(`Loaded ${datasetLabel} into the active session`);
      if (!sessionId) {
        return;
      }
      void queryClient.invalidateQueries({ queryKey: ["session-summary", sessionId] });
      void queryClient.invalidateQueries({ queryKey: ["runconfig", sessionId] });
      void queryClient.invalidateQueries({ queryKey: ["analysis-summary", sessionId] });
      void queryClient.invalidateQueries({ queryKey: ["sensors-coverage", sessionId] });
      void queryClient.invalidateQueries({ queryKey: ["timeseries-preview", sessionId] });
      void queryClient.invalidateQueries({ queryKey: ["coverage-timeline", sessionId] });
    },
    onError: (error) => setLatestError(toErrorMessage(error)),
  });

  const uploadDisabled = useMemo(
    () => uploadMutation.isPending || timeseriesFile === null || datamodelFile === null,
    [datamodelFile, timeseriesFile, uploadMutation.isPending],
  );

  const pendingDeleteDataset =
    pendingDeleteDatasetId === null ? null : datasets.find((dataset) => dataset.id === pendingDeleteDatasetId) ?? null;

  return (
    <section className="workflow-panel-card">
      <div className="workflow-panel-header">
        <div>
          <span className="eyebrow">Dataset pool</span>
          <h2>Shared inputs</h2>
        </div>
        <span className="workflow-phase-chip">{datasets.length} datasets</span>
      </div>

      <div className="workflow-dataset-upload">
        <label className="workflow-form-field">
          <span>Dataset name (optional)</span>
          <input
            value={datasetName}
            placeholder="Example: HornsRev-MAST"
            onChange={(event) => setDatasetName(event.target.value)}
          />
        </label>
        <label className="workflow-form-field">
          <span>Timeseries file</span>
          <input
            key={`timeseries-${fileInputRevision}`}
            type="file"
            accept=".csv,.tsv,.txt,.xlsx,.xls"
            onChange={(event) => setTimeseriesFile(event.target.files?.[0] ?? null)}
          />
        </label>
        <label className="workflow-form-field">
          <span>Datamodel file</span>
          <input
            key={`datamodel-${fileInputRevision}`}
            type="file"
            accept=".json"
            onChange={(event) => setDatamodelFile(event.target.files?.[0] ?? null)}
          />
        </label>
        <button className="primary-button" type="button" disabled={uploadDisabled} onClick={() => uploadMutation.mutate()}>
          {uploadMutation.isPending ? `Uploading ${uploadProgress}%` : "Upload dataset"}
        </button>
        {uploadMutation.isPending ? (
          <div className="workflow-upload-progress" aria-live="polite">
            <progress max={100} value={uploadProgress} />
            <span>{uploadProgress}%</span>
          </div>
        ) : null}
      </div>

      {latestError ? <p className="workflow-error-text">{latestError}</p> : null}
      {toastMessage ? <div className="workflow-toast" role="status">{toastMessage}</div> : null}
      {datasetsQuery.isFetching ? <p className="muted-text">Refreshing dataset pool...</p> : null}

      <div className="workflow-dataset-list">
        {datasets.length === 0 ? <p className="muted-text">No shared datasets yet. Upload one to start wiring workflows.</p> : null}
        {datasets.map((dataset) => (
          <div key={dataset.id} className="workflow-dataset-card-shell">
            <button
              type="button"
              className="workflow-dataset-card"
              draggable
              onClick={() => setSelectedNodeId(addDatasetNode(activeBranchId, dataset.id))}
              onDragStart={(event) => {
                event.dataTransfer.setData("application/gokaatru-dataset", dataset.id);
                event.dataTransfer.effectAllowed = "move";
              }}
            >
              <strong>{dataset.name}</strong>
              <span>
                {dataset.sensor_count} sensors · {summarizeRange(dataset.date_range.start, dataset.date_range.end)}
              </span>
              <span>Coverage {dataset.coverage_pct.toFixed(1)}%</span>
            </button>
            <div className="workflow-dataset-actions">
              <button
                className="secondary-button"
                type="button"
                disabled={loadMutation.isPending || !sessionId}
                onClick={() => loadMutation.mutate(dataset.id)}
              >
                Load To Session
              </button>
              <button
                className="ghost-button"
                type="button"
                onClick={() => setPreviewDatasetId((current) => (current === dataset.id ? null : dataset.id))}
              >
                {previewDatasetId === dataset.id ? "Hide Preview" : "Preview"}
              </button>
              <button
                className="ghost-button"
                type="button"
                disabled={deleteMutation.isPending}
                onClick={() => setPendingDeleteDatasetId(dataset.id)}
              >
                Delete
              </button>
            </div>
            {previewDatasetId === dataset.id ? (
              <div className="workflow-dataset-preview">
                <div className="workflow-dataset-preview-meta">
                  <strong>Preview rows</strong>
                  <span>
                    {previewQuery.data?.preview_rows ?? 0} of {previewQuery.data?.total_rows ?? 0}
                  </span>
                </div>
                {previewQuery.isLoading ? <p className="muted-text">Loading preview...</p> : null}
                {previewQuery.isError ? <p className="workflow-error-text">{toErrorMessage(previewQuery.error)}</p> : null}
                {previewQuery.data ? (
                  <div className="table-wrap">
                    <table className="data-table workflow-preview-table">
                      <thead>
                        <tr>
                          {previewQuery.data.columns.map((column) => (
                            <th key={`${dataset.id}-${column}`}>{column}</th>
                          ))}
                        </tr>
                      </thead>
                      <tbody>
                        {previewQuery.data.rows.map((row, rowIndex) => (
                          <tr key={`${dataset.id}-row-${rowIndex + 1}`}>
                            {previewQuery.data.columns.map((column) => (
                              <td key={`${dataset.id}-row-${rowIndex + 1}-${column}`}>{String(row[column] ?? "")}</td>
                            ))}
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                ) : null}
              </div>
            ) : null}
          </div>
        ))}
      </div>

      {pendingDeleteDataset ? (
        <div className="workflow-modal-overlay" role="dialog" aria-modal="true" aria-label="Confirm dataset deletion">
          <div className="workflow-modal">
            <header className="workflow-modal-header">
              <h3>Delete Dataset</h3>
            </header>
            <div className="workflow-modal-body">
              <p>
                Delete <strong>{pendingDeleteDataset.name}</strong> from the shared dataset pool?
              </p>
              <p className="muted-text">This removes stored files and cannot be undone.</p>
            </div>
            <footer className="workflow-modal-actions">
              <button className="secondary-button" type="button" onClick={() => setPendingDeleteDatasetId(null)}>
                Cancel
              </button>
              <button
                className="ghost-button"
                type="button"
                disabled={deleteMutation.isPending}
                onClick={() => deleteMutation.mutate(pendingDeleteDataset.id)}
              >
                {deleteMutation.isPending ? "Deleting..." : "Confirm Delete"}
              </button>
            </footer>
          </div>
        </div>
      ) : null}
    </section>
  );
}