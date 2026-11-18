import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

export default defineConfig({
  plugins: [react()],
  build: {
    target: "es2022",
    minify: "esbuild",
    chunkSizeWarningLimit: 10000,
    rollupOptions: {
      output: {
        chunkFileNames: "assets/[name]-[hash].js",
        manualChunks(id) {
          if (id.includes("node_modules/dockview")) return "lib-dockview";
          if (id.includes("node_modules/flexlayout-react")) return "lib-flexlayout";
          if (id.includes("node_modules/uplot")) return "lib-uplot";
          if (/node_modules\/(react|react-dom|scheduler)\//.test(id)) return "lib-react";
          return undefined;
        },
      },
    },
  },
  preview: { port: 5198, strictPort: true, host: "127.0.0.1" },
  server: { port: 5198, strictPort: true, host: "127.0.0.1" },
});
