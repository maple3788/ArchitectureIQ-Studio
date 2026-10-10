import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
export default defineConfig({
  plugins: [react()],
  server: {
    proxy: {
      "/api/studio": {
        target: process.env.STUDIO_API_TARGET || "http://127.0.0.1:8094",
        changeOrigin: true,
      },
    },
  },
  test: { environment: "jsdom" },
});
