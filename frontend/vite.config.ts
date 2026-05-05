import { defineConfig, loadEnv } from "vite";
import react from "@vitejs/plugin-react";

const LOCAL_HOST = "127.0.0.1";
const DEFAULT_BACKEND_PORT = "9020";
const DEFAULT_FRONTEND_PORT = 5180;
const DEFAULT_WEB_BASE_PATH = "/";

const MARKDOWN_CORE_PACKAGES = new Set([
  "react-markdown",
  "remark-gfm",
  "rehype-raw",
  "unified",
  "vfile",
  "vfile-message",
  "mdast-util-from-markdown",
  "mdast-util-gfm",
  "mdast-util-gfm-autolink-literal",
  "mdast-util-gfm-footnote",
  "mdast-util-gfm-strikethrough",
  "mdast-util-gfm-table",
  "mdast-util-gfm-task-list-item",
  "mdast-util-to-hast",
  "mdast-util-to-markdown",
  "micromark",
  "micromark-core-commonmark",
  "micromark-extension-gfm",
  "micromark-extension-gfm-autolink-literal",
  "micromark-extension-gfm-footnote",
  "micromark-extension-gfm-strikethrough",
  "micromark-extension-gfm-table",
  "micromark-extension-gfm-tagfilter",
  "micromark-extension-gfm-task-list-item",
  "micromark-factory-destination",
  "micromark-factory-label",
  "micromark-factory-space",
  "micromark-factory-title",
  "micromark-factory-whitespace",
  "micromark-util-character",
  "micromark-util-chunked",
  "micromark-util-classify-character",
  "micromark-util-combine-extensions",
  "micromark-util-decode-numeric-character-reference",
  "micromark-util-decode-string",
  "micromark-util-encode",
  "micromark-util-html-tag-name",
  "micromark-util-normalize-identifier",
  "micromark-util-resolve-all",
  "micromark-util-sanitize-uri",
  "micromark-util-subtokenize",
  "micromark-util-symbol",
  "micromark-util-types",
  "hast-util-to-jsx-runtime",
  "hast-util-to-text",
  "property-information",
  "space-separated-tokens",
  "comma-separated-tokens",
  "trim-lines",
  "zwitch",
  "devlop",
]);

const MARKDOWN_MATH_PACKAGES = new Set([
  "katex",
  "rehype-katex",
  "remark-math",
  "micromark-extension-math",
  "mdast-util-math",
  "hast-util-to-text",
]);

const MARKDOWN_HIGHLIGHT_PACKAGES = new Set([
  "highlight.js",
  "rehype-highlight",
  "lowlight",
]);

const MERMAID_VENDOR_PACKAGES = new Set([
  "lodash-es",
  "dompurify",
  "marked",
  "roughjs",
  "khroma",
  "stylis",
  "dayjs",
  "ts-dedent",
  "@braintree/sanitize-url",
  "@iconify/utils",
]);

function getNodeModulePackageName(id: string): string | null {
  const normalized = id.replace(/\\/g, "/");
  const match = normalized.match(/\/node_modules\/((?:@[^/]+\/)?[^/]+)/);
  return match?.[1] ?? null;
}

function manualChunks(id: string): string | undefined {
  const packageName = getNodeModulePackageName(id);
  if (!packageName) {
    return undefined;
  }

  if (packageName === "react" || packageName === "react-dom" || packageName === "scheduler") {
    return "vendor-react";
  }
  if (packageName === "react-router" || packageName === "react-router-dom") {
    return "vendor-router";
  }
  if (packageName === "@tanstack/react-query" || packageName === "@tanstack/query-core") {
    return "vendor-query";
  }
  if (packageName === "framer-motion" || packageName === "motion-dom" || packageName === "motion-utils") {
    return "vendor-motion";
  }
  if (packageName === "lucide-react") {
    return "vendor-icons";
  }
  if (packageName === "axios") {
    return "vendor-http";
  }
  if (MERMAID_VENDOR_PACKAGES.has(packageName)) {
    return "mermaid-vendor";
  }
  if (packageName === "d3" || packageName.startsWith("d3-")) {
    return "vendor-d3";
  }
  if (MARKDOWN_MATH_PACKAGES.has(packageName)) {
    return "markdown-math";
  }
  if (MARKDOWN_HIGHLIGHT_PACKAGES.has(packageName)) {
    return "markdown-highlight";
  }
  if (MARKDOWN_CORE_PACKAGES.has(packageName)) {
    return "markdown-core";
  }

  return undefined;
}

function normalizeBasePath(rawValue?: string): string {
  const value = (rawValue || DEFAULT_WEB_BASE_PATH).trim();
  if (!value) {
    return DEFAULT_WEB_BASE_PATH;
  }
  if (value === "." || value === "./") {
    return "./";
  }
  if (/^[a-z][a-z\d+\-.]*:\/\//i.test(value)) {
    return value.endsWith("/") ? value : `${value}/`;
  }

  const normalized = value.startsWith("/") ? value : `/${value}`;
  return normalized.endsWith("/") ? normalized : `${normalized}/`;
}

export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, "..", "");
  const backendPort = env.AITEACHME_BACKEND_PORT || DEFAULT_BACKEND_PORT;
  const frontendPort = Number(env.AITEACHME_FRONTEND_PORT || DEFAULT_FRONTEND_PORT);
  const apiTarget = env.VITE_API_URL?.trim() || `http://${LOCAL_HOST}:${backendPort}`;
  const basePath = normalizeBasePath(env.VITE_BASE_PATH || env.AITEACHME_FRONTEND_BASE_PATH);

  return {
    base: basePath,
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
      rollupOptions: {
        output: {
          manualChunks,
        },
      },
    },
  };
});
