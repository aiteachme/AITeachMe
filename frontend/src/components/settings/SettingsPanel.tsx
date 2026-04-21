import { useEffect, useMemo, useState } from "react";
import { AnimatePresence, motion } from "framer-motion";
import {
  Activity,
  Bot,
  CheckCircle2,
  Database,
  KeyRound,
  Loader2,
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

type SectionType = "connection" | "models" | "learning" | "search" | "ops" | "observability";
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
  { id: "connection", label: "连接", description: "模式与本机连接", icon: KeyRound },
  { id: "models", label: "模型", description: "模型路由", icon: Bot },
  { id: "learning", label: "学习引擎", description: "解析与构建", icon: Wrench },
  { id: "search", label: "检索", description: "联网与 RAG", icon: Search },
  { id: "ops", label: "部署状态", description: "鉴权、SMTP、存储", icon: Database },
  { id: "observability", label: "观测调试", description: "Tracing 与浏览器调试", icon: Activity },
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
  "settings.source",
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

const SIMPLE_LEARNING_KEYS = new Set([
  "ingest.default_parser_provider",
  "ingest.mineru_model_version",
  "ingest.mineru_enable_formula",
  "ingest.mineru_enable_table",
  "ingest.mineru_is_ocr",
  "planner.default_digest_mode",
  "planner.sprint.min_chapters",
  "planner.sprint.max_chapters",
  "planner.sprint.target_length",
  "planner.systematic.min_chapters",
  "planner.systematic.max_chapters",
  "planner.systematic.target_length",
  "docgen.allow_external_search",
  "docgen.generate_cover_image",
  "interact.history_turns",
  "knowledge_graph.sync_after_docgen",
]);

const SIMPLE_SEARCH_KEYS = new Set([
  "rag.top_k",
  "rag.similarity_threshold",
  "rag.rerank_model",
  "rag.rerank_top_k",
  "local_rag.priority",
  "local_rag.min_results",
  "search.retriever_profile",
]);

const SIMPLE_SEARCH_ENV_KEYS = new Set([
  "search.tavily_key",
  "search.jina_key",
  "search.serper_key",
  "search.mcp_tool",
  "rag.rerank_api_key",
]);

const SIMPLE_OBSERVABILITY_KEYS = new Set([
  "observability.tracing_enabled",
  "observability.llm_token_summary_enabled",
  "observability.llm_observability_enabled",
  "runtime.llm_concurrency_limit",
]);

const LEARNING_SETTING_PREFIXES = ["ingest.", "planner.", "docgen.", "interact.", "knowledge_graph."];
const SEARCH_SETTING_PREFIXES = ["rag.", "local_rag.", "search."];
const OBSERVABILITY_SETTING_PREFIXES = ["observability.", "runtime.", "embedding."];
const MODE_AWARE_PREFERENCE_KEYS = new Set([
  "ingest.default_parser_provider",
  "ingest.mineru_model_version",
  "ingest.mineru_enable_formula",
  "ingest.mineru_enable_table",
  "ingest.mineru_is_ocr",
  "planner.default_digest_mode",
  "interact.history_turns",
]);

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

function filterByVisibleKeys(
  entries: SettingEntry[],
  allowedKeys: Set<string>,
  showAdvanced: boolean,
) {
  if (showAdvanced) {
    return entries;
  }
  return entries.filter((entry) => allowedKeys.has(entry.key));
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
                <span className="rounded-md border border-zinc-200 bg-white px-2 py-0.5 text-[11px] text-zinc-400">
                  默认：{displayValue({ ...entry, value: entry.default_value })}
                </span>
                {entry.restart_required ? (
                  <span className="rounded-md border border-amber-200 bg-amber-50 px-2 py-0.5 text-[11px] text-amber-700">
                    保存后建议重启
                  </span>
                ) : null}
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
  const [activeSection, setActiveSection] = useState<SectionType>("connection");
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
    setActiveSection("connection");
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

  const renderConnection = () => (
    <div className="space-y-5">
      <InfoCard
        text={
          isLocalRuntime
            ? "本地模式下，会开放浏览器本机设置和本地 .env 编辑；这里的非敏感运行参数仍保存到数据库。"
            : "云端模式下，这里只作为状态页展示当前运行模式、能力状态与配置来源。"
        }
      />
      {isLocalRuntime ? (
        <>
          <SectionDivider label="本地 .env" />
          <EditableSettingsList
            entries={getEntries("models").filter((entry) => entry.source === "env")}
            draft={envDraft}
            onChange={patchEnvSetting}
            loading={isOverviewLoading}
            error={overviewError}
          />
        </>
      ) : null}
      {isLocalRuntime ? (
        <div className="space-y-3 rounded-lg border border-zinc-100 bg-zinc-50/40 px-4 py-3">
          <SectionDivider label="浏览器本机" />
          <div className="space-y-3">
            <div className="space-y-2">
              <label className="text-[13px] font-semibold text-zinc-700">FastAPI 地址</label>
              <TextInput value={draft.apiUrl} onChange={(value) => patch("apiUrl", value)} placeholder="http://localhost:8000" />
              <p className="text-[11px] leading-relaxed text-zinc-400">只影响当前浏览器访问哪个后端地址。</p>
            </div>
            <SwitchRow
              title="本地 Mock"
              description="只影响当前浏览器是否启用前端 Mock。"
              enabled={draft.useMock}
              onToggle={() => patch("useMock", !draft.useMock)}
            />
          </div>
        </div>
      ) : null}
      <SectionDivider label="后端当前状态" />
      <ReadonlySettingsList
        entries={getEntries("runtime", "models").filter((entry) => CORE_STATUS_KEYS.has(entry.key))}
        loading={isOverviewLoading}
        error={overviewError}
      />
      {overview?.notes?.length ? (
        <div className="space-y-2">
          {overview.notes.map((note) => (
            <InfoCard key={note} text={note} />
          ))}
        </div>
      ) : null}
    </div>
  );

  const renderModels = () => (
    <div className="space-y-5">
      <InfoCard
        text={
          isLocalRuntime
            ? "本地模式允许直接调整模型路由。保存后会写入本地系统配置。"
            : "云端模式下模型路由视为系统级配置，这里只读展示当前有效值。"
        }
      />
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

  const renderLearning = () => {
    const learningEntries = filterByVisibleKeys(
      getEntries("learning_engines").filter(
        (entry) => hasAnyPrefix(entry.key, LEARNING_SETTING_PREFIXES) || MODE_AWARE_PREFERENCE_KEYS.has(entry.key),
      ),
      SIMPLE_LEARNING_KEYS,
      showAdvanced,
    );
    const learningEnvEntries = getEntries("learning_engines").filter((entry) => entry.source === "env");

    return (
      <div className="space-y-5">
        <InfoCard
          text={
            isLocalRuntime
              ? showAdvanced
                ? "当前显示本地模式下的全部学习引擎可写项。低频调优项也会一起展开，适合排查链路或精细打磨默认行为。"
                : "当前默认只显示常用学习引擎设置。更底层的并发、超时和链路调优项可以通过右上角“显示高级”查看。"
              : "云端模式下学习引擎配置只读展示，普通用户不能修改服务端默认值。"
          }
        />
        <EditableSettingsList
          entries={learningEntries}
          draft={settingsDraft}
          onChange={patchServerSetting}
          loading={isOverviewLoading}
          error={overviewError}
        />
        {isLocalRuntime && parserProvider === "mineru" ? (
          <div className="space-y-3 rounded-lg border border-zinc-100 bg-zinc-50/40 px-4 py-3">
            <SectionDivider label="浏览器临时覆盖" />
            <div className="space-y-2">
              <label className="text-[13px] font-semibold text-zinc-700">MinerU 临时 Token</label>
              <TextInput
                type="password"
                value={draft.mineruApiToken}
                onChange={(value) => patch("mineruApiToken", value)}
                placeholder="MINERU_API_TOKEN"
              />
              <p className="text-[11px] leading-relaxed text-zinc-400">
                仅当前浏览器可见。上传时会优先使用这个临时 Token；留空则回退到本地 .env 里的 MINERU_API_TOKEN。
              </p>
            </div>
          </div>
        ) : null}
        {parserProvider === "auto" ? (
          <InfoCard text="自动模式不会显式指定 parser_provider。上传时会走后端当前已实现的本地自动 parser chain：先分类，再生成 ParsePlan，再按文件类型和质量策略选择并尝试本地解析器链。" />
        ) : null}
        {isLocalRuntime ? (
          <>
            <SectionDivider label="本地 .env" />
            <EditableSettingsList
              entries={learningEnvEntries}
              draft={envDraft}
              onChange={patchEnvSetting}
              loading={isOverviewLoading}
              error={overviewError}
            />
          </>
        ) : (
          <>
            <SectionDivider label="服务端状态" />
            <ReadonlySettingsList
              entries={learningEnvEntries}
              loading={isOverviewLoading}
              error={overviewError}
            />
          </>
        )}
      </div>
    );
  };

  const renderSearch = () => {
    const searchEntries = filterByVisibleKeys(
      getEntries("search").filter((entry) => hasAnyPrefix(entry.key, SEARCH_SETTING_PREFIXES)),
      SIMPLE_SEARCH_KEYS,
      showAdvanced,
    );
    const searchEnvEntries = filterByVisibleKeys(
      getEntries("search").filter((entry) => entry.source === "env"),
      SIMPLE_SEARCH_ENV_KEYS,
      showAdvanced,
    );

    return (
      <div className="space-y-5">
        <InfoCard
          text={
            isLocalRuntime
              ? showAdvanced
                ? "当前显示完整检索调优面板，包括 provider、缓存和超时等低层参数。"
                : "当前默认只显示常用检索策略。大部分 provider 密钥和超时调优项已收进高级视图，避免把日常设置页变成运维面板。"
              : "云端模式下，检索 provider 的密钥与运行参数只读展示。"
          }
        />
        <EditableSettingsList
          entries={searchEntries}
          draft={settingsDraft}
          onChange={patchServerSetting}
          loading={isOverviewLoading}
          error={overviewError}
        />
        <SectionDivider label={isLocalRuntime ? "本地 .env" : "服务端 provider 状态"} />
        {isLocalRuntime ? (
          <EditableSettingsList
            entries={searchEnvEntries}
            draft={envDraft}
            onChange={patchEnvSetting}
            loading={isOverviewLoading}
            error={overviewError}
          />
        ) : (
          <ReadonlySettingsList
            entries={searchEnvEntries}
            loading={isOverviewLoading}
            error={overviewError}
          />
        )}
      </div>
    );
  };

  const renderOps = () => {
    const opsEntries = getEntries("runtime", "storage");
    const editableEnvEntries = opsEntries.filter((entry) => entry.source === "env");
    const readonlyEntries = opsEntries.filter(
      (entry) => CORE_STATUS_KEYS.has(entry.key) || STORAGE_STATUS_KEYS.has(entry.key) || entry.source === "runtime",
    );

    return (
      <div className="space-y-5">
        <InfoCard
          text={
            isLocalRuntime
              ? "本地模式下部署级环境变量也可写入本地 .env，但是否立即生效取决于具体配置，通常建议保存后重启后端。"
              : "云端模式下，部署、鉴权、数据库和对象存储统一视为平台级配置，只读展示。"
          }
        />
        {isLocalRuntime ? (
          <>
            <SectionDivider label="本地 .env" />
            <EditableSettingsList
              entries={editableEnvEntries}
              draft={envDraft}
              onChange={patchEnvSetting}
              loading={isOverviewLoading}
              error={overviewError}
            />
          </>
        ) : null}
        <SectionDivider label="当前状态" />
        <ReadonlySettingsList
          entries={readonlyEntries}
          loading={isOverviewLoading}
          error={overviewError}
        />
      </div>
    );
  };

  const renderObservability = () => {
    const observabilityEntries = filterByVisibleKeys(
      getEntries("observability").filter(
        (entry) => entry.editable && hasAnyPrefix(entry.key, OBSERVABILITY_SETTING_PREFIXES),
      ),
      SIMPLE_OBSERVABILITY_KEYS,
      showAdvanced,
    );
    const observabilityEnvEntries = getEntries("observability").filter((entry) =>
      OBSERVABILITY_ENV_STATUS_KEYS.has(entry.key),
    );

    return (
      <div className="space-y-5">
        <InfoCard
          text={
            isLocalRuntime
              ? showAdvanced
                ? "当前显示完整观测与调试设置，包括采样、展示和嵌入批处理等低频参数。"
                : "当前默认只显示最常用的观测控制项。更细的追踪预览、批处理和保留策略已收进高级视图。"
              : "云端模式下观测配置只读展示；浏览器调试项默认不开放给普通用户。"
          }
        />
        <EditableSettingsList
          entries={observabilityEntries}
          draft={settingsDraft}
          onChange={patchServerSetting}
          loading={isOverviewLoading}
          error={overviewError}
        />
        {isLocalRuntime ? (
          <div className="space-y-3 rounded-lg border border-zinc-100 bg-zinc-50/40 px-4 py-3">
            <SectionDivider label="浏览器本机" />
            <SwitchRow
              title="调试模式"
              description="只影响当前浏览器的调试体验。"
              enabled={draft.debugMode}
              onToggle={() => patch("debugMode", !draft.debugMode)}
            />
          </div>
        ) : null}
        <SectionDivider label={isLocalRuntime ? "本地 .env" : "服务端观测状态"} />
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
      </div>
    );
  };

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
