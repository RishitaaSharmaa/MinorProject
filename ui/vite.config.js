import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// In development the UI calls "/api/*", which Vite forwards to the FastAPI
// backend, so the browser never makes a cross-origin request.
export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    proxy: {
      "/api": {
        target: process.env.VITE_PROXY_TARGET || "http://localhost:8000",
        changeOrigin: true,
        rewrite: (path) => path.replace(/^\/api/, ""),
      },
    },
  },
});
