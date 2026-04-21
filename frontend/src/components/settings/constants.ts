import { Activity, Bot, Database, Search, Wifi, Wrench } from "lucide-react";

import type { SectionNavEntry } from "./types";

export const SECTIONS: readonly SectionNavEntry[] = [
  { id: "connection", label: "连接", description: "模式与本机连接", icon: Wifi },
  { id: "models", label: "模型", description: "模型路由", icon: Bot },
  { id: "learning", label: "学习引擎", description: "解析与构建", icon: Wrench },
  { id: "search", label: "检索", description: "联网与 RAG", icon: Search },
  { id: "ops", label: "部署状态", description: "鉴权、SMTP、存储", icon: Database },
  { id: "observability", label: "观测调试", description: "Tracing 与浏览器调试", icon: Activity },
] as const;

export const MODEL_KEYS = new Set([
  "models.primary",
  "models.reason",
  "models.light",
  "models.extract",
  "models.embedding",
  "models.ocr",
  "models.image_generation",
]);

export const CORE_STATUS_KEYS = new Set([
  "auth.enabled",
  "llm.base_url",
]);

export const STORAGE_STATUS_KEYS = new Set([
  "database.url",
  "storage.backend",
  "storage.s3_bucket",
  "storage.s3_endpoint",
  "storage.s3_public_base_url",
  "storage.s3_addressing_style",
  "storage.s3_credential_mode",
  "storage.s3_access_key",
  "storage.s3_secret_key",
  "storage.dogecloud_access_key",
  "storage.dogecloud_space",
]);

export const OBSERVABILITY_ENV_STATUS_KEYS = new Set([
  "langsmith.tracing",
  "langsmith.api_key",
  "langsmith.project",
  "langsmith.endpoint",
]);

export const LEARNING_SETTING_PREFIXES = [
  "ingest.",
  "planner.",
  "docgen.",
  "interact.",
  "knowledge_graph.",
];

export const SEARCH_SETTING_PREFIXES = ["rag.", "local_rag.", "search."];

export const OBSERVABILITY_SETTING_PREFIXES = [
  "observability.",
  "runtime.",
  "embedding.",
];

export const MODE_AWARE_PREFERENCE_KEYS = new Set([
  "ingest.default_parser_provider",
  "ingest.mineru_model_version",
  "ingest.mineru_enable_formula",
  "ingest.mineru_enable_table",
  "ingest.mineru_is_ocr",
  "planner.default_digest_mode",
  "interact.history_turns",
]);

export const SETTING_SELECT_OPTIONS: Record<
  string,
  Array<{ value: string; label: string }>
> = {
  "ingest.default_parser_provider": [
    { value: "auto", label: "自动（本地 parser chain）" },
    { value: "mineru", label: "MinerU" },
    { value: "markitdown", label: "MarkItDown" },
  ],
  "ingest.mineru_model_version": [
    { value: "vlm", label: "vlm" },
    { value: "pipeline", label: "pipeline" },
  ],
  "planner.default_digest_mode": [
    { value: "sprint", label: "sprint" },
    { value: "systematic", label: "systematic" },
  ],
};
