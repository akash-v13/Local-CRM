import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";

// The UI calls the backend at /api/... and Vite forwards those requests to the
// FastAPI server (stripping the /api prefix). Same origin for the browser, so no
// CORS setup is needed. Inside docker-compose the API is http://api:8000.
const apiTarget = process.env.API_TARGET ?? "http://localhost:8000";

export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    proxy: {
      "/api": {
        target: apiTarget,
        changeOrigin: true,
        rewrite: (path) => path.replace(/^\/api/, ""),
      },
    },
  },
});
