import { type ReactNode, useEffect, useMemo, useState } from "react";
import { AnimatePresence, motion } from "framer-motion";
import {
  Activity,
  Bot,
  CheckCircle2,
  Database,
  Loader2,
  Monitor,
  RefreshCcw,
  Search,
  SlidersHorizontal,
  Wrench,
  X,
} from "lucide-react";

import { DEFAULT_SETTINGS, type AppSettings, useSettings } from "../../hooks/useSettings";
import { apiClient, getApiErrorMessage } from "../../api/client";
import {
  getStoredSystemSettingsOverview,
  storeSystemSettingsOverview,
} from "../../lib/systemSettings";

interface SettingsModalProps {
  isOpen: boolean;
  onClose: () => void;
}

type SectionType = "device" | "models" | "learning" | "search" | "deploy" | "observability";
type SaveState = "idle" | "saving" | "saved" | "error";
type SettingSource = "env" | "settings" | "system_settings" | "user_settings" | "runtime";
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
  restart_required?: boolean;
  derived?: boolean;
  description?: string;
}

interface SettingSection {
  id: string;
  label: string;
  description: string;
  entries?: SettingEntry[];
}

interface SettingsOverviewData {
  settings_source: string;
  mode: string;
  sections?: SettingSection[];
  notes?: string[];
}

interface ApiResponse<T> {
  code: number;
  message: string;
  data: T;
}

const SECTIONS = [
  { id: "device", label: "当前设备", description: "浏览器本机项", icon: Monitor },
  { id: "models", label: "AI 与模型", description: "模型路由与推导", icon: Bot },
  { id: "learning", label: "学习构建", description: "上传、规划与文档生成", icon: Wrench },
  { id: "search", label: "检索与来源", description: "RAG、联网与检索服务", icon: Search },
  { id: "deploy", label: "部署与集成", description: "运行模式、鉴权、存储", icon: Database },
  { id: "observability", label: "观测与性能", description: "追踪、并发与调优", icon: Activity },
] as const;

const MODEL_BASIC_KEYS = new Set([
  "models.primary",
  "models.reason",
  "models.light",
  "models.embedding",
]);

const MODEL_KEYS = new Set([
  "models.primary",
  "models.reason",
  "models.light",
  "models.extract",
  "models.embedding",
  "models.ocr",
  "models.image_generation",
]);

const DEPLOY_RUNTIME_KEYS = new Set([
  "runtime.mode",
  "runtime.app_mode_raw",
  "runtime.version",
  "auth.enabled",
  "settings.source",
]);

const LLM_PROVIDER_STATUS_KEYS = new Set([
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

const INGEST_BASIC_KEYS = new Set([
  "ingest.default_parser_provider",
  "ingest.mineru_model_version",
  "ingest.mineru_enable_formula",
  "ingest.mineru_enable_table",
  "ingest.mineru_is_ocr",
]);

const DOCGEN_BASIC_KEYS = new Set([
  "docgen.allow_external_search",
  "docgen.generate_cover_image",
]);

const LEARNING_LINKAGE_KEYS = new Set([
  "interact.history_turns",
  "knowledge_graph.sync_after_docgen",
]);

const SEARCH_STRATEGY_KEYS = new Set([
  "rag.top_k",
  "rag.similarity_threshold",
  "rag.rerank_model",
  "rag.rerank_top_k",
  "local_rag.priority",
  "local_rag.min_results",
  "search.retriever_profile",
]);

const SEARCH_PROVIDER_BASIC_KEYS = new Set([
  "search.tavily_key",
  "search.jina_key",
  "search.serper_key",
  "search.mcp_tool",
  "rag.rerank_api_key",
]);

const OBSERVABILITY_BASIC_KEYS = new Set([
  "observability.tracing_enabled",
  "observability.llm_token_summary_enabled",
  "observability.llm_observability_enabled",
]);

const PERFORMANCE_BASIC_KEYS = new Set([
  "runtime.llm_concurrency_limit",
]);

const LEARNING_SETTING_PREFIXES = ["ingest.", "planner.", "docgen.", "interact.", "knowledge_graph."];
const SEARCH_SETTING_PREFIXES = ["rag.", "local_rag.", "search."];
const OBSERVABILITY_SETTING_PREFIXES = ["observability.", "runtime.", "embedding."];

const SETTING_SELECT_OPTIONS: Record<string, Array<{ value: string; label: string }>> = {
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

function hasAnyPrefix(key: string, prefixes: string[]): boolean {
  return prefixes.some((prefix) => key.startsWith(prefix));
}

function splitEntriesByKeys(entries: SettingEntry[], basicKeys: Set<string>) {
  return {
    basic: entries.filter((entry) => basicKeys.has(entry.key)),
    advanced: entries.filter((entry) => !basicKeys.has(entry.key)),
  };
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

function editableEntries(sections: SettingSection[], source?: SettingSource) {
  return sections
    .flatMap((section) => section.entries ?? [])
    .filter((entry) => entry.editable && isPrimitive(entry.value) && (!source || entry.source === source));
}

function draftFromEntries(
  entries: SettingEntry[],
  source: "value" | "default_value" = "value",
) {
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

function buildChangedSettingsPayload(
  draft: Record<string, SettingPrimitive>,
  defaults: Record<string, SettingPrimitive>,
  entries: SettingEntry[],
) {
  const changedDraft = Object.fromEntries(
    Object.entries(draft).filter(([key, value]) => value !== defaults[key]),
  ) as Record<string, SettingPrimitive>;
  return buildSettingsPayload(changedDraft, entries);
}

function buildChangedFlatPayload(
  draft: Record<string, SettingPrimitive>,
  saved: Record<string, SettingPrimitive>,
) {
  return Object.fromEntries(
    Object.entries(draft)
      .filter(([key, value]) => value !== saved[key])
      .map(([key, value]) => [key, value === null ? "" : String(value)]),
  ) as Record<string, string>;
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
      : source === "system_settings"
        ? "系统库"
      : source === "user_settings"
        ? "用户库"
        : source === "settings"
          ? "默认"
      : "运行时";
  return <span className="rounded-md border border-zinc-200 bg-white px-2 py-0.5 text-[11px] font-semibold text-zinc-500">{label}</span>;
}

function ScopePill({ entry }: { entry: SettingEntry }) {
  const label =
    entry.source === "env"
      ? "部署级"
      : entry.source === "runtime" || entry.derived
        ? "诊断值"
        : "服务端运行时";
  return <span className="rounded-md border border-zinc-200 bg-white px-2 py-0.5 text-[11px] text-zinc-500">{label}</span>;
}

function EffectPill({ entry }: { entry: SettingEntry }) {
  const label = entry.derived
    ? "只读"
    : entry.restart_required
      ? "建议重启"
      : "即时生效";
  const className = entry.restart_required
    ? "border-amber-200 bg-amber-50 text-amber-700"
    : "border-zinc-200 bg-white text-zinc-500";
  return <span className={`rounded-md px-2 py-0.5 text-[11px] ${className}`}>{label}</span>;
}

function SettingsGroup({
  title,
  description,
  children,
}: {
  title: string;
  description?: string;
  children: ReactNode;
}) {
  return (
    <section className="space-y-3 rounded-xl border border-zinc-100 bg-zinc-50/35 p-4">
      <div className="space-y-1">
        <h4 className="text-[13px] font-semibold text-zinc-800">{title}</h4>
        {description ? <p className="text-[11px] leading-relaxed text-zinc-500">{description}</p> : null}
      </div>
      {children}
    </section>
  );
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
            <div className="flex flex-wrap items-center gap-1.5">
              <SourcePill source={entry.source} />
              <ScopePill entry={entry} />
              <EffectPill entry={entry} />
            </div>
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
  if (loading) return <InfoCard text="正在读取可编辑设置..." />;
  if (error) return <InfoCard text={error} variant="warning" />;
  if (!items.length) return <InfoCard text="当前模式下暂无可编辑项。" />;

  return (
    <div className="space-y-3">
      {items.map((entry) => {
        const value = draft[entry.key];
        const selectOptions = SETTING_SELECT_OPTIONS[entry.key];

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
                <ScopePill entry={entry} />
                <EffectPill entry={entry} />
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
              <div className="flex flex-wrap items-center gap-1.5">
                <SourcePill source={entry.source} />
                <ScopePill entry={entry} />
                <EffectPill entry={entry} />
              </div>
            </div>
            {selectOptions ? (
              <SelectInput
                value={value === null ? "" : String(value)}
                onChange={(next) => onChange(entry.key, next)}
                options={selectOptions}
              />
            ) : (
              <TextInput
                value={value === null ? "" : String(value)}
                onChange={(next) => onChange(entry.key, parseInputValue(next, value))}
                placeholder={
                  entry.default_value === null || entry.default_value === undefined
                    ? "留空"
                    : String(entry.default_value)
                }
                type={typeof value === "number" ? "number" : "text"}
              />
            )}
            <p className="text-[11px] leading-relaxed text-zinc-400">
              默认：{displayValue({ ...entry, value: entry.default_value })}
              {entry.description ? ` · ${entry.description}` : ""}
              {entry.restart_required ? " · 保存后建议重启" : ""}
            </p>
          </div>
        );
      })}
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
  const [activeSection, setActiveSection] = useState<SectionType>("device");
  const [showAdvanced, setShowAdvanced] = useState(false);
  const [saveState, setSaveState] = useState<SaveState>("idle");
  const [saveError, setSaveError] = useState<string | null>(null);
  const [overview, setOverview] = useState<SettingsOverviewData | null>(() => getStoredSystemSettingsOverview());
  const [isOverviewLoading, setIsOverviewLoading] = useState(false);
  const [overviewError, setOverviewError] = useState<string | null>(null);
  const [settingsDraft, setSettingsDraft] = useState<Record<string, SettingPrimitive>>({});
  const [savedSettingsDraft, setSavedSettingsDraft] = useState<Record<string, SettingPrimitive>>({});
  const [defaultSettingsDraft, setDefaultSettingsDraft] = useState<Record<string, SettingPrimitive>>({});
  const [envDraft, setEnvDraft] = useState<Record<string, SettingPrimitive>>({});
  const [savedEnvDraft, setSavedEnvDraft] = useState<Record<string, SettingPrimitive>>({});

  useEffect(() => {
    if (!isOpen) return;
    setDraft({ ...settings });
    setActiveSection("device");
    setSaveState("idle");
    setSaveError(null);
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
        storeSystemSettingsOverview(response.data);
        const nextSettingEntries = editableEntries(response.data.sections ?? [], "settings").concat(
          editableEntries(response.data.sections ?? [], "system_settings"),
        );
        const nextEnvEntries = editableEntries(response.data.sections ?? [], "env");
        const nextSettingsDraft = draftFromEntries(nextSettingEntries);
        const nextEnvDraft = draftFromEntries(nextEnvEntries);
        setSettingsDraft(nextSettingsDraft);
        setSavedSettingsDraft(nextSettingsDraft);
        setDefaultSettingsDraft(draftFromEntries(nextSettingEntries, "default_value"));
        setEnvDraft(nextEnvDraft);
        setSavedEnvDraft(nextEnvDraft);
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

  const runtimeMode = overview?.mode ?? getStoredSystemSettingsOverview()?.mode ?? "local";
  const isLocalRuntime = runtimeMode === "local";
  const parserProvider =
    String(settingsDraft["ingest.default_parser_provider"] ?? defaultSettingsDraft["ingest.default_parser_provider"] ?? "auto");
  const activeSectionConfig = useMemo(
    () => SECTIONS.find((section) => section.id === activeSection) ?? SECTIONS[0],
    [activeSection],
  );
  const sectionMap = useMemo(
    () => Object.fromEntries((overview?.sections ?? []).map((section) => [section.id, section] as const)),
    [overview],
  );
  const getEntries = (...ids: string[]) => ids.flatMap((id) => sectionMap[id]?.entries ?? []);
  const editableSettingEntries = useMemo(
    () => editableEntries(overview?.sections ?? [], "settings").concat(editableEntries(overview?.sections ?? [], "system_settings")),
    [overview],
  );
  const hasLocalChanges = JSON.stringify(draft) !== JSON.stringify(settings);
  const hasServerChanges = !sameDraft(settingsDraft, savedSettingsDraft);
  const hasEnvChanges = !sameDraft(envDraft, savedEnvDraft);
  const hasChanges = hasLocalChanges || hasServerChanges || hasEnvChanges;

  const patch = <K extends keyof AppSettings>(key: K, value: AppSettings[K]) => {
    setDraft((prev) => ({ ...prev, [key]: value }));
  };

  const patchServerSetting = (key: string, value: SettingPrimitive) => {
    setSettingsDraft((prev) => ({ ...prev, [key]: value }));
  };

  const patchEnvSetting = (key: string, value: SettingPrimitive) => {
    setEnvDraft((prev) => ({ ...prev, [key]: value }));
  };

  const saveSettings = async () => {
    setSaveState("saving");
    setSaveError(null);
    updateSettings(draft);

    if (!hasServerChanges && !hasEnvChanges) {
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
          settings: reset
            ? {}
            : buildChangedSettingsPayload(settingsDraft, defaultSettingsDraft, editableSettingEntries),
          env: buildChangedFlatPayload(envDraft, savedEnvDraft),
          reset,
        },
      });
      setOverview(response.data);
      storeSystemSettingsOverview(response.data);
      const nextSettingEntries = editableEntries(response.data.sections ?? [], "settings").concat(
        editableEntries(response.data.sections ?? [], "system_settings"),
      );
      const nextEnvEntries = editableEntries(response.data.sections ?? [], "env");
      const nextSettingsDraft = draftFromEntries(nextSettingEntries);
      const nextEnvDraft = draftFromEntries(nextEnvEntries);
      setSettingsDraft(nextSettingsDraft);
      setSavedSettingsDraft(nextSettingsDraft);
      setDefaultSettingsDraft(draftFromEntries(nextSettingEntries, "default_value"));
      setEnvDraft(nextEnvDraft);
      setSavedEnvDraft(nextEnvDraft);
      setSaveState("saved");
      window.setTimeout(() => setSaveState("idle"), 1400);
    } catch (error) {
      setSaveState("error");
      setSaveError(getApiErrorMessage(error, "保存设置失败。"));
    }
  };

  const renderDevice = () => (
    <div className="space-y-5">
      <InfoCard text="这里只影响当前浏览器或本机调试体验，不会写入服务端运行时真相。" />
      <SettingsGroup title="当前浏览器" description="浏览器本机项始终只对你现在使用的这台设备生效。">
        <div className="space-y-3">
          <div className="space-y-2 rounded-lg border border-zinc-100 bg-white px-4 py-3">
            <label className="text-[13px] font-semibold text-zinc-700">后端地址</label>
            <TextInput value={draft.apiUrl} onChange={(value) => patch("apiUrl", value)} placeholder="http://localhost:8000" />
            <p className="text-[11px] leading-relaxed text-zinc-400">只影响当前浏览器请求哪个后端服务。</p>
          </div>
          <SwitchRow
            title="启用本地 Mock"
            description="只影响当前浏览器是否使用前端 Mock 数据。"
            enabled={draft.useMock}
            onToggle={() => patch("useMock", !draft.useMock)}
          />
          <SwitchRow
            title="调试模式"
            description="只影响当前浏览器的调试展示和开发辅助体验。"
            enabled={draft.debugMode}
            onToggle={() => patch("debugMode", !draft.debugMode)}
          />
          <div className="space-y-2 rounded-lg border border-zinc-100 bg-white px-4 py-3">
            <label className="text-[13px] font-semibold text-zinc-700">MinerU 临时令牌</label>
            <TextInput
              type="password"
              value={draft.mineruApiToken}
              onChange={(value) => patch("mineruApiToken", value)}
              placeholder="MINERU_API_TOKEN"
            />
            <p className="text-[11px] leading-relaxed text-zinc-400">
              仅当前浏览器可见。上传时会优先使用这个临时令牌；留空则回退到服务端环境变量。
            </p>
          </div>
        </div>
      </SettingsGroup>
      {overview?.notes?.length ? (
        <SettingsGroup title="说明" description="帮助你理解当前设置来源与保存方式。">
          <div className="space-y-2">
            {overview.notes.map((note) => (
              <InfoCard key={note} text={note} />
            ))}
          </div>
        </SettingsGroup>
      ) : null}
    </div>
  );

  const renderModels = () => {
    const modelEntries = getEntries("models").filter((entry) => MODEL_KEYS.has(entry.key));
    const { basic: basicModelEntries, advanced: advancedModelEntries } = splitEntriesByKeys(modelEntries, MODEL_BASIC_KEYS);

    return (
      <div className="space-y-5">
        <InfoCard
          text={
            isLocalRuntime
              ? "这里集中放模型路由。常用项默认展示，专用模型放进高级设置；保存后会写入服务端运行时配置。"
              : "云端模式下模型路由只读展示，普通用户不能修改服务端全局模型配置。"
          }
        />
        <SettingsGroup title="核心路由" description="优先调整这里，通常就能满足大多数本地调试和日常使用。">
          <EditableSettingsList
            entries={basicModelEntries}
            draft={settingsDraft}
            onChange={patchServerSetting}
            loading={isOverviewLoading}
            error={overviewError}
          />
        </SettingsGroup>
        {(showAdvanced || advancedModelEntries.length === 0) ? null : (
          <InfoCard text="还有 OCR、抽取和图片生成等专用模型设置，点击右上角“显示高级”后展开。" />
        )}
        {showAdvanced && advancedModelEntries.length > 0 ? (
          <SettingsGroup title="专用模型" description="低频修改项，适合需要精细拆分任务模型时使用。">
            <EditableSettingsList
              entries={advancedModelEntries}
              draft={settingsDraft}
              onChange={patchServerSetting}
              loading={isOverviewLoading}
              error={overviewError}
            />
          </SettingsGroup>
        ) : null}
        <SettingsGroup title="运行推导" description="这些值来自当前路由配置推导，只读展示。">
          <ReadonlySettingsList
            entries={getEntries("models").filter((entry) => entry.key === "models.embedding_dim")}
            loading={isOverviewLoading}
            error={overviewError}
          />
        </SettingsGroup>
      </div>
    );
  };

  const renderLearning = () => {
    const learningEntries = getEntries("learning_engines").filter(
      (entry) => hasAnyPrefix(entry.key, LEARNING_SETTING_PREFIXES) && entry.source !== "env",
    );
    const ingestEntries = learningEntries.filter((entry) => entry.key.startsWith("ingest."));
    const plannerEntries = learningEntries.filter((entry) => entry.key.startsWith("planner."));
    const docgenEntries = learningEntries.filter((entry) => entry.key.startsWith("docgen."));
    const linkageEntries = learningEntries.filter(
      (entry) => entry.key.startsWith("interact.") || entry.key.startsWith("knowledge_graph."),
    );
    const { basic: basicIngestEntries, advanced: advancedIngestEntries } = splitEntriesByKeys(ingestEntries, INGEST_BASIC_KEYS);
    const { basic: basicDocgenEntries, advanced: advancedDocgenEntries } = splitEntriesByKeys(docgenEntries, DOCGEN_BASIC_KEYS);
    const { basic: basicLinkageEntries, advanced: advancedLinkageEntries } = splitEntriesByKeys(linkageEntries, LEARNING_LINKAGE_KEYS);
    const learningEnvEntries = getEntries("learning_engines").filter((entry) => entry.source === "env");

    return (
      <div className="space-y-5">
        <InfoCard
          text={
            isLocalRuntime
              ? "这页按学习链路组织配置：上传与解析、方案规划、知识文档生成，以及伴读/图谱联动。"
              : "云端模式下学习构建参数只读展示，普通用户不能修改服务端全局行为。"
          }
        />
        <SettingsGroup title="上传与解析" description="控制默认解析方式，以及上传时的基础行为。">
          <EditableSettingsList
            entries={basicIngestEntries}
            draft={settingsDraft}
            onChange={patchServerSetting}
            loading={isOverviewLoading}
            error={overviewError}
          />
        </SettingsGroup>
        {parserProvider === "auto" ? (
          <InfoCard text="当前是自动解析模式。上传时会先分类，再生成解析计划，然后按文件类型和质量策略选择本地解析器链。" />
        ) : null}
        {showAdvanced && advancedIngestEntries.length > 0 ? (
          <SettingsGroup title="解析高级项" description="并发、超时和上传上限等低频调优项。">
            <EditableSettingsList
              entries={advancedIngestEntries}
              draft={settingsDraft}
              onChange={patchServerSetting}
              loading={isOverviewLoading}
              error={overviewError}
            />
          </SettingsGroup>
        ) : null}
        <SettingsGroup title="方案规划" description="控制 Planner 默认采用的 Digest 模式与章节范围。">
          <EditableSettingsList
            entries={plannerEntries}
            draft={settingsDraft}
            onChange={patchServerSetting}
            loading={isOverviewLoading}
            error={overviewError}
          />
        </SettingsGroup>
        <SettingsGroup title="知识文档生成" description="控制 DocGen 的来源策略、封面开关与章节执行预算。">
          <EditableSettingsList
            entries={basicDocgenEntries}
            draft={settingsDraft}
            onChange={patchServerSetting}
            loading={isOverviewLoading}
            error={overviewError}
          />
        </SettingsGroup>
        {showAdvanced && advancedDocgenEntries.length > 0 ? (
          <SettingsGroup title="文档生成高级项" description="章节并发、研究查询数和网页读取预算等低层调优项。">
            <EditableSettingsList
              entries={advancedDocgenEntries}
              draft={settingsDraft}
              onChange={patchServerSetting}
              loading={isOverviewLoading}
              error={overviewError}
            />
          </SettingsGroup>
        ) : null}
        <SettingsGroup title="伴读与图谱联动" description="控制伴读上下文长度，以及生成文档后是否同步知识图谱。">
          <EditableSettingsList
            entries={basicLinkageEntries}
            draft={settingsDraft}
            onChange={patchServerSetting}
            loading={isOverviewLoading}
            error={overviewError}
          />
        </SettingsGroup>
        {showAdvanced && advancedLinkageEntries.length > 0 ? (
          <SettingsGroup title="联动高级项" description="知识图谱抽取并发等低频调优项。">
            <EditableSettingsList
              entries={advancedLinkageEntries}
              draft={settingsDraft}
              onChange={patchServerSetting}
              loading={isOverviewLoading}
              error={overviewError}
            />
          </SettingsGroup>
        ) : null}
        <SettingsGroup title={isLocalRuntime ? "服务端解析凭证" : "解析服务状态"} description="MinerU 等服务依赖的部署级环境变量。">
          {isLocalRuntime ? (
            <EditableSettingsList
              entries={learningEnvEntries}
              draft={envDraft}
              onChange={patchEnvSetting}
              loading={isOverviewLoading}
              error={overviewError}
            />
          ) : (
            <ReadonlySettingsList
              entries={learningEnvEntries}
              loading={isOverviewLoading}
              error={overviewError}
            />
          )}
        </SettingsGroup>
      </div>
    );
  };

  const renderSearch = () => {
    const searchEntries = getEntries("search").filter(
      (entry) => hasAnyPrefix(entry.key, SEARCH_SETTING_PREFIXES) && entry.source !== "env",
    );
    const searchEnvEntries = getEntries("search").filter((entry) => entry.source === "env");
    const { basic: basicSearchEntries, advanced: advancedSearchEntries } = splitEntriesByKeys(searchEntries, SEARCH_STRATEGY_KEYS);
    const { basic: basicSearchEnvEntries, advanced: advancedSearchEnvEntries } = splitEntriesByKeys(searchEnvEntries, SEARCH_PROVIDER_BASIC_KEYS);

    return (
      <div className="space-y-5">
        <InfoCard
          text={
            isLocalRuntime
              ? "默认先展示最常用的 RAG 与检索策略。各类联网检索服务的密钥与状态收进下方的检索服务区。"
              : "云端模式下，这里作为只读状态页展示当前检索策略与联网服务状态。"
          }
        />
        <SettingsGroup title="检索策略" description="优先调整这里，决定本地资料优先级、相似度阈值与默认检索 Profile。">
          <EditableSettingsList
            entries={basicSearchEntries}
            draft={settingsDraft}
            onChange={patchServerSetting}
            loading={isOverviewLoading}
            error={overviewError}
          />
        </SettingsGroup>
        {showAdvanced && advancedSearchEntries.length > 0 ? (
          <SettingsGroup title="检索高级项" description="超时、缓存、并发 provider 和融合参数等低层调优项。">
            <EditableSettingsList
              entries={advancedSearchEntries}
              draft={settingsDraft}
              onChange={patchServerSetting}
              loading={isOverviewLoading}
              error={overviewError}
            />
          </SettingsGroup>
        ) : null}
        <SettingsGroup title={isLocalRuntime ? "检索服务与密钥" : "检索服务状态"} description="联网搜索、阅读器、MCP 与重排服务的接入状态。">
          {isLocalRuntime ? (
            <EditableSettingsList
              entries={basicSearchEnvEntries}
              draft={envDraft}
              onChange={patchEnvSetting}
              loading={isOverviewLoading}
              error={overviewError}
            />
          ) : (
            <ReadonlySettingsList
              entries={basicSearchEnvEntries}
              loading={isOverviewLoading}
              error={overviewError}
            />
          )}
        </SettingsGroup>
        {showAdvanced && advancedSearchEnvEntries.length > 0 ? (
          <SettingsGroup title="更多检索服务" description="低频使用的联网检索服务与附加来源接入项。">
            {isLocalRuntime ? (
              <EditableSettingsList
                entries={advancedSearchEnvEntries}
                draft={envDraft}
                onChange={patchEnvSetting}
                loading={isOverviewLoading}
                error={overviewError}
              />
            ) : (
              <ReadonlySettingsList
                entries={advancedSearchEnvEntries}
                loading={isOverviewLoading}
                error={overviewError}
              />
            )}
          </SettingsGroup>
        ) : null}
      </div>
    );
  };

  const renderDeploy = () => {
    const runtimeEntries = getEntries("runtime").filter((entry) => DEPLOY_RUNTIME_KEYS.has(entry.key));
    const llmEntries = getEntries("models").filter((entry) => LLM_PROVIDER_STATUS_KEYS.has(entry.key));
    const storageEntries = getEntries("storage").filter(
      (entry) => STORAGE_STATUS_KEYS.has(entry.key) || entry.source === "runtime",
    );
    const localDeployEnvEntries = getEntries("runtime", "storage", "models").filter(
      (entry) => entry.source === "env" && (DEPLOY_RUNTIME_KEYS.has(entry.key) || STORAGE_STATUS_KEYS.has(entry.key) || LLM_PROVIDER_STATUS_KEYS.has(entry.key)),
    );

    return (
      <div className="space-y-5">
        <InfoCard
          text={
            isLocalRuntime
              ? "这里集中展示部署级变量、运行模式、鉴权、模型接入以及数据库/存储状态。本地模式下允许写回本机 .env。"
              : "云端模式下部署、鉴权、数据库和对象存储统一视为平台级配置，只读展示当前状态。"
          }
        />
        {isLocalRuntime ? (
          <SettingsGroup title="本机环境变量" description="部署级配置通常保存到本机 .env；是否立即生效取决于具体变量，通常建议保存后重启后端。">
            <EditableSettingsList
              entries={localDeployEnvEntries}
              draft={envDraft}
              onChange={patchEnvSetting}
              loading={isOverviewLoading}
              error={overviewError}
            />
          </SettingsGroup>
        ) : null}
        <SettingsGroup title="运行与鉴权" description="当前运行模式、APP_MODE 解析结果、鉴权开关与设置来源。">
          <ReadonlySettingsList
            entries={runtimeEntries}
            loading={isOverviewLoading}
            error={overviewError}
          />
        </SettingsGroup>
        <SettingsGroup title="模型接入" description="当前模型服务地址与密钥配置状态。">
          <ReadonlySettingsList
            entries={llmEntries}
            loading={isOverviewLoading}
            error={overviewError}
          />
        </SettingsGroup>
        <SettingsGroup title="数据库与存储" description="数据库连接、对象存储后端与 S3 / DogeCloud 当前状态。">
          <ReadonlySettingsList
            entries={storageEntries}
            loading={isOverviewLoading}
            error={overviewError}
          />
        </SettingsGroup>
      </div>
    );
  };

  const renderObservability = () => {
    const observabilityEntries = getEntries("observability").filter(
      (entry) => entry.editable && hasAnyPrefix(entry.key, OBSERVABILITY_SETTING_PREFIXES),
    );
    const observabilityToggleEntries = observabilityEntries.filter((entry) => entry.key.startsWith("observability."));
    const performanceEntries = observabilityEntries.filter(
      (entry) => entry.key.startsWith("runtime.") || entry.key.startsWith("embedding."),
    );
    const { basic: basicObservabilityEntries, advanced: advancedObservabilityEntries } = splitEntriesByKeys(observabilityToggleEntries, OBSERVABILITY_BASIC_KEYS);
    const { basic: basicPerformanceEntries, advanced: advancedPerformanceEntries } = splitEntriesByKeys(performanceEntries, PERFORMANCE_BASIC_KEYS);
    const observabilityEnvEntries = getEntries("observability").filter((entry) =>
      OBSERVABILITY_ENV_STATUS_KEYS.has(entry.key),
    );

    return (
      <div className="space-y-5">
        <InfoCard
          text={
            isLocalRuntime
              ? "这页聚合 tracing、调用统计和运行性能调优项。调试模式已移到“当前设备”，避免与服务端观测开关混淆。"
              : "云端模式下观测与性能设置只读展示；普通用户不能修改服务端 tracing 和运行时调优参数。"
          }
        />
        <SettingsGroup title="观测与追踪" description="控制 LangSmith、LLM 调用统计和文本预览等可观测性行为。">
          <EditableSettingsList
            entries={basicObservabilityEntries}
            draft={settingsDraft}
            onChange={patchServerSetting}
            loading={isOverviewLoading}
            error={overviewError}
          />
        </SettingsGroup>
        {showAdvanced && advancedObservabilityEntries.length > 0 ? (
          <SettingsGroup title="观测高级项" description="Trace 输入输出预览和文本截断等低频调优项。">
            <EditableSettingsList
              entries={advancedObservabilityEntries}
              draft={settingsDraft}
              onChange={patchServerSetting}
              loading={isOverviewLoading}
              error={overviewError}
            />
          </SettingsGroup>
        ) : null}
        <SettingsGroup title="运行性能" description="控制 LLM 并发和 Embedding 批处理行为。">
          <EditableSettingsList
            entries={basicPerformanceEntries}
            draft={settingsDraft}
            onChange={patchServerSetting}
            loading={isOverviewLoading}
            error={overviewError}
          />
        </SettingsGroup>
        {showAdvanced && advancedPerformanceEntries.length > 0 ? (
          <SettingsGroup title="性能高级项" description="上下文预算、Embedding 批延迟等低频调优项。">
            <EditableSettingsList
              entries={advancedPerformanceEntries}
              draft={settingsDraft}
              onChange={patchServerSetting}
              loading={isOverviewLoading}
              error={overviewError}
            />
          </SettingsGroup>
        ) : null}
        <SettingsGroup title={isLocalRuntime ? "LangSmith 与观测环境变量" : "观测服务状态"} description="用于 tracing 与可观测性的部署级环境变量。">
          {isLocalRuntime ? (
            <EditableSettingsList
              entries={observabilityEnvEntries}
              draft={envDraft}
              onChange={patchEnvSetting}
              loading={isOverviewLoading}
              error={overviewError}
            />
          ) : (
            <ReadonlySettingsList
              entries={observabilityEnvEntries}
              loading={isOverviewLoading}
              error={overviewError}
            />
          )}
        </SettingsGroup>
      </div>
    );
  };

  const renderers: Record<SectionType, () => ReactNode> = {
    device: renderDevice,
    models: renderModels,
    learning: renderLearning,
    search: renderSearch,
    deploy: renderDeploy,
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
            className="pointer-events-auto flex h-[min(720px,85vh)] w-full max-w-[960px] overflow-hidden rounded-lg border border-zinc-200/60 bg-white shadow-[0_25px_80px_-20px_rgba(0,0,0,0.35)]"
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
                <span className={`inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-[10px] font-medium ${isLocalRuntime ? "bg-emerald-50 text-emerald-600" : "bg-sky-50 text-sky-600"}`}>
                  <span className={`h-1.5 w-1.5 rounded-full ${isLocalRuntime ? "bg-emerald-500" : "bg-sky-500"}`} />
                  {isLocalRuntime ? "本地模式" : "云端模式"}
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
                <div className="flex items-center gap-2">
                  {isLocalRuntime ? (
                    <button
                      type="button"
                      onClick={() => setShowAdvanced((prev) => !prev)}
                      className={`inline-flex items-center gap-1.5 rounded-lg border px-3 py-1.5 text-[12px] font-medium transition ${
                        showAdvanced
                          ? "border-zinc-900 bg-zinc-900 text-white hover:bg-zinc-800"
                          : "border-zinc-200 bg-white text-zinc-500 hover:border-zinc-300 hover:text-zinc-700"
                      }`}
                    >
                      <SlidersHorizontal className="h-3.5 w-3.5" />
                      {showAdvanced ? "收起高级" : "显示高级"}
                    </button>
                  ) : null}
                  <button
                    type="button"
                    onClick={onClose}
                    className="inline-flex h-8 w-8 items-center justify-center rounded-lg text-zinc-400 transition hover:bg-zinc-100 hover:text-zinc-600"
                    aria-label="关闭设置"
                  >
                    <X className="h-4 w-4" />
                  </button>
                </div>
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
                  {isLocalRuntime ? (
                    <>
                      <button
                        type="button"
                        onClick={() => {
                          setDraft({ ...DEFAULT_SETTINGS });
                          setSettingsDraft(defaultSettingsDraft);
                          setEnvDraft(savedEnvDraft);
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
                    </>
                  ) : null}
                </div>
              </div>
            </div>
          </motion.div>
        </div>
      </motion.div>
    </AnimatePresence>
  );
}
