import { defineConfig, devices } from "@playwright/test";
import path from "node:path";
import { fileURLToPath } from "node:url";

const here = path.dirname(fileURLToPath(import.meta.url));

// Dedicated ports: a developer's own servers on 8000 / 5173 are never reused or touched.
const BACKEND_PORT = 8011;
const FRONTEND_PORT = 5183;
const BACKEND_URL = `http://127.0.0.1:${BACKEND_PORT}`;
const FRONTEND_URL = `http://127.0.0.1:${FRONTEND_PORT}`;

// The backend must run under the interpreter that has the project installed; override
// with E2E_PYTHON when `python` on PATH is not that one.
const PYTHON = process.env.E2E_PYTHON ?? "python";

export default defineConfig({
  testDir: "./e2e",
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
      env: { GOKAATRU_DATA_DIR: path.resolve(here, ".e2e-data") },
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
