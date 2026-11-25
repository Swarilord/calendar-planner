import react from "@vitejs/plugin-react";
import { defineConfig } from "vitest/config";

export default defineConfig({
  plugins: [react()],
  server: {
    // In development, the page asks Vite for /api/...; Vite forwards it to
    // FastAPI. The browser sees one origin, so no CORS setup is needed.
    proxy: { "/api": "http://localhost:8000" },
  },
});
