import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// Vite config. We talk to the backend directly via VITE_API_BASE (the backend has
// permissive CORS), so a dev proxy is optional. A "/api" proxy is provided as a
// convenience for anyone who prefers same-origin requests in dev.
export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    proxy: {
      "/api": {
        target: "http://localhost:8001",
        changeOrigin: true,
        rewrite: (p) => p.replace(/^\/api/, ""),
      },
    },
  },
});
