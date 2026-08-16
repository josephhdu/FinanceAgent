import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// The SPA talks to the FastAPI backend over these paths. In dev, Vite proxies
// them to uvicorn (default :8000) so the frontend hot-reloads independently.
// In production, `vite build` emits to dist/ and FastAPI serves it directly, so
// everything is same-origin and no proxy is involved.
const API_TARGET = process.env.VITE_API_TARGET || "http://127.0.0.1:8000";
const proxy = {
  target: API_TARGET,
  changeOrigin: true,
};

export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    proxy: {
      "/api": proxy,
      "/ready": proxy,
      "/health": proxy,
    },
  },
});
