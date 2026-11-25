/// <reference types="vitest" />
import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import { fileURLToPath, URL } from "node:url";

// The e2e harness points the dev proxy at its own backend through this variable.
const apiProxyTarget = process.env.VITE_API_PROXY_TARGET ?? "http://127.0.0.1:8000";

// https://vite.dev/config/
export default defineConfig({
  plugins: [react()],
  resolve: {
    alias: {
      "@": fileURLToPath(new URL("./src", import.meta.url)),
    },
  },
  server: {
    port: 5173,
    proxy: {
      // Browser talks same-origin in dev; proxy /api to the FastAPI app.
      "/api": {
        target: apiProxyTarget,
        changeOrigin: true,
      },
      "/sse": {
        target: apiProxyTarget,
        changeOrigin: true,
      },
    },
  },
  test: {
    globals: true,
    environment: "jsdom",
    setupFiles: ["./src/test/setup.ts"],
    css: false,
    // e2e/ holds Playwright specs, which Vitest cannot run.
    include: ["src/**/*.{test,spec}.{ts,tsx}"],
  },
});
