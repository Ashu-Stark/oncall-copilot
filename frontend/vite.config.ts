import { defineConfig } from "vitest/config";
import react from "@vitejs/plugin-react";

export default defineConfig({
  plugins: [react()],
  server: {
    port: 5184,
    // the API runs on 8104 in development; same-origin /api calls are forwarded to it
    proxy: { "/api": { target: "http://127.0.0.1:8104", changeOrigin: false } },
  },
  preview: { port: 5184, proxy: { "/api": { target: "http://127.0.0.1:8104" } } },
  test: {
    environment: "jsdom",
    globals: true,
    setupFiles: ["./src/test/setup.ts"],
  },
});
