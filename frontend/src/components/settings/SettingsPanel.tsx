import { useEffect, useMemo, useState } from "react";
import { AnimatePresence, motion } from "framer-motion";
import {
  Activity,
  Bot,
  CheckCircle2,
  Database,
  Eye,
  EyeOff,
  KeyRound,
  Loader2,
  Search,
  RefreshCcw,
  Sparkles,
  Wrench,
  X,
} from "lucide-react";
import {
  DEFAULT_SETTINGS,
  type AppSettings,
  type MinerUModelVersion,
  type ParserProvider,
  useSettings,
} from "../../hooks/useSettings";
import { apiClient, getApiErrorMessage } from "../../api/client";

interface SettingsModalProps {
  isOpen: boolean;
  onClose: () => void;
}

type SectionType = "connection" | "models" | "learning" | "search" | "ops" | "observability";
type SaveState = "idle" | "saving" | "saved" | "error";
type ConnectionStatus = "idle" | "success" | "error";
type SettingSource = "env" | "settings" | "user_settings" | "runtime";
type SettingStatus = "configured" | "missing" | "default" | "disabled" | "enabled" | "runtime";
type SettingPrimitive = string | number | boolean | null;

interface SettingEntry {
  key: string;
  label: string;
  source: SettingSource;
  value?: unknown;
  default_value?: unknown;
  display_value?: string | null;
  status: SettingStatus;
  secret?: boolean;
  editable?: boolean;
  description?: string;
}

interface SettingSection {
  id: string;
  label: string;
  entries: SettingEntry[];
}

interface SettingsOverviewData {
  settings_path: string;
  mode: string;
  sections: SettingSection[];
  notes: string[];
}

interface ApiResponse<T> {
  code: number;
  message: string;
  data: T;
}

const DEFAULT_PROVIDER_BASE_URL = "https://api.openai.com/v1";

interface LocalEnvField {
  key: string;
  label: string;
  placeholder?: string;
  secret?: boolean;
}

interface LocalEnvGroup {
  id: string;
  label: string;
  fields: LocalEnvField[];
}

const CONNECTION_ENV_GROUPS: LocalEnvGroup[] = [
  {
    id: "llm",
    label: "LLM 接入",
    fields: [
      { key: "LLM_API_KEY", label: "LLM API Key", placeholder: "sk-...", secret: true },
      { key: "LLM_BASE_URL", label: "LLM Base URL", placeholder: "https://dashscope.aliyuncs.com/compatible-mode/v1" },
    ],
  },
  {
    id: "frontend",
    label: "前端连接",
    fields: [
      { key: "VITE_API_URL", label: "FastAPI 地址", placeholder: "http://localhost:8000" },
      { key: "VITE_USE_MOCK", label: "本地 Mock", placeholder: "false" },
    ],
  },
];

const LEARNING_ENV_GROUPS: LocalEnvGroup[] = [
  {
    id: "parser",
    label: "文档解析服务",
    fields: [
      { key: "MINERU_API_TOKEN", label: "MinerU Token", secret: true },
    ],
  },
];

const SEARCH_ENV_GROUPS: LocalEnvGroup[] = [
  {
    id: "general-search",
    label: "通用网页检索",
    fields: [
      { key: "TAVILY_API_KEY", label: "Tavily API Key", secret: true },
      { key: "BING_API_KEY", label: "Bing API Key", secret: true },
      { key: "BOCHA_API_KEY", label: "Bocha API Key", secret: true },
      { key: "BOCHA_FRESHNESS", label: "Bocha Freshness", placeholder: "noLimit" },
      { key: "BRAVE_SEARCH_API_KEY", label: "Brave Search API Key", secret: true },
      { key: "EXA_API_KEY", label: "Exa API Key", secret: true },
      { key: "JINA_SEARCH_ENRICH", label: "Jina Search Enrich", placeholder: "false" },
      { key: "SERPER_API_KEY", label: "Serper API Key", secret: true },
      { key: "SERPER_SEARCH_MODE", label: "Serper Mode", placeholder: "search" },
      { key: "SERPER_GL", label: "Serper Country", placeholder: "us" },
      { key: "SERPER_HL", label: "Serper Language", placeholder: "en" },
      { key: "SERPER_AUTOCORRECT", label: "Serper Autocorrect", placeholder: "true" },
      { key: "GOOGLE_API_KEY", label: "Google API Key", secret: true },
      { key: "GOOGLE_CX_KEY", label: "Google CX Key", secret: true },
      { key: "GOOGLE_SAFE_SEARCH", label: "Google Safe Search" },
      { key: "GOOGLE_LR", label: "Google Language Restrict" },
      { key: "SEARCHAPI_API_KEY", label: "SearchApi API Key", secret: true },
      { key: "SEARCHAPI_ENGINE", label: "SearchApi Engine", placeholder: "google" },
      { key: "SEARCHAPI_GL", label: "SearchApi Country" },
      { key: "SEARCHAPI_HL", label: "SearchApi Language" },
      { key: "SERPAPI_API_KEY", label: "SerpApi API Key", secret: true },
      { key: "SERPAPI_ENGINE", label: "SerpApi Engine", placeholder: "google" },
      { key: "SERPAPI_GL", label: "SerpApi Country" },
      { key: "SERPAPI_HL", label: "SerpApi Language" },
      { key: "SEARXNG_BASE_URL", label: "SearXNG Base URL" },
      { key: "JINA_API_KEY", label: "Jina API Key", secret: true },
    ],
  },
  {
    id: "answer-search",
    label: "答案型搜索",
    fields: [
      { key: "PERPLEXITY_API_KEY", label: "Perplexity API Key", secret: true },
      { key: "PERPLEXITY_SEARCH_MODEL", label: "Perplexity Model", placeholder: "sonar" },
      { key: "OPENROUTER_API_KEY", label: "OpenRouter API Key", secret: true },
      { key: "OPENROUTER_BASE_URL", label: "OpenRouter Base URL", placeholder: "https://openrouter.ai/api/v1" },
      { key: "OPENROUTER_SEARCH_MODEL", label: "OpenRouter Search Model", placeholder: "perplexity/sonar" },
      { key: "OPENROUTER_HTTP_REFERER", label: "OpenRouter Referer", placeholder: "http://localhost" },
      { key: "OPENROUTER_APP_TITLE", label: "OpenRouter App Title", placeholder: "AITeachMe" },
      { key: "BAIDU_AI_SEARCH_API_KEY", label: "Baidu AI Search API Key", secret: true },
      { key: "BAIDU_AI_SEARCH_MODEL", label: "Baidu AI Search Model", placeholder: "ernie-4.5-turbo-32k" },
      { key: "BAIDU_AI_SEARCH_SOURCE", label: "Baidu Search Source", placeholder: "baidu_search_v2" },
      { key: "BAIDU_AI_SEARCH_DEEP", label: "Baidu Deep Search", placeholder: "false" },
    ],
  },
  {
    id: "academic-custom-search",
    label: "学术 / 内部检索",
    fields: [
      { key: "SEMANTIC_SCHOLAR_API_KEY", label: "Semantic Scholar API Key", secret: true },
      { key: "NCBI_API_KEY", label: "NCBI API Key", secret: true },
      { key: "PUBMED_DB", label: "PubMed DB", placeholder: "pmc" },
      { key: "PUBMED_SORT", label: "PubMed Sort", placeholder: "relevance" },
      { key: "CUSTOM_RETRIEVER_ENDPOINT", label: "Custom Retriever Endpoint" },
      { key: "CUSTOM_RETRIEVER_API_KEY", label: "Custom Retriever API Key", secret: true },
      { key: "CUSTOM_RETRIEVER_API_KEY_HEADER", label: "Custom API Key Header", placeholder: "Authorization" },
      { key: "CUSTOM_RETRIEVER_QUERY_PARAM", label: "Custom Query Param", placeholder: "query" },
      { key: "CUSTOM_RETRIEVER_MAX_RESULTS_PARAM", label: "Custom Max Results Param", placeholder: "max_results" },
    ],
  },
  {
    id: "reader-rerank",
    label: "正文读取 / Rerank",
    fields: [
      { key: "JINA_READER_ENABLED", label: "Jina Reader Enabled", placeholder: "false" },
      { key: "MCP_SEARCH_TOOL", label: "MCP Search Tool" },
      { key: "MCP_SEARCH_QUERY_ARG", label: "MCP Query Arg", placeholder: "query" },
      { key: "MCP_SEARCH_MAX_RESULTS_ARG", label: "MCP Max Results Arg", placeholder: "max_results" },
      { key: "RAG_RERANK_API_KEY", label: "Rerank API Key", secret: true },
      { key: "RAG_RERANK_BASE_URL", label: "Rerank Base URL" },
    ],
  },
];

const OPS_ENV_GROUPS: LocalEnvGroup[] = [
  {
    id: "runtime-auth",
    label: "运行模式 / 鉴权",
    fields: [
      { key: "APP_MODE", label: "运行模式", placeholder: "local" },
      { key: "AUTH_ENABLED", label: "启用鉴权", placeholder: "false" },
      { key: "AUTH_TOKEN_SECRET", label: "Auth Token Secret", secret: true },
      { key: "AUTH_TOKEN_TTL_HOURS", label: "Auth Token TTL", placeholder: "720" },
      { key: "GUEST_TOKEN_TTL_HOURS", label: "Guest Token TTL", placeholder: "720" },
      { key: "GUEST_COOKIE_NAME", label: "Guest Cookie Name", placeholder: "atm_guest_token" },
      { key: "GUEST_COOKIE_SECURE", label: "Guest Cookie Secure" },
      { key: "GUEST_COOKIE_SAMESITE", label: "Guest Cookie SameSite", placeholder: "auto" },
      { key: "APP_VERSION", label: "应用版本", placeholder: "0.2.0" },
    ],
  },
  {
    id: "smtp",
    label: "SMTP / 邮箱验证码",
    fields: [
      { key: "SMTP_HOST", label: "SMTP Host" },
      { key: "SMTP_PORT", label: "SMTP Port", placeholder: "465" },
      { key: "SMTP_USERNAME", label: "SMTP Username" },
      { key: "SMTP_PASSWORD", label: "SMTP Password", secret: true },
      { key: "SMTP_FROM_EMAIL", label: "From Email" },
      { key: "SMTP_FROM_NAME", label: "From Name", placeholder: "AITeachMe" },
      { key: "SMTP_USE_SSL", label: "Use SSL", placeholder: "true" },
      { key: "SMTP_USE_STARTTLS", label: "Use StartTLS", placeholder: "false" },
      { key: "SMTP_ADDRESS_FAMILY", label: "Address Family", placeholder: "ipv4" },
      { key: "SMTP_TIMEOUT_S", label: "Timeout Seconds", placeholder: "15" },
      { key: "AUTH_EMAIL_CODE_TTL_S", label: "验证码 TTL", placeholder: "600" },
      { key: "AUTH_EMAIL_CODE_RESEND_INTERVAL_S", label: "重发间隔", placeholder: "60" },
      { key: "AUTH_EMAIL_CODE_MAX_ATTEMPTS", label: "最大尝试次数", placeholder: "5" },
    ],
  },
  {
    id: "database-storage",
    label: "数据库 / 对象存储",
    fields: [
      { key: "DATABASE_URL", label: "Database URL", secret: true },
      { key: "STORAGE_BACKEND", label: "Storage Backend", placeholder: "local" },
      { key: "S3_BUCKET", label: "S3 Bucket" },
      { key: "S3_ENDPOINT", label: "S3 Endpoint" },
      { key: "S3_ACCESS_KEY", label: "S3 Access Key", secret: true },
      { key: "S3_SECRET_KEY", label: "S3 Secret Key", secret: true },
      { key: "S3_SESSION_TOKEN", label: "S3 Session Token", secret: true },
      { key: "S3_REGION", label: "S3 Region" },
      { key: "S3_PUBLIC_BASE_URL", label: "S3 Public Base URL" },
      { key: "S3_ADDRESSING_STYLE", label: "S3 Addressing Style", placeholder: "virtual" },
      { key: "S3_CREDENTIAL_MODE", label: "S3 Credential Mode", placeholder: "auto" },
      { key: "DOGECLOUD_API_ACCESS_KEY", label: "DogeCloud Access Key", secret: true },
      { key: "DOGECLOUD_API_SECRET_KEY", label: "DogeCloud Secret Key", secret: true },
      { key: "DOGECLOUD_API_BASE_URL", label: "DogeCloud Base URL", placeholder: "https://api.dogecloud.com" },
      { key: "DOGECLOUD_SPACE_NAME", label: "DogeCloud Space" },
      { key: "DOGECLOUD_TMP_TOKEN_PATH", label: "DogeCloud Token Path", placeholder: "/auth/tmp_token.json" },
      { key: "DOGECLOUD_TMP_TOKEN_CHANNEL", label: "DogeCloud Token Channel", placeholder: "OSS_FULL" },
      { key: "DOGECLOUD_TMP_TOKEN_SCOPE", label: "DogeCloud Token Scope", placeholder: "*" },
    ],
  },
  {
    id: "misc",
    label: "其他",
    fields: [
      { key: "PROJECT_SETTINGS_PATH", label: "Settings 文件路径", placeholder: "settings_default.yaml" },
      { key: "EXPORT_OPENAPI_ON_STARTUP", label: "启动导出 OpenAPI", placeholder: "false" },
      { key: "CORS_ALLOWED_ORIGINS", label: "CORS 来源" },
    ],
  },
];

const OBSERVABILITY_ENV_GROUPS: LocalEnvGroup[] = [
  {
    id: "langsmith",
    label: "LangSmith",
    fields: [
      { key: "LANGSMITH_TRACING", label: "Tracing", placeholder: "false" },
      { key: "LANGSMITH_API_KEY", label: "API Key", secret: true },
      { key: "LANGSMITH_PROJECT", label: "Project", placeholder: "AITeachMe" },
      { key: "LANGSMITH_ENDPOINT", label: "Endpoint", placeholder: "https://api.smith.langchain.com" },
    ],
  },
];

const SECTIONS = [
  { id: "connection", label: "连接", description: "后端与 LLM", icon: KeyRound },
  { id: "models", label: "模型", description: "模型路由", icon: Bot },
  { id: "learning", label: "学习引擎", description: "解析与构建", icon: Wrench },
  { id: "search", label: "检索", description: "联网与 RAG", icon: Search },
  { id: "ops", label: "账号与存储", description: "鉴权、SMTP、数据", icon: Database },
  { id: "observability", label: "观测调试", description: "Tracing 与本机调试", icon: Activity },
] as const;

const MODEL_KEYS = new Set([
  "models.primary",
  "models.reason",
  "models.light",
  "models.extract",
  "models.embedding",
  "models.ocr",
  "models.image_generation",
]);

const CORE_STATUS_KEYS = new Set([
  "runtime.mode",
  "runtime.app_mode_raw",
  "runtime.version",
  "auth.enabled",
  "settings.path",
  "llm.base_url",
  "llm.api_key",
]);

const STORAGE_STATUS_KEYS = new Set([
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

const OBSERVABILITY_ENV_STATUS_KEYS = new Set([
  "langsmith.tracing",
  "langsmith.api_key",
  "langsmith.project",
  "langsmith.endpoint",
]);

const LEARNING_SETTING_PREFIXES = ["ingest.", "planner.", "docgen.", "interact.", "knowledge_graph."];
const SEARCH_SETTING_PREFIXES = ["rag.", "local_rag.", "search."];
const OBSERVABILITY_SETTING_PREFIXES = ["observability.", "runtime.", "embedding."];

function hasAnyPrefix(key: string, prefixes: string[]): boolean {
  return prefixes.some((prefix) => key.startsWith(prefix));
}

function isPrimitive(value: unknown): value is SettingPrimitive {
  return value === null || ["string", "number", "boolean"].includes(typeof value);
}

function displayValue(entry: SettingEntry): string {
  if (entry.secret || /key|token|secret|password|database\.url/i.test(entry.key)) {
    return entry.status === "configured" ? "已配置" : "未配置";
  }
  if (entry.display_value !== undefined && entry.display_value !== null) {
    return entry.display_value;
  }
  if (entry.value === null || entry.value === undefined || entry.value === "") {
    return "未配置";
  }
  if (typeof entry.value === "boolean") {
    return entry.value ? "开启" : "关闭";
  }
  return String(entry.value);
}

function editableEntries(sections: SettingSection[]): SettingEntry[] {
  return sections
    .flatMap((section) => section.entries)
    .filter((entry) => entry.editable && isPrimitive(entry.value));
}

function draftFromEntries(entries: SettingEntry[], source: "value" | "default_value" = "value") {
  return Object.fromEntries(
    entries.map((entry) => [entry.key, isPrimitive(entry[source]) ? entry[source] : null]),
  ) as Record<string, SettingPrimitive>;
}

function sameDraft(a: Record<string, SettingPrimitive>, b: Record<string, SettingPrimitive>): boolean {
  return JSON.stringify(a) === JSON.stringify(b);
}

function buildSettingsPayload(draft: Record<string, SettingPrimitive>, entries: SettingEntry[]) {
  const allowed = new Set(entries.map((entry) => entry.key));
  const root: Record<string, unknown> = {};
  Object.entries(draft).forEach(([key, value]) => {
    if (!allowed.has(key)) {
      return;
    }
    const parts = key.split(".");
    let cursor = root;
    parts.forEach((part, index) => {
      if (index === parts.length - 1) {
        cursor[part] = value;
        return;
      }
      if (typeof cursor[part] !== "object" || cursor[part] === null || Array.isArray(cursor[part])) {
        cursor[part] = {};
      }
      cursor = cursor[part] as Record<string, unknown>;
    });
  });
  return root;
}

function parseInputValue(raw: string, currentValue: SettingPrimitive): SettingPrimitive {
  if (typeof currentValue === "number") {
    const next = Number(raw);
    return Number.isFinite(next) ? next : currentValue;
  }
  if (currentValue === null) {
    const normalized = raw.trim().toLowerCase();
    if (!normalized || normalized === "null") return null;
    if (normalized === "true") return true;
    if (normalized === "false") return false;
  }
  return raw;
}

function InfoCard({ text, variant = "neutral" }: { text: string; variant?: "neutral" | "warning" }) {
  const className =
    variant === "warning"
      ? "border-amber-100 bg-amber-50/60 text-amber-700"
      : "border-zinc-100 bg-zinc-50/60 text-zinc-500";
  return <div className={`rounded-lg border px-4 py-3 text-[12px] leading-relaxed ${className}`}>{text}</div>;
}

function SectionDivider({ label }: { label: string }) {
  return (
    <div className="flex items-center gap-3 pt-2">
      <span className="text-[11px] font-semibold uppercase tracking-widest text-zinc-400">{label}</span>
      <div className="h-px flex-1 bg-zinc-100" />
    </div>
  );
}

function TextInput({
  value,
  onChange,
  placeholder,
  type = "text",
}: {
  value: string;
  onChange: (value: string) => void;
  placeholder?: string;
  type?: string;
}) {
  return (
    <input
      type={type}
      value={value}
      onChange={(event) => onChange(event.target.value)}
      placeholder={placeholder}
      className="w-full rounded-lg border border-zinc-200 bg-white px-3.5 py-2.5 text-[13px] text-zinc-900 placeholder:text-zinc-300 outline-none transition focus:border-zinc-400 focus:ring-4 focus:ring-zinc-900/5"
    />
  );
}

function EnvInput({
  field,
  value,
  onChange,
}: {
  field: LocalEnvField;
  value: string;
  onChange: (value: string) => void;
}) {
  const [showSecret, setShowSecret] = useState(false);
  return (
    <div className="space-y-2">
      <label className="text-[13px] font-semibold text-zinc-700">{field.label}</label>
      <div className="relative">
        <input
          type={field.secret && !showSecret ? "password" : "text"}
          value={value}
          onChange={(event) => onChange(event.target.value)}
          placeholder={field.placeholder || field.key}
          autoComplete={field.secret ? "new-password" : "off"}
          autoCapitalize="none"
          autoCorrect="off"
          spellCheck={false}
          className={`w-full rounded-lg border border-zinc-200 bg-white px-3.5 py-2.5 text-[13px] text-zinc-900 placeholder:text-zinc-300 outline-none transition focus:border-zinc-400 focus:ring-4 focus:ring-zinc-900/5 ${
            field.secret ? "pr-10" : ""
          }`}
        />
        {field.secret ? (
          <button
            type="button"
            onClick={() => setShowSecret((value) => !value)}
            className="absolute right-2 top-1/2 -translate-y-1/2 rounded-md p-1 text-zinc-400 transition hover:bg-zinc-100 hover:text-zinc-700"
            aria-label={showSecret ? "隐藏密钥" : "显示密钥"}
          >
            {showSecret ? <EyeOff className="h-4 w-4" /> : <Eye className="h-4 w-4" />}
          </button>
        ) : null}
      </div>
      <p className="font-mono text-[11px] text-zinc-400">{field.key}</p>
    </div>
  );
}

function SelectInput({
  value,
  onChange,
  options,
}: {
  value: string;
  onChange: (value: string) => void;
  options: { value: string; label: string }[];
}) {
  return (
    <select
      value={value}
      onChange={(event) => onChange(event.target.value)}
      className="w-full rounded-lg border border-zinc-200 bg-white px-3.5 py-2.5 text-[13px] text-zinc-900 outline-none transition focus:border-zinc-400 focus:ring-4 focus:ring-zinc-900/5"
    >
      {options.map((option) => (
        <option key={option.value} value={option.value}>
          {option.label}
        </option>
      ))}
    </select>
  );
}

function SwitchRow({
  title,
  description,
  enabled,
  onToggle,
}: {
  title: string;
  description: string;
  enabled: boolean;
  onToggle: () => void;
}) {
  return (
    <button
      type="button"
      onClick={onToggle}
      className="flex w-full items-center justify-between gap-4 rounded-lg border border-zinc-100 bg-white px-4 py-3 text-left transition hover:border-zinc-200"
    >
      <span>
        <span className="block text-[13px] font-semibold text-zinc-800">{title}</span>
        <span className="mt-0.5 block text-[12px] leading-relaxed text-zinc-400">{description}</span>
      </span>
      <span className={`relative inline-flex h-[22px] w-[42px] shrink-0 items-center rounded-full transition ${enabled ? "bg-zinc-900" : "bg-zinc-200"}`}>
        <span className={`inline-block h-[18px] w-[18px] rounded-full bg-white shadow-sm transition ${enabled ? "translate-x-[22px]" : "translate-x-[2px]"}`} />
      </span>
    </button>
  );
}

function SourcePill({ source }: { source: SettingSource }) {
  const label =
    source === "env"
      ? ".env"
      : source === "user_settings"
        ? "用户库"
        : source === "settings"
          ? "默认"
          : "运行时";
  return <span className="rounded-md border border-zinc-200 bg-white px-2 py-0.5 text-[11px] font-semibold text-zinc-500">{label}</span>;
}

function ReadonlySettingsList({
  entries,
  loading,
  error,
}: {
  entries: SettingEntry[];
  loading: boolean;
  error: string | null;
}) {
  if (loading) return <InfoCard text="正在读取后端当前状态..." />;
  if (error) return <InfoCard text={error} variant="warning" />;
  if (!entries.length) return <InfoCard text="暂无配置项。" />;

  return (
    <div className="space-y-2">
      {entries.map((entry) => (
        <div key={entry.key} className="rounded-lg border border-zinc-100 bg-zinc-50/40 px-4 py-3">
          <div className="flex flex-wrap items-center justify-between gap-2">
            <div>
              <div className="text-[13px] font-semibold text-zinc-700">{entry.label}</div>
              <div className="mt-0.5 font-mono text-[11px] text-zinc-400">{entry.key}</div>
            </div>
            <SourcePill source={entry.source} />
          </div>
          <div className="mt-2 rounded-md border border-zinc-200 bg-white px-2.5 py-1.5 font-mono text-[12px] text-zinc-800">
            {displayValue(entry)}
          </div>
          {entry.description ? <p className="mt-2 text-[11px] leading-relaxed text-zinc-400">{entry.description}</p> : null}
        </div>
      ))}
    </div>
  );
}

function EditableSettingsList({
  entries,
  draft,
  onChange,
  loading,
  error,
}: {
  entries: SettingEntry[];
  draft: Record<string, SettingPrimitive>;
  onChange: (key: string, value: SettingPrimitive) => void;
  loading: boolean;
  error: string | null;
}) {
  const items = entries.filter((entry) => entry.editable && isPrimitive(draft[entry.key]));
  if (loading) return <InfoCard text="正在读取当前用户 settings..." />;
  if (error) return <InfoCard text={error} variant="warning" />;
  if (!items.length) return <InfoCard text="暂无可编辑 settings。" />;

  return (
    <div className="space-y-3">
      {items.map((entry) => {
        const value = draft[entry.key];
        if (typeof value === "boolean") {
          return (
            <div key={entry.key} className="space-y-2 rounded-lg border border-zinc-100 bg-zinc-50/40 px-4 py-3">
              <SwitchRow
                title={entry.label}
                description={entry.description || entry.key}
                enabled={value}
                onToggle={() => onChange(entry.key, !value)}
              />
              <div className="flex flex-wrap items-center gap-1.5">
                <SourcePill source={entry.source} />
                <span className="rounded-md border border-zinc-200 bg-white px-2 py-0.5 text-[11px] text-zinc-400">
                  默认：{displayValue({ ...entry, value: entry.default_value })}
                </span>
              </div>
            </div>
          );
        }

        return (
          <div key={entry.key} className="space-y-2 rounded-lg border border-zinc-100 bg-zinc-50/40 px-4 py-3">
            <div className="flex flex-wrap items-start justify-between gap-2">
              <div>
                <label className="block text-[13px] font-semibold text-zinc-700">{entry.label}</label>
                <div className="mt-0.5 font-mono text-[11px] text-zinc-400">{entry.key}</div>
              </div>
              <SourcePill source={entry.source} />
            </div>
            <TextInput
              value={value === null ? "" : String(value)}
              onChange={(next) => onChange(entry.key, parseInputValue(next, value))}
              placeholder={entry.default_value === null || entry.default_value === undefined ? "留空" : String(entry.default_value)}
              type={typeof value === "number" ? "number" : "text"}
            />
            <p className="text-[11px] leading-relaxed text-zinc-400">
              默认：{displayValue({ ...entry, value: entry.default_value })}
              {entry.description ? ` · ${entry.description}` : ""}
            </p>
          </div>
        );
      })}
    </div>
  );
}

function EnvGroupList({
  groups,
  values,
  onChange,
}: {
  groups: LocalEnvGroup[];
  values: Record<string, string>;
  onChange: (key: string, value: string) => void;
}) {
  return (
    <div className="space-y-5">
      {groups.map((group) => (
        <div key={group.id} className="space-y-3">
          <SectionDivider label={group.label} />
          <div className="grid grid-cols-1 gap-4 md:grid-cols-2">
            {group.fields.map((field) => (
              <EnvInput
                key={field.key}
                field={field}
                value={values[field.key] ?? ""}
                onChange={(value) => onChange(field.key, value)}
              />
            ))}
          </div>
        </div>
      ))}
    </div>
  );
}

const contentVariants = {
  initial: { opacity: 0, y: 8 },
  animate: { opacity: 1, y: 0, transition: { duration: 0.22, ease: "easeOut" as const } },
  exit: { opacity: 0, y: -4, transition: { duration: 0.12 } },
};

export function SettingsPanel({ isOpen, onClose }: SettingsModalProps) {
  const { settings, updateSettings } = useSettings();
  const [draft, setDraft] = useState<AppSettings>({ ...settings });
  const [activeSection, setActiveSection] = useState<SectionType>("connection");
  const [saveState, setSaveState] = useState<SaveState>("idle");
  const [saveError, setSaveError] = useState<string | null>(null);
  const [connectionStatus, setConnectionStatus] = useState<ConnectionStatus>("idle");
  const [connectionMessage, setConnectionMessage] = useState("");
  const [isTestingConnection, setIsTestingConnection] = useState(false);
  const [overview, setOverview] = useState<SettingsOverviewData | null>(null);
  const [isOverviewLoading, setIsOverviewLoading] = useState(false);
  const [overviewError, setOverviewError] = useState<string | null>(null);
  const [settingsDraft, setSettingsDraft] = useState<Record<string, SettingPrimitive>>({});
  const [savedSettingsDraft, setSavedSettingsDraft] = useState<Record<string, SettingPrimitive>>({});
  const [defaultSettingsDraft, setDefaultSettingsDraft] = useState<Record<string, SettingPrimitive>>({});

  useEffect(() => {
    if (!isOpen) return;
    setDraft({ ...settings });
    setActiveSection("connection");
    setSaveState("idle");
    setSaveError(null);
    setConnectionStatus("idle");
    setConnectionMessage("");
    setOverviewError(null);
  }, [isOpen, settings]);

  useEffect(() => {
    if (!isOpen) return;
    let cancelled = false;

    async function loadOverview() {
      setIsOverviewLoading(true);
      setOverviewError(null);
      try {
        const response = await apiClient<ApiResponse<SettingsOverviewData>>({
          url: "/api/v1/system/settings",
          method: "POST",
          data: {},
        });
        if (cancelled) return;
        setOverview(response.data);
        const entries = editableEntries(response.data.sections ?? []);
        const nextDraft = draftFromEntries(entries);
        setSettingsDraft(nextDraft);
        setSavedSettingsDraft(nextDraft);
        setDefaultSettingsDraft(draftFromEntries(entries, "default_value"));
      } catch (error) {
        if (!cancelled) {
          setOverviewError(getApiErrorMessage(error, "读取后端设置失败，请确认后端服务可用。"));
        }
      } finally {
        if (!cancelled) {
          setIsOverviewLoading(false);
        }
      }
    }

    void loadOverview();
    return () => {
      cancelled = true;
    };
  }, [isOpen]);

  useEffect(() => {
    if (!isOpen) return;
    const onEsc = (event: KeyboardEvent) => {
      if (event.key === "Escape") onClose();
    };
    document.addEventListener("keydown", onEsc);
    return () => document.removeEventListener("keydown", onEsc);
  }, [isOpen, onClose]);

  const activeSectionConfig = useMemo(
    () => SECTIONS.find((section) => section.id === activeSection) ?? SECTIONS[0],
    [activeSection],
  );
  const sectionMap = useMemo(
    () => Object.fromEntries((overview?.sections ?? []).map((section) => [section.id, section] as const)),
    [overview],
  );
  const allEditableEntries = useMemo(() => editableEntries(overview?.sections ?? []), [overview]);
  const getEntries = (...ids: string[]) => ids.flatMap((id) => sectionMap[id]?.entries ?? []);
  const hasLocalChanges = JSON.stringify(draft) !== JSON.stringify(settings);
  const hasServerChanges = !sameDraft(settingsDraft, savedSettingsDraft);
  const hasChanges = hasLocalChanges || hasServerChanges;
  const llmConfigured = Boolean((draft.localEnv.LLM_API_KEY ?? "").trim());

  const patch = <K extends keyof AppSettings>(key: K, value: AppSettings[K]) => {
    setDraft((prev) => ({ ...prev, [key]: value }));
  };

  const patchEnvVar = (key: string, value: string) => {
    setDraft((prev) => ({
      ...prev,
      localEnv: {
        ...prev.localEnv,
        [key]: value,
      },
      apiUrl: key === "VITE_API_URL" ? value : prev.apiUrl,
      useMock: key === "VITE_USE_MOCK" ? value.trim().toLowerCase() === "true" : prev.useMock,
      mineruApiToken: key === "MINERU_API_TOKEN" ? value : prev.mineruApiToken,
    }));
  };

  const patchServerSetting = (key: string, value: SettingPrimitive) => {
    setSettingsDraft((prev) => ({ ...prev, [key]: value }));
  };

  const saveSettings = async () => {
    setSaveState("saving");
    setSaveError(null);
    updateSettings(draft);

    if (!hasServerChanges) {
      setSaveState("saved");
      window.setTimeout(() => setSaveState("idle"), 1400);
      return;
    }

    try {
      const reset = sameDraft(settingsDraft, defaultSettingsDraft);
      const response = await apiClient<ApiResponse<SettingsOverviewData>>({
        url: "/api/v1/system/settings",
        method: "PATCH",
        data: {
          settings: reset ? {} : buildSettingsPayload(settingsDraft, allEditableEntries),
          reset,
        },
      });
      setOverview(response.data);
      const entries = editableEntries(response.data.sections ?? []);
      const nextDraft = draftFromEntries(entries);
      setSettingsDraft(nextDraft);
      setSavedSettingsDraft(nextDraft);
      setDefaultSettingsDraft(draftFromEntries(entries, "default_value"));
      setSaveState("saved");
      window.setTimeout(() => setSaveState("idle"), 1400);
    } catch (error) {
      setSaveState("error");
      setSaveError(getApiErrorMessage(error, "保存用户 settings 失败。"));
    }
  };

  const testConnection = async () => {
    const key = (draft.localEnv.LLM_API_KEY ?? "").trim();
    if (!key) {
      setConnectionStatus("error");
      setConnectionMessage("请先填写 LLM_API_KEY。");
      return;
    }
    setIsTestingConnection(true);
    setConnectionStatus("idle");
    setConnectionMessage("");
    const endpoint = `${((draft.localEnv.LLM_BASE_URL ?? "").trim() || DEFAULT_PROVIDER_BASE_URL).replace(/\/$/, "")}/models`;
    try {
      const response = await fetch(endpoint, { method: "GET", headers: { Authorization: `Bearer ${key}` } });
      setConnectionStatus(response.ok ? "success" : "error");
      setConnectionMessage(response.ok ? "连接成功：models 接口可访问。" : `连接失败：HTTP ${response.status}`);
    } catch (error) {
      setConnectionStatus("error");
      setConnectionMessage(error instanceof Error ? error.message : "连接失败，请检查网络。");
    } finally {
      setIsTestingConnection(false);
    }
  };

  const renderConnection = () => (
    <div className="space-y-5">
      <InfoCard text="先保证前端能连到后端，后端能连到模型。这里的密钥只保存在当前浏览器。" />
      <EnvGroupList groups={CONNECTION_ENV_GROUPS} values={draft.localEnv} onChange={patchEnvVar} />
      <div className="flex flex-wrap items-center gap-2">
        <button
          type="button"
          onClick={testConnection}
          disabled={isTestingConnection}
          className="inline-flex h-[38px] items-center gap-1.5 rounded-lg border border-zinc-200 bg-white px-3 text-[12px] font-medium text-zinc-600 transition hover:text-zinc-900 disabled:opacity-50"
        >
          {isTestingConnection ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <Sparkles className="h-3.5 w-3.5" />}
          测试 LLM
        </button>
      </div>
      <AnimatePresence>
        {connectionStatus !== "idle" ? (
          <motion.div
            initial={{ opacity: 0, height: 0 }}
            animate={{ opacity: 1, height: "auto" }}
            exit={{ opacity: 0, height: 0 }}
            className={`overflow-hidden rounded-lg border px-4 py-3 text-[12px] leading-relaxed ${
              connectionStatus === "success"
                ? "border-emerald-200 bg-emerald-50/60 text-emerald-700"
                : "border-red-200 bg-red-50/60 text-red-600"
            }`}
          >
            {connectionMessage}
          </motion.div>
        ) : null}
      </AnimatePresence>
      <SectionDivider label="后端当前状态" />
      <ReadonlySettingsList
        entries={getEntries("runtime", "models").filter((entry) => CORE_STATUS_KEYS.has(entry.key))}
        loading={isOverviewLoading}
        error={overviewError}
      />
    </div>
  );

  const renderModels = () => (
    <div className="space-y-5">
      <InfoCard text="模型名是用户级 settings，保存后进入用户数据库；LLM_API_KEY 和 LLM_BASE_URL 仍只在环境变量里。" />
      <EditableSettingsList
        entries={getEntries("models").filter((entry) => MODEL_KEYS.has(entry.key))}
        draft={settingsDraft}
        onChange={patchServerSetting}
        loading={isOverviewLoading}
        error={overviewError}
      />
      <SectionDivider label="运行推导" />
      <ReadonlySettingsList
        entries={getEntries("models").filter((entry) => entry.key === "models.embedding_dim")}
        loading={isOverviewLoading}
        error={overviewError}
      />
    </div>
  );

  const renderLearning = () => (
    <div className="space-y-5">
      <InfoCard text="这里配置资料解析、知识构建、伴读上下文和知识图谱这些学习流程本身。" />
      <EditableSettingsList
        entries={getEntries("learning_engines").filter((entry) => hasAnyPrefix(entry.key, LEARNING_SETTING_PREFIXES))}
        draft={settingsDraft}
        onChange={patchServerSetting}
        loading={isOverviewLoading}
        error={overviewError}
      />
      <SectionDivider label="解析服务密钥" />
      <EnvGroupList groups={LEARNING_ENV_GROUPS} values={draft.localEnv} onChange={patchEnvVar} />
      <SectionDivider label="上传时解析偏好" />
      <div className="space-y-3">
        <SelectInput
          value={draft.parserProvider}
          onChange={(value) => patch("parserProvider", value as ParserProvider)}
          options={[
            { value: "docling", label: "Docling" },
            { value: "unstructured", label: "Unstructured" },
            { value: "mineru", label: "MinerU" },
          ]}
        />
        {draft.parserProvider === "mineru" ? (
          <div className="space-y-3 rounded-lg border border-zinc-100 bg-zinc-50/40 p-4">
            <TextInput
              type="password"
              value={draft.mineruApiToken}
              onChange={(value) => patchEnvVar("MINERU_API_TOKEN", value)}
              placeholder="MINERU_API_TOKEN"
            />
            <SelectInput
              value={draft.mineruModelVersion}
              onChange={(value) => patch("mineruModelVersion", value as MinerUModelVersion)}
              options={[
                { value: "vlm", label: "vlm" },
                { value: "pipeline", label: "pipeline" },
              ]}
            />
            <SwitchRow title="公式识别" description="上传时传给 MinerU。" enabled={draft.mineruEnableFormula} onToggle={() => patch("mineruEnableFormula", !draft.mineruEnableFormula)} />
            <SwitchRow title="表格识别" description="上传时传给 MinerU。" enabled={draft.mineruEnableTable} onToggle={() => patch("mineruEnableTable", !draft.mineruEnableTable)} />
            <SwitchRow title="OCR" description="上传扫描件时启用。" enabled={draft.mineruIsOcr} onToggle={() => patch("mineruIsOcr", !draft.mineruIsOcr)} />
          </div>
        ) : null}
      </div>
    </div>
  );

  const renderSearch = () => (
    <div className="space-y-5">
      <InfoCard text="这里配置本地 RAG、联网检索、Rerank、reader 和各类搜索 provider。" />
      <EditableSettingsList
        entries={getEntries("search").filter((entry) => hasAnyPrefix(entry.key, SEARCH_SETTING_PREFIXES))}
        draft={settingsDraft}
        onChange={patchServerSetting}
        loading={isOverviewLoading}
        error={overviewError}
      />
      <SectionDivider label="搜索服务密钥" />
      <EnvGroupList groups={SEARCH_ENV_GROUPS} values={draft.localEnv} onChange={patchEnvVar} />
      <SectionDivider label="后端 provider 状态" />
      <ReadonlySettingsList
        entries={getEntries("search").filter((entry) => entry.source === "env")}
        loading={isOverviewLoading}
        error={overviewError}
      />
    </div>
  );

  const renderOps = () => (
    <div className="space-y-5">
      <InfoCard text="账号、邮件、数据库和对象存储属于部署与数据层配置；敏感项只保存在当前浏览器。" />
      <EnvGroupList groups={OPS_ENV_GROUPS} values={draft.localEnv} onChange={patchEnvVar} />
      <SectionDivider label="后端当前状态" />
      <ReadonlySettingsList
        entries={getEntries("runtime", "storage").filter((entry) => STORAGE_STATUS_KEYS.has(entry.key) || CORE_STATUS_KEYS.has(entry.key))}
        loading={isOverviewLoading}
        error={overviewError}
      />
    </div>
  );

  const renderObservability = () => (
    <div className="space-y-5">
      <InfoCard text="这里配置 trace、LLM 调用统计和当前浏览器的调试开关。" />
      <EnvGroupList groups={OBSERVABILITY_ENV_GROUPS} values={draft.localEnv} onChange={patchEnvVar} />
      <EditableSettingsList
        entries={getEntries("observability").filter((entry) => entry.editable && hasAnyPrefix(entry.key, OBSERVABILITY_SETTING_PREFIXES))}
        draft={settingsDraft}
        onChange={patchServerSetting}
        loading={isOverviewLoading}
        error={overviewError}
      />
      <SectionDivider label="前端本机" />
      <SwitchRow title="调试模式" description="只影响当前浏览器。" enabled={draft.debugMode} onToggle={() => patch("debugMode", !draft.debugMode)} />
      <SectionDivider label="后端观测状态" />
      <ReadonlySettingsList
        entries={getEntries("observability").filter((entry) => OBSERVABILITY_ENV_STATUS_KEYS.has(entry.key))}
        loading={isOverviewLoading}
        error={overviewError}
      />
    </div>
  );

  const renderers: Record<SectionType, () => React.ReactNode> = {
    connection: renderConnection,
    models: renderModels,
    learning: renderLearning,
    search: renderSearch,
    ops: renderOps,
    observability: renderObservability,
  };

  if (!isOpen) return null;

  return (
    <AnimatePresence>
      <motion.div
        initial={{ opacity: 0 }}
        animate={{ opacity: 1 }}
        exit={{ opacity: 0 }}
        transition={{ duration: 0.18 }}
        className="fixed inset-0 z-[100]"
      >
        <div className="absolute inset-0 bg-black/40 backdrop-blur-sm" onClick={onClose} />
        <div className="pointer-events-none absolute inset-0 flex items-center justify-center p-4 sm:p-8">
          <motion.div
            initial={{ opacity: 0, y: 16, scale: 0.97 }}
            animate={{ opacity: 1, y: 0, scale: 1 }}
            exit={{ opacity: 0, y: 10, scale: 0.97 }}
            transition={{ type: "spring", stiffness: 400, damping: 32 }}
            className="pointer-events-auto flex h-[min(720px,85vh)] w-full max-w-[880px] overflow-hidden rounded-lg border border-zinc-200/60 bg-white shadow-[0_25px_80px_-20px_rgba(0,0,0,0.35)]"
          >
            <nav className="flex w-[210px] shrink-0 flex-col border-r border-zinc-100 bg-zinc-50/70">
              <div className="px-5 pb-4 pt-5">
                <h2 className="text-[15px] font-bold text-zinc-900">设置</h2>
              </div>
              <div className="flex-1 space-y-0.5 overflow-y-auto px-2.5">
                {SECTIONS.map((section) => {
                  const Icon = section.icon;
                  const active = activeSection === section.id;
                  return (
                    <button
                      key={section.id}
                      type="button"
                      onClick={() => setActiveSection(section.id)}
                      className={`flex w-full items-center gap-2.5 rounded-lg px-3 py-2.5 text-left transition ${
                        active ? "bg-white text-zinc-900 shadow-[0_1px_3px_rgba(0,0,0,0.06)]" : "text-zinc-500 hover:bg-white/60 hover:text-zinc-700"
                      }`}
                    >
                      <span className={`inline-flex h-8 w-8 items-center justify-center rounded-lg ${active ? "bg-zinc-900 text-white" : "bg-zinc-100 text-zinc-400"}`}>
                        <Icon className="h-4 w-4" />
                      </span>
                      <span>
                        <span className="block text-[13px] font-medium">{section.label}</span>
                        <span className="block text-[11px] text-zinc-400">{section.description}</span>
                      </span>
                    </button>
                  );
                })}
              </div>
              <div className="flex flex-wrap gap-1.5 border-t border-zinc-100 px-4 py-3">
                <span className={`inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-[10px] font-medium ${llmConfigured ? "bg-emerald-50 text-emerald-600" : "bg-amber-50 text-amber-600"}`}>
                  <span className={`h-1.5 w-1.5 rounded-full ${llmConfigured ? "bg-emerald-500" : "bg-amber-500"}`} />
                  {llmConfigured ? "LLM Key" : "缺少 LLM Key"}
                </span>
                <span className={`inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-[10px] font-medium ${draft.useMock ? "bg-amber-50 text-amber-600" : "bg-emerald-50 text-emerald-600"}`}>
                  <span className={`h-1.5 w-1.5 rounded-full ${draft.useMock ? "bg-amber-500" : "bg-emerald-500"}`} />
                  {draft.useMock ? "Mock" : "真实后端"}
                </span>
              </div>
            </nav>

            <div className="flex min-w-0 flex-1 flex-col">
              <div className="flex items-center justify-between border-b border-zinc-100 px-6 py-4">
                <div>
                  <h3 className="text-[16px] font-bold text-zinc-900">{activeSectionConfig.label}</h3>
                  <p className="mt-0.5 text-[12px] text-zinc-400">{activeSectionConfig.description}</p>
                </div>
                <button
                  type="button"
                  onClick={onClose}
                  className="inline-flex h-8 w-8 items-center justify-center rounded-lg text-zinc-400 transition hover:bg-zinc-100 hover:text-zinc-600"
                  aria-label="关闭设置"
                >
                  <X className="h-4 w-4" />
                </button>
              </div>

              <div className="min-h-0 flex-1 overflow-y-auto px-6 py-5">
                <AnimatePresence mode="wait">
                  <motion.div key={activeSection} variants={contentVariants} initial="initial" animate="animate" exit="exit">
                    {renderers[activeSection]()}
                  </motion.div>
                </AnimatePresence>
              </div>

              <div className="flex items-center justify-between border-t border-zinc-100 bg-zinc-50/50 px-6 py-3">
                <div className="text-[12px] text-zinc-400">
                  <AnimatePresence mode="wait">
                    {saveState === "saving" ? (
                      <motion.span key="saving" initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }} className="flex items-center gap-1.5 text-zinc-600">
                        <Loader2 className="h-3.5 w-3.5 animate-spin" /> 正在保存
                      </motion.span>
                    ) : saveState === "error" ? (
                      <motion.span key="error" initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }} className="flex items-center gap-1.5 text-red-600">
                        <RefreshCcw className="h-3.5 w-3.5" /> {saveError ?? "保存失败"}
                      </motion.span>
                    ) : saveState === "saved" ? (
                      <motion.span key="saved" initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }} className="flex items-center gap-1.5 text-emerald-600">
                        <CheckCircle2 className="h-3.5 w-3.5" /> 已保存
                      </motion.span>
                    ) : hasChanges ? (
                      <motion.span key="changed" initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }} className="flex items-center gap-1.5 text-amber-600">
                        <RefreshCcw className="h-3.5 w-3.5" /> 有未保存修改
                      </motion.span>
                    ) : (
                      <motion.span key="synced" initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }} className="flex items-center gap-1.5">
                        <CheckCircle2 className="h-3.5 w-3.5" /> 已同步
                      </motion.span>
                    )}
                  </AnimatePresence>
                </div>

                <div className="flex items-center gap-2">
                  <button
                    type="button"
                    onClick={() => {
                      const nextDraft = { ...DEFAULT_SETTINGS };
                      setDraft(nextDraft);
                      setSettingsDraft(defaultSettingsDraft);
                      setSaveError(null);
                    }}
                    className="rounded-lg px-3 py-1.5 text-[12px] font-medium text-zinc-500 transition hover:bg-zinc-100 hover:text-zinc-700"
                  >
                    恢复默认
                  </button>
                  <button
                    type="button"
                    onClick={saveSettings}
                    disabled={!hasChanges || saveState === "saving"}
                    className={`rounded-lg px-4 py-1.5 text-[12px] font-semibold transition ${
                      hasChanges && saveState !== "saving"
                        ? "bg-zinc-900 text-white hover:bg-zinc-800"
                        : "cursor-not-allowed bg-zinc-100 text-zinc-300"
                    }`}
                  >
                    {saveState === "saving" ? "保存中" : "保存设置"}
                  </button>
                </div>
              </div>
            </div>
          </motion.div>
        </div>
      </motion.div>
    </AnimatePresence>
  );
}
