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
  Wrench,
  X,
  Wifi,
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

type SectionType = "connection" | "models" | "learning" | "search" | "credentials" | "ops" | "observability";
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
  { id: "connection", label: "连接", description: "模式与本机连接", icon: Wifi },
  { id: "models", label: "模型", description: "模型路由", icon: Bot },
  { id: "learning", label: "学习引擎", description: "解析与构建", icon: Wrench },
  { id: "search", label: "检索", description: "联网与 RAG", icon: Search },
  { id: "credentials", label: "API 密钥", description: "服务授权配置", icon: KeyRound },
  { id: "ops", label: "部署状态", description: "鉴权、SMTP、存储", icon: Database },
  { id: "observability", label: "观测调试", description: "Tracing 与浏览器调试", icon: Activity },
] as const;

function isCredentialKey(key: string): boolean {
  const k = key.toLowerCase();
  return k.includes("key") || k.includes("token") || k.includes("secret") || k.includes("password");
}

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
  "auth.enabled",
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
      ? "text-amber-700 bg-amber-50"
      : "text-zinc-600 bg-zinc-50/80";
  return <div className={`rounded-xl px-4 py-3 text-[13px] leading-relaxed ${className}`}>{text}</div>;
}

function SectionDivider({ label }: { label: string }) {
  return (
    <div className="flex items-center justify-between pb-2 mt-8 mb-4 border-b border-zinc-100/80">
      <h3 className="text-base font-semibold text-zinc-900">{label}</h3>
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
      className="flex h-9 w-full max-w-2xl rounded-md border border-zinc-200 bg-transparent px-3 py-1 text-sm shadow-sm transition-colors placeholder:text-zinc-500 focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-zinc-950 disabled:cursor-not-allowed disabled:opacity-50"
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
      className="flex h-9 w-full max-w-2xl items-center justify-between whitespace-nowrap rounded-md border border-zinc-200 bg-transparent px-3 py-2 text-sm shadow-sm ring-offset-white focus:outline-none focus:ring-1 focus:ring-zinc-950 appearance-none bg-[url('data:image/svg+xml;charset=US-ASCII,%3Csvg%20width%3D%2224%22%20height%3D%2224%22%20viewBox%3D%220%200%2024%2024%22%20fill%3D%22none%22%20xmlns%3D%22http%3A%2F%2Fwww.w3.org%2F2000%2Fsvg%22%3E%3Cpath%20d%3D%22M6%209L12%2015L18%209%22%20stroke%3D%22%2371717A%22%20stroke-width%3D%222%22%20stroke-linecap%3D%22round%22%20stroke-linejoin%3D%22round%22%2F%3E%3C%2Fsvg%3E')] bg-[length:16px_16px] bg-[position:right_10px_center] bg-no-repeat pr-10 cursor-pointer"
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
    <div className="flex flex-row items-center justify-between rounded-lg py-3 hover:bg-zinc-50/50 transition px-2 -mx-2">
      <div className="space-y-0.5 pr-4">
        <label className="text-sm font-medium leading-none text-zinc-900 cursor-pointer" onClick={onToggle}>{title}</label>
        <p className="text-[13px] text-zinc-500 leading-relaxed mt-1.5">{description}</p>
      </div>
      <button
        type="button"
        onClick={onToggle}
        className={`relative inline-flex h-5 w-9 shrink-0 cursor-pointer items-center rounded-full border-2 border-transparent transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-zinc-950 focus-visible:ring-offset-2 ${
          enabled ? "bg-zinc-900" : "bg-zinc-200"
        }`}
      >
        <span className={`pointer-events-none block h-4 w-4 rounded-full bg-white shadow-lg ring-0 transition-transform ${enabled ? "translate-x-4" : "translate-x-0"}`} />
      </button>
    </div>
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
  if (!entries.length) return null;

  return (
    <div className="space-y-6">
      {entries.map((entry) => (
        <div key={entry.key} className="space-y-2">
          <div className="flex flex-col gap-1.5">
            <span className="text-sm font-medium leading-none text-zinc-900 block">{entry.label}</span>
            {entry.description && (
              <p className="text-[13px] text-zinc-500 leading-relaxed">{entry.description}</p>
            )}
          </div>
          <div className="font-mono text-[13px] text-zinc-800 bg-zinc-50/80 px-3 py-1.5 rounded-md border border-zinc-200 break-all w-fit max-w-full shadow-sm">
            {displayValue(entry)}
          </div>
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
  if (loading) return <InfoCard text="正在加载..." />;
  if (error) return <InfoCard text={error} variant="warning" />;
  if (!items.length) return null;

  return (
    <div className="space-y-6">
      {items.map((entry) => {
        const value = draft[entry.key];
        const selectOptions = SETTING_SELECT_OPTIONS[entry.key];

        if (typeof value === "boolean") {
          return (
            <div key={entry.key}>
              <SwitchRow
                title={entry.label}
                description={entry.description || entry.key}
                enabled={value}
                onToggle={() => onChange(entry.key, !value)}
              />
            </div>
          );
        }

        return (
          <div key={entry.key} className="space-y-2">
            <div className="flex flex-col gap-1.5">
              <label className="text-sm font-medium leading-none peer-disabled:cursor-not-allowed peer-disabled:opacity-70 text-zinc-900">{entry.label}</label>
              {entry.description && (
                <p className="text-[13px] text-zinc-500 leading-relaxed">
                  {entry.description}
                </p>
              )}
            </div>
            
            <div className="w-full">
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
            </div>
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
    <div className="space-y-4">
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
        <div className="space-y-3 rounded-lg border border-zinc-100 bg-zinc-50/40 px-4 py-3 mt-4">
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
      <SectionDivider label="后端能力探测" />
      <ReadonlySettingsList
        entries={getEntries("runtime", "models").filter((entry) => CORE_STATUS_KEYS.has(entry.key))}
        loading={isOverviewLoading}
        error={overviewError}
      />
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
    const learningEntries = getEntries("learning_engines").filter(
      (entry) => (hasAnyPrefix(entry.key, LEARNING_SETTING_PREFIXES) || MODE_AWARE_PREFERENCE_KEYS.has(entry.key)) && !isCredentialKey(entry.key)
    );
    const learningEnvEntries = getEntries("learning_engines").filter((entry) => entry.source === "env" && !isCredentialKey(entry.key));

    return (
      <div className="space-y-5">
        <InfoCard
          text={
            isLocalRuntime
              ? "当前显示本地模式下的全部学习引擎可写项。"
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
    const searchEntries = getEntries("search").filter((entry) => hasAnyPrefix(entry.key, SEARCH_SETTING_PREFIXES) && !isCredentialKey(entry.key));
    const searchEnvEntries = getEntries("search").filter((entry) => entry.source === "env" && !isCredentialKey(entry.key));

    return (
      <div className="space-y-5">
        <InfoCard
          text={
            isLocalRuntime
              ? "当前显示完整检索调优面板，包括 provider、缓存和超时等低层参数。"
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

  const renderCredentials = () => {
    const allEntries = getEntries("runtime", "models", "learning_engines", "search", "storage", "observability");
    const credentialEntries = allEntries.filter((entry) => isCredentialKey(entry.key) || entry.secret);
    const uniqueCredentialEntries = Array.from(new Map(credentialEntries.map((e) => [e.key, e])).values());
    const editableEnvEntries = uniqueCredentialEntries.filter((entry) => entry.source === "env");

    return (
      <div className="space-y-5">
        <InfoCard text="此处集中管理所有第三方服务与本地服务的 API 密钥和鉴权 Token。" />
        {isLocalRuntime ? (
          <>
            <SectionDivider label="临时覆盖" />
            <div className="space-y-3 rounded-lg border border-zinc-100 bg-zinc-50/40 px-4 py-3">
              <div className="space-y-2">
                <label className="text-[13px] font-semibold text-zinc-700">MinerU 临时 Token</label>
                <TextInput
                  type="password"
                  value={draft.mineruApiToken}
                  onChange={(value) => patch("mineruApiToken", value)}
                  placeholder="MINERU_API_TOKEN"
                />
                <p className="text-[11px] leading-relaxed text-zinc-400">
                  仅当前浏览器可见。优先使用此设置；留空则回退到本地 .env 配置。
                </p>
              </div>
            </div>
            <SectionDivider label="本地 .env 配置" />
            <EditableSettingsList
              entries={editableEnvEntries}
              draft={envDraft}
              onChange={patchEnvSetting}
              loading={isOverviewLoading}
              error={overviewError}
            />
          </>
        ) : (
          <ReadonlySettingsList
            entries={editableEnvEntries}
            loading={isOverviewLoading}
            error={overviewError}
          />
        )}
      </div>
    );
  };

  const renderOps = () => {
    const opsEntries = getEntries("runtime", "storage").filter((entry) => !isCredentialKey(entry.key));
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
    const observabilityEntries = getEntries("observability").filter(
      (entry) => entry.editable && hasAnyPrefix(entry.key, OBSERVABILITY_SETTING_PREFIXES) && !isCredentialKey(entry.key)
    );
    const observabilityEnvEntries = getEntries("observability").filter((entry) =>
      OBSERVABILITY_ENV_STATUS_KEYS.has(entry.key) && !isCredentialKey(entry.key)
    );

    return (
      <div className="space-y-5">
        <InfoCard
          text={
            isLocalRuntime
              ? "当前显示完整观测与调试设置，包括采样、展示和嵌入批处理等低频参数。"
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
    credentials: renderCredentials,
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
        <div className="absolute inset-0 bg-black/20 backdrop-blur-[2px]" onClick={onClose} />
        <div className="pointer-events-none absolute inset-0 flex items-center justify-center p-4 sm:p-8">
          <motion.div
            initial={{ opacity: 0, scale: 0.96, y: 10 }}
            animate={{ opacity: 1, scale: 1, y: 0 }}
            exit={{ opacity: 0, scale: 0.96, y: 10 }}
            transition={{ type: "spring", stiffness: 500, damping: 40 }}
            className="pointer-events-auto flex h-[85vh] w-full max-w-[900px] overflow-hidden rounded-xl bg-white shadow-lg ring-1 ring-black/5"
          >
            <nav className="flex w-[240px] shrink-0 flex-col bg-zinc-50/50 border-r border-zinc-200">
              <div className="px-5 pb-2 pt-6">
                <h2 className="text-lg font-semibold text-zinc-900">设置</h2>
              </div>
              <div className="flex-1 space-y-1 overflow-y-auto px-3 py-4">
                {SECTIONS.map((section) => {
                  const Icon = section.icon;
                  const active = activeSection === section.id;
                  return (
                    <button
                      key={section.id}
                      type="button"
                      onClick={() => setActiveSection(section.id)}
                      className={`group flex w-full items-center gap-3 rounded-md px-3 py-2 text-sm transition-colors min-w-0 text-left ${
                        active ? "bg-zinc-100 text-zinc-900 font-medium" : "text-zinc-600 hover:bg-zinc-100 hover:text-zinc-900"
                      }`}
                    >
                      <span className={`inline-flex items-center justify-center shrink-0 ${active ? "text-zinc-900" : "text-zinc-500 group-hover:text-zinc-600"}`}>
                        <Icon className="h-4 w-4" />
                      </span>
                      <span className="truncate leading-none">{section.label}</span>
                    </button>
                  );
                })}
              </div>
              
              <div className="p-4 mt-auto mb-4 mx-3 rounded-xl bg-zinc-100/50 border border-zinc-200/50">
                <div className="flex flex-col gap-2">
                  <span className="text-xs font-semibold text-zinc-500 uppercase tracking-wider mb-1">环境状态</span>
                  <div className="flex items-center gap-2">
                    <span className={`relative flex h-2 w-2`}>
                      <span className={`animate-ping absolute inline-flex h-full w-full rounded-full opacity-75 ${isLocalRuntime ? "bg-emerald-400" : "bg-sky-400"}`}></span>
                      <span className={`relative inline-flex rounded-full h-2 w-2 ${isLocalRuntime ? "bg-emerald-500" : "bg-sky-500"}`}></span>
                    </span>
                    <span className="text-[13px] font-medium text-zinc-700">{isLocalRuntime ? "本地网络直连" : "云端托管运行"}</span>
                  </div>
                  <div className="flex items-center gap-2">
                    <span className={`h-2 w-2 rounded-sm ${draft.useMock ? "bg-amber-500" : "bg-zinc-300"}`} />
                    <span className="text-[13px] font-medium text-zinc-700">{draft.useMock ? "Mock数据开启" : "系统真实数据"}</span>
                  </div>
                </div>
              </div>
            </nav>

            <div className="flex min-w-0 flex-1 flex-col bg-white">
              <div className="flex items-center justify-between px-8 py-6 pb-4">
                <div>
                  <h3 className="text-xl font-bold text-zinc-900">{activeSectionConfig.label}</h3>
                  <p className="mt-1 text-[13px] text-zinc-500">{activeSectionConfig.description}</p>
                </div>
                <div className="flex items-center gap-3">
                  <button
                    type="button"
                    onClick={onClose}
                    className="inline-flex h-8 w-8 items-center justify-center rounded-full text-zinc-400 transition hover:bg-zinc-100 hover:text-zinc-600"
                    aria-label="关闭设置"
                  >
                    <X className="h-5 w-5" />
                  </button>
                </div>
              </div>

              <div className="min-h-0 flex-1 overflow-y-auto px-8 py-2">
                <AnimatePresence mode="wait">
                  <motion.div key={activeSection} variants={contentVariants} initial="initial" animate="animate" exit="exit" className="pb-8">
                    {renderers[activeSection]()}
                  </motion.div>
                </AnimatePresence>
              </div>

              <div className="flex items-center justify-between border-t border-zinc-100 bg-white px-8 py-4">
                <div className="text-[13px] font-medium">
                  <AnimatePresence mode="wait">
                    {saveState === "saving" ? (
                      <motion.span key="saving" initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }} className="flex items-center gap-2 text-zinc-600">
                        <Loader2 className="h-4 w-4 animate-spin" /> 保存配置中...
                      </motion.span>
                    ) : saveState === "error" ? (
                      <motion.span key="error" initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }} className="flex items-center gap-2 text-red-600">
                        <RefreshCcw className="h-4 w-4" /> {saveError ?? "保存失败"}
                      </motion.span>
                    ) : saveState === "saved" ? (
                      <motion.span key="saved" initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }} className="flex items-center gap-2 text-emerald-600">
                        <CheckCircle2 className="h-4 w-4" /> 配置已生效
                      </motion.span>
                    ) : hasChanges ? (
                      <motion.span key="changed" initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }} className="flex items-center gap-2 text-amber-600">
                        <span className="relative flex h-2.5 w-2.5"><span className="animate-ping absolute inline-flex h-full w-full rounded-full bg-amber-400 opacity-75"></span><span className="relative inline-flex rounded-full h-2.5 w-2.5 bg-amber-500"></span></span>
                        发现未保存更改
                      </motion.span>
                    ) : (
                      <motion.span key="synced" initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }} className="flex items-center gap-2 text-zinc-400">
                        设置已同步
                      </motion.span>
                    )}
                  </AnimatePresence>
                </div>

                <div className="flex items-center gap-3">
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
                        className="inline-flex h-9 items-center justify-center rounded-md px-4 py-2 text-sm font-medium text-zinc-600 transition-colors hover:bg-zinc-100 hover:text-zinc-900"
                      >
                        撤销恢复
                      </button>
                      <button
                        type="button"
                        onClick={saveSettings}
                        disabled={!hasChanges || saveState === "saving"}
                        className={`inline-flex h-9 items-center justify-center rounded-md px-4 py-2 text-sm font-medium shadow transition-colors ${
                          hasChanges && saveState !== "saving"
                            ? "bg-zinc-900 text-zinc-50 hover:bg-zinc-900/90"
                            : "cursor-not-allowed bg-zinc-100 text-zinc-400"
                        }`}
                      >
                        {saveState === "saving" ? "应用中..." : "保存更改"}
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
