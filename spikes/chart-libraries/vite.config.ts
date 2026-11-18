import { defineConfig } from "vite";

export default defineConfig({
  build: {
    target: "es2022",
    minify: "esbuild",
    chunkSizeWarningLimit: 10000,
    rollupOptions: {
      output: {
        chunkFileNames: "assets/[name]-[hash].js",
        manualChunks(id) {
          if (id.includes("plotly-v2")) return "lib-plotly2";
          if (id.includes("plotly.js-dist-min")) return "lib-plotly4";
          if (id.includes("node_modules/echarts") || id.includes("node_modules/zrender")) return "lib-echarts";
          if (id.includes("node_modules/uplot")) return "lib-uplot";
          if (/node_modules\/(regl|regl-scatterplot|regl-line|dom-2d-camera|camera-2d-simple|gl-matrix|earcut|pub-sub-es|@flekschas)/.test(id)) return "lib-regl-scatterplot";
          return undefined;
        },
      },
    },
  },
  preview: { port: 5199, strictPort: true, host: "127.0.0.1" },
  server: { port: 5199, strictPort: true, host: "127.0.0.1" },
});
