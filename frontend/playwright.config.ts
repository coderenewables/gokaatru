import { defineConfig, devices } from "@playwright/test";
import path from "node:path";
import { fileURLToPath } from "node:url";

const here = path.dirname(fileURLToPath(import.meta.url));

// Dedicated ports: a developer's own servers on 8000 / 5173 are never reused or touched. Two
// checkouts running their browser tests at once each set their own pair.
const BACKEND_PORT = Number(process.env.E2E_BACKEND_PORT ?? 8011);
const FRONTEND_PORT = Number(process.env.E2E_FRONTEND_PORT ?? 5183);
const BACKEND_URL = `http://127.0.0.1:${BACKEND_PORT}`;
const FRONTEND_URL = `http://127.0.0.1:${FRONTEND_PORT}`;

// The backend must run under the interpreter that has the project installed; override
// with E2E_PYTHON when `python` on PATH is not that one.
const PYTHON = process.env.E2E_PYTHON ?? "python";

// Each run's backend keeps its sessions and projects in a folder of its own, so a run never
// sees what earlier runs left (the start screen would list every project they made). The
// name is fixed once in the runner's environment, which its workers inherit; global-setup
// removes the folders of earlier runs.
process.env.E2E_RUN ??= new Date().toISOString().replace(/[:.]/g, "-");
export const E2E_DATA_ROOT = path.resolve(here, ".e2e-data");
const E2E_DATA_DIR = path.join(E2E_DATA_ROOT, process.env.E2E_RUN);

export default defineConfig({
  testDir: "./e2e",
  globalSetup: "./e2e/global-setup.ts",
  outputDir: "./test-results",
  reporter: [["list"], ["html", { open: "never", outputFolder: "playwright-report" }]],
  fullyParallel: false,
  workers: 1,
  retries: 0,
  timeout: 60_000,
  expect: { timeout: 10_000 },
  use: {
    baseURL: FRONTEND_URL,
    trace: "retain-on-failure",
    screenshot: "only-on-failure",
  },
  projects: [{ name: "chromium", use: { ...devices["Desktop Chrome"] } }],
  webServer: [
    {
      command: `${PYTHON} -m uvicorn server.api.main:app --host 127.0.0.1 --port ${BACKEND_PORT}`,
      cwd: path.resolve(here, ".."),
      // Its own sessions and projects, never the developer's data/.
      env: { GOKAATRU_DATA_DIR: E2E_DATA_DIR },
      url: `${BACKEND_URL}/api/health`,
      reuseExistingServer: false,
      // Importing the scientific stack makes a cold start take 20-40 s.
      timeout: 180_000,
    },
    {
      command: `npx vite --host 127.0.0.1 --port ${FRONTEND_PORT} --strictPort`,
      cwd: here,
      url: FRONTEND_URL,
      reuseExistingServer: false,
      timeout: 60_000,
      env: { VITE_API_PROXY_TARGET: BACKEND_URL },
    },
  ],
});
