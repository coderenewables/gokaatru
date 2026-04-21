import { useCallback, useMemo, useRef } from "react";

import { ApiError, workflowApi } from "../lib/api";
import { useWorkflowStore } from "../stores/workflowStore";

function toErrorMessage(error: unknown): string {
  if (error instanceof ApiError) {
    return error.message;
  }
  if (error instanceof Error) {
    return error.message;
  }
  return "Workflow execution failed";
}

export function useWorkflowExecution() {
  const sessionId = useWorkflowStore((state) => {
    const activeBranch = state.branches.find((branch) => branch.id === state.activeBranchId);
    return activeBranch?.sessionId ?? null;
  });
  const isExecuting = useWorkflowStore((state) => state.isExecuting);
  const executionMode = useWorkflowStore((state) => state.executionMode);
  const executionError = useWorkflowStore((state) => state.executionError);

  const prepareExecution = useWorkflowStore((state) => state.prepareExecution);
  const applyExecutionEvent = useWorkflowStore((state) => state.applyExecutionEvent);
  const applyExecutionResult = useWorkflowStore((state) => state.applyExecutionResult);
  const setExecutionError = useWorkflowStore((state) => state.setExecutionError);
  const stopExecution = useWorkflowStore((state) => state.stopExecution);
  const buildExecutionRequest = useWorkflowStore((state) => state.buildExecutionRequest);
  const retryFailedNodes = useWorkflowStore((state) => state.retryFailedNodes);

  const streamControllerRef = useRef<AbortController | null>(null);

  const canExecute = sessionId !== null;

  const streamExecute = useCallback(
    async (mode: "auto" | "manual", resetStatuses: boolean) => {
      if (!sessionId) {
        setExecutionError("Create a session before running workflow execution.");
        return;
      }

      if (streamControllerRef.current) {
        streamControllerRef.current.abort();
      }

      const controller = new AbortController();
      streamControllerRef.current = controller;

      prepareExecution(mode, resetStatuses);
      const payload = buildExecutionRequest(mode);

      try {
        await workflowApi.streamExecute(
          sessionId,
          payload,
          (event) => {
            applyExecutionEvent(event);
          },
          controller.signal,
        );
      } catch (error) {
        if (error instanceof DOMException && error.name === "AbortError") {
          return;
        }
        setExecutionError(toErrorMessage(error));
        stopExecution();
      } finally {
        if (streamControllerRef.current === controller) {
          streamControllerRef.current = null;
        }
      }
    },
    [applyExecutionEvent, buildExecutionRequest, prepareExecution, sessionId, setExecutionError, stopExecution],
  );

  const runAll = useCallback(async () => {
    await streamExecute("auto", true);
  }, [streamExecute]);

  const retryFailed = useCallback(async () => {
    if (!sessionId) {
      setExecutionError("Create a session before retrying failed workflow nodes.");
      return;
    }

    const hasFailedNodes = retryFailedNodes();
    if (!hasFailedNodes) {
      setExecutionError("No failed nodes are available for retry.");
      return;
    }

    await streamExecute("auto", false);
  }, [retryFailedNodes, sessionId, setExecutionError, streamExecute]);

  const step = useCallback(async () => {
    if (!sessionId) {
      setExecutionError("Create a session before stepping through workflow execution.");
      return;
    }

    prepareExecution("manual", false);
    const payload = buildExecutionRequest("manual");

    try {
      const result = await workflowApi.step(sessionId, payload);
      applyExecutionResult(result);
      setExecutionError(null);
    } catch (error) {
      setExecutionError(toErrorMessage(error));
      stopExecution();
    }
  }, [applyExecutionResult, buildExecutionRequest, prepareExecution, sessionId, setExecutionError, stopExecution]);

  const pause = useCallback(async () => {
    if (streamControllerRef.current) {
      streamControllerRef.current.abort();
      streamControllerRef.current = null;
    }

    if (!sessionId) {
      stopExecution();
      return;
    }

    try {
      await workflowApi.stop(sessionId);
    } catch {
      // Keep UI responsive even if stop call fails.
    }
    stopExecution();
  }, [sessionId, stopExecution]);

  const statusLabel = useMemo(() => {
    if (!canExecute) {
      return "Create a session to enable execution";
    }
    if (isExecuting) {
      return executionMode === "auto" ? "Running workflow..." : "Stepping workflow...";
    }
    if (executionError) {
      return executionError;
    }
    return "Execution ready";
  }, [canExecute, executionError, executionMode, isExecuting]);

  return {
    canExecute,
    isExecuting,
    statusLabel,
    runAll,
    retryFailed,
    step,
    pause,
  };
}
