import { defineConfig, loadEnv } from "vite";
import react from "@vitejs/plugin-react";

export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, "..", "");
  const backendHost = env.AITEACHME_BACKEND_HOST || "127.0.0.1";
  const backendPort = env.AITEACHME_BACKEND_PORT || "9020";
  const frontendHost = env.AITEACHME_FRONTEND_HOST || "127.0.0.1";
  const frontendPort = Number(env.AITEACHME_FRONTEND_PORT || "5180");
  const apiTarget = env.VITE_API_URL?.trim() || `http://${backendHost}:${backendPort}`;

  return {
    base: "./",
    plugins: [react()],
    root: ".",
    envDir: "..",
    server: {
      host: frontendHost,
      port: frontendPort,
      strictPort: true,
      proxy: {
        "/api": {
          target: apiTarget,
          changeOrigin: true,
        },
        "/openapi.json": {
          target: apiTarget,
          changeOrigin: true,
        },
      },
    },
    build: {
      outDir: "dist",
    },
  };
});
