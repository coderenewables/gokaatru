import { cleanup } from "@testing-library/react";
import { afterEach, beforeEach, vi } from "vitest";

import { useWorkspaceStore } from "../stores/workspaceStore";

beforeEach(() => {
  localStorage.clear();
  useWorkspaceStore.getState().resetWorkspace();
});

afterEach(() => {
  cleanup();
  useWorkspaceStore.getState().resetWorkspace();
  localStorage.clear();
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
});