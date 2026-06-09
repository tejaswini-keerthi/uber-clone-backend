import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// Dev server runs on 5173. The API base URL is configured via VITE_API_BASE_URL
// (see .env.example), so no dev proxy is required.
export default defineConfig({
  plugins: [react()],
  server: {
    host: true,
    port: 5173,
  },
});
