import { defineConfig, loadEnv } from "vite";
import react from "@vitejs/plugin-react";

const LOCAL_HOST = "127.0.0.1";
const DEFAULT_BACKEND_PORT = "9020";
const DEFAULT_FRONTEND_PORT = 5180;

export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, "..", "");
  const backendPort = env.AITEACHME_BACKEND_PORT || DEFAULT_BACKEND_PORT;
  const frontendPort = Number(env.AITEACHME_FRONTEND_PORT || DEFAULT_FRONTEND_PORT);
  const apiTarget = env.VITE_API_URL?.trim() || `http://${LOCAL_HOST}:${backendPort}`;

  return {
    base: "./",
    plugins: [react()],
    root: ".",
    envDir: "..",
    server: {
      host: LOCAL_HOST,
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
