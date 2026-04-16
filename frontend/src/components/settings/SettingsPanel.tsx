import { useEffect, useMemo, useState } from "react";
import { AnimatePresence, motion } from "framer-motion";
import {
  Bot,
  CheckCircle2,
  Eye,
  EyeOff,
  KeyRound,
  Loader2,
  RefreshCcw,
  Server,
  SlidersHorizontal,
  Sparkles,
  Wrench,
  X,
} from "lucide-react";
import {
  DEFAULT_SETTINGS,
  type AppSettings,
  type OcrProvider,
  type ParserMode,
  type ParserProvider,
  useSettings,
} from "../../hooks/useSettings";
import { apiClient, getApiErrorMessage } from "../../api/client";

interface SettingsModalProps {
  isOpen: boolean;
  onClose: () => void;
}

type SectionType = "credentials" | "models" | "parser" | "generation" | "runtime";

interface SectionConfig {
  id: SectionType;
  label: string;
  description: string;
  icon: typeof KeyRound;
}

type SaveState = "idle" | "saved";
type ConnectionStatus = "idle" | "success" | "error";
type SettingSource = "env" | "settings" | "runtime";
type SettingStatus = "configured" | "missing" | "default" | "disabled" | "enabled" | "runtime";

interface SettingEntry {
  key: string;
  label: string;
  source: SettingSource;
  value?: unknown;
  display_value?: string | null;
  status: SettingStatus;
  secret?: boolean;
  description?: string;
}

interface SettingSection {
  id: string;
  label: string;
  description: string;
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

const SECTIONS: SectionConfig[] = [
  { id: "credentials", label: "后端与凭证", description: ".env 生效状态与本机连接", icon: KeyRound },
  { id: "models", label: "模型配置", description: "settings.yaml 当前模型", icon: Bot },
  { id: "parser", label: "解析与检索", description: "Ingest / Search 配置", icon: Wrench },
  { id: "generation", label: "生成参数", description: "本机实验参数", icon: SlidersHorizontal },
  { id: "runtime", label: "运行与调试", description: "存储、观测与本机偏好", icon: Server },
];

function clamp(value: number, min: number, max: number): number {
  if (!Number.isFinite(value)) return min;
  if (value < min) return min;
  if (value > max) return max;
  return value;
}

/* ── Reusable form primitives ── */

function FieldGroup({ label, children, hint }: { label: string; children: React.ReactNode; hint?: string }) {
  return (
    <div className="rounded-xl border border-zinc-100 bg-zinc-50/40 px-4 py-3.5 space-y-2">
      <label className="block text-[13px] font-semibold text-zinc-700">{label}</label>
      {children}
      {hint ? <p className="text-[11px] leading-relaxed text-zinc-400">{hint}</p> : null}
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
      onChange={(e) => onChange(e.target.value)}
      placeholder={placeholder}
      className="w-full rounded-lg border border-zinc-200 bg-white px-3.5 py-2.5 text-[13px] text-zinc-900 placeholder:text-zinc-300 outline-none transition-all duration-200 focus:border-zinc-400 focus:ring-4 focus:ring-zinc-900/5 shadow-[0_1px_2px_rgba(0,0,0,0.04)]"
    />
  );
}

function NumberInput({
  value,
  onChange,
  min,
  max,
  step,
}: {
  value: number;
  onChange: (value: number) => void;
  min: number;
  max: number;
  step: number;
}) {
  return (
    <input
      type="number"
      min={min}
      max={max}
      step={step}
      value={value}
      onChange={(e) => onChange(Math.round(clamp(Number(e.target.value), min, max)))}
      className="w-full rounded-lg border border-zinc-200 bg-white px-3.5 py-2.5 text-[13px] text-zinc-900 outline-none transition-all duration-200 focus:border-zinc-400 focus:ring-4 focus:ring-zinc-900/5 shadow-[0_1px_2px_rgba(0,0,0,0.04)]"
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
      onChange={(e) => onChange(e.target.value)}
      className="w-full appearance-none rounded-lg border border-zinc-200 bg-white px-3.5 py-2.5 text-[13px] text-zinc-900 outline-none transition-all duration-200 focus:border-zinc-400 focus:ring-4 focus:ring-zinc-900/5 shadow-[0_1px_2px_rgba(0,0,0,0.04)] cursor-pointer"
    >
      {options.map((opt) => (
        <option key={opt.value} value={opt.value}>{opt.label}</option>
      ))}
    </select>
  );
}

function SliderInput({
  label,
  value,
  onChange,
  min,
  max,
  step,
}: {
  label: string;
  value: number;
  onChange: (value: number) => void;
  min: number;
  max: number;
  step: number;
}) {
  return (
    <div className="rounded-xl border border-zinc-100 bg-zinc-50/40 px-4 py-3.5 space-y-3">
      <div className="flex items-center justify-between">
        <label className="text-[13px] font-semibold text-zinc-700">{label}</label>
        <span className="rounded-md bg-white border border-zinc-200 px-2.5 py-0.5 text-[12px] font-mono font-bold text-zinc-800 shadow-[0_1px_2px_rgba(0,0,0,0.04)]">{value.toFixed(2)}</span>
      </div>
      <input
        type="range"
        min={min}
        max={max}
        step={step}
        value={value}
        onChange={(e) => onChange(clamp(Number(e.target.value), min, max))}
        className="w-full accent-zinc-900 h-1.5 rounded-full appearance-none bg-zinc-200 cursor-pointer [&::-webkit-slider-thumb]:appearance-none [&::-webkit-slider-thumb]:h-4 [&::-webkit-slider-thumb]:w-4 [&::-webkit-slider-thumb]:rounded-full [&::-webkit-slider-thumb]:bg-zinc-900 [&::-webkit-slider-thumb]:shadow-sm [&::-webkit-slider-thumb]:border-2 [&::-webkit-slider-thumb]:border-white"
      />
    </div>
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
      className="flex w-full items-center justify-between gap-4 rounded-xl border border-zinc-100 bg-white px-4 py-3.5 text-left transition-all duration-200 hover:border-zinc-200 hover:shadow-[0_2px_8px_rgba(0,0,0,0.03)]"
    >
      <span>
        <span className="block text-[13px] font-semibold text-zinc-800">{title}</span>
        <span className="mt-0.5 block text-[12px] text-zinc-400 leading-relaxed">{description}</span>
      </span>
      <span
        className={`relative inline-flex h-[22px] w-[42px] shrink-0 items-center rounded-full transition-colors duration-200 ${
          enabled ? "bg-zinc-900" : "bg-zinc-200"
        }`}
      >
        <span
          className={`inline-block h-[18px] w-[18px] rounded-full bg-white shadow-sm transition-transform duration-200 ${
            enabled ? "translate-x-[22px]" : "translate-x-[2px]"
          }`}
        />
      </span>
    </button>
  );
}

function InfoCard({ text, variant = "neutral" }: { text: string; variant?: "neutral" | "warning" }) {
  const style =
    variant === "warning"
      ? "border-amber-100 bg-amber-50/60 text-amber-700"
      : "border-zinc-100 bg-zinc-50/60 text-zinc-500";
  return (
    <div className={`rounded-xl border px-4 py-3 text-[12px] leading-relaxed ${style}`}>
      {text}
    </div>
  );
}

function SectionDivider({ label }: { label: string }) {
  return (
    <div className="flex items-center gap-3 pt-2">
      <span className="text-[11px] font-semibold uppercase tracking-widest text-zinc-400">{label}</span>
      <div className="h-px flex-1 bg-zinc-100" />
    </div>
  );
}

function displaySettingValue(entry: SettingEntry): string {
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

function SettingSourcePill({ source }: { source: SettingSource }) {
  const label = source === "env" ? ".env" : source === "settings" ? "settings.yaml" : "runtime";
  return (
    <span className="rounded-md bg-white border border-zinc-200 px-2 py-0.5 text-[11px] font-semibold text-zinc-500">
      {label}
    </span>
  );
}

function SettingStatusPill({ entry }: { entry: SettingEntry }) {
  const configured = entry.status === "configured" || entry.status === "runtime" || entry.status === "enabled";
  return (
    <span
      className={`rounded-md border px-2 py-0.5 text-[11px] font-semibold ${
        configured
          ? "border-emerald-100 bg-emerald-50/80 text-emerald-700"
          : "border-amber-100 bg-amber-50/80 text-amber-700"
      }`}
    >
      {configured ? "已生效" : "未配置"}
    </span>
  );
}

function BackendSettingList({
  entries,
  loading,
  error,
}: {
  entries: SettingEntry[];
  loading: boolean;
  error: string | null;
}) {
  if (loading) {
    return <InfoCard text="正在读取后端 .env 与 settings.yaml 当前生效配置..." />;
  }
  if (error) {
    return <InfoCard text={error} variant="warning" />;
  }
  if (entries.length === 0) {
    return <InfoCard text="后端暂未返回该分组配置。" />;
  }
  return (
    <div className="space-y-2.5">
      {entries.map((entry) => (
        <div key={entry.key} className="rounded-xl border border-zinc-100 bg-zinc-50/40 px-4 py-3.5 space-y-2">
          <div className="flex flex-wrap items-center justify-between gap-2">
            <div className="min-w-0">
              <div className="text-[13px] font-semibold text-zinc-700">{entry.label}</div>
              <div className="mt-0.5 font-mono text-[11px] text-zinc-400">{entry.key}</div>
            </div>
            <div className="flex items-center gap-1.5">
              <SettingSourcePill source={entry.source} />
              <SettingStatusPill entry={entry} />
            </div>
          </div>
          <div className="rounded-md bg-white border border-zinc-200 px-2.5 py-1.5 font-mono text-[12px] text-zinc-800">
            {displaySettingValue(entry)}
          </div>
          {entry.description ? <p className="text-[11px] leading-relaxed text-zinc-400">{entry.description}</p> : null}
        </div>
      ))}
    </div>
  );
}

/* ── Content transition wrapper ── */
const contentVariants = {
  initial: { opacity: 0, y: 8 },
  animate: { opacity: 1, y: 0, transition: { duration: 0.25, ease: "easeOut" as const } },
  exit: { opacity: 0, y: -4, transition: { duration: 0.15 } },
};

/* ── Main Component ── */

export function SettingsPanel({ isOpen, onClose }: SettingsModalProps) {
  const { settings, updateSettings } = useSettings();
  const [draft, setDraft] = useState<AppSettings>({ ...settings });
  const [activeSection, setActiveSection] = useState<SectionType>("credentials");
  const [showApiKey, setShowApiKey] = useState(false);
  const [isTestingConnection, setIsTestingConnection] = useState(false);
  const [saveState, setSaveState] = useState<SaveState>("idle");
  const [connectionStatus, setConnectionStatus] = useState<ConnectionStatus>("idle");
  const [connectionMessage, setConnectionMessage] = useState("");
  const [settingsOverview, setSettingsOverview] = useState<SettingsOverviewData | null>(null);
  const [isOverviewLoading, setIsOverviewLoading] = useState(false);
  const [overviewError, setOverviewError] = useState<string | null>(null);

  useEffect(() => {
    if (!isOpen) return;
    setDraft({ ...settings });
    setActiveSection("credentials");
    setShowApiKey(false);
    setIsTestingConnection(false);
    setSaveState("idle");
    setConnectionStatus("idle");
    setConnectionMessage("");
    setOverviewError(null);
  }, [isOpen, settings]);

  useEffect(() => {
    if (!isOpen) return;
    let cancelled = false;

    async function loadSettingsOverview() {
      setIsOverviewLoading(true);
      setOverviewError(null);
      try {
        const response = await apiClient<ApiResponse<SettingsOverviewData>>({
          url: "/api/v1/system/settings",
          method: "POST",
          data: {},
        });
        if (!cancelled) {
          setSettingsOverview(response.data);
        }
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

    void loadSettingsOverview();
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
    () => SECTIONS.find((entry) => entry.id === activeSection) ?? SECTIONS[0],
    [activeSection],
  );
  const hasChanges = JSON.stringify(draft) !== JSON.stringify(settings);
  const providerConfigured = draft.providerApiKey.trim().length > 0;
  const backendSectionMap = useMemo(
    () => Object.fromEntries((settingsOverview?.sections ?? []).map((section) => [section.id, section] as const)),
    [settingsOverview],
  );
  const getBackendEntries = (...sectionIds: string[]) =>
    sectionIds.flatMap((id) => backendSectionMap[id]?.entries ?? []);

  const patch = <K extends keyof AppSettings>(key: K, value: AppSettings[K]) => {
    setDraft((prev) => ({ ...prev, [key]: value }));
  };

  const saveSettings = () => {
    updateSettings(draft);
    setSaveState("saved");
    window.setTimeout(() => setSaveState("idle"), 1500);
  };

  const testConnection = async () => {
    const key = draft.providerApiKey.trim();
    if (!key) {
      setConnectionStatus("error");
      setConnectionMessage("请先填写 API Key。");
      return;
    }
    setIsTestingConnection(true);
    setConnectionStatus("idle");
    setConnectionMessage("");
    const endpoint = `${(draft.providerBaseUrl.trim() || DEFAULT_PROVIDER_BASE_URL).replace(/\/$/, "")}/models`;
    try {
      const response = await fetch(endpoint, { method: "GET", headers: { Authorization: `Bearer ${key}` } });
      if (response.ok) {
        setConnectionStatus("success");
        setConnectionMessage("连接成功：已可访问 models 接口。");
      } else {
        setConnectionStatus("error");
        setConnectionMessage(`连接失败：HTTP ${response.status}`);
      }
    } catch (error) {
      setConnectionStatus("error");
      setConnectionMessage(error instanceof Error ? error.message : "连接失败，请检查网络。");
    } finally {
      setIsTestingConnection(false);
    }
  };

  /* ── Section Content Renderers ── */

  const renderCredentials = () => (
    <div className="space-y-6">
      <InfoCard text="后端的模型服务地址、密钥、鉴权和部署模式来自 .env；页面只显示当前是否配置，不返回密钥明文。" />
      <BackendSettingList
        entries={getBackendEntries("runtime", "models").filter((entry) =>
          [
            "runtime.mode",
            "runtime.app_mode_raw",
            "runtime.version",
            "auth.enabled",
            "settings.path",
            "llm.base_url",
            "llm.api_key",
          ].includes(entry.key),
        )}
        loading={isOverviewLoading}
        error={overviewError}
      />

      <SectionDivider label="本机旧版直连设置" />
      <InfoCard text="下面几项仅保存在当前浏览器，当前主要后端流程不会写回 .env 或 settings.yaml。" variant="warning" />

      <FieldGroup label="模型服务地址（Base URL）">
        <TextInput
          value={draft.providerBaseUrl}
          onChange={(v) => patch("providerBaseUrl", v)}
          placeholder={DEFAULT_PROVIDER_BASE_URL}
        />
      </FieldGroup>

      <FieldGroup label="访问密钥（API Key）">
        <div className="flex gap-2">
          <input
            type={showApiKey ? "text" : "password"}
            value={draft.providerApiKey}
            onChange={(e) => patch("providerApiKey", e.target.value)}
            placeholder="sk-..."
            className="min-w-0 flex-1 rounded-lg border border-zinc-200 bg-white px-3.5 py-2.5 text-[13px] text-zinc-900 placeholder:text-zinc-300 outline-none transition-all duration-200 focus:border-zinc-400 focus:ring-4 focus:ring-zinc-900/5 shadow-[0_1px_2px_rgba(0,0,0,0.04)]"
          />
          <button
            type="button"
            onClick={() => setShowApiKey((v) => !v)}
            className="inline-flex h-[42px] w-[42px] items-center justify-center rounded-lg border border-zinc-200 bg-white text-zinc-400 shadow-[0_1px_2px_rgba(0,0,0,0.04)] transition-all hover:text-zinc-700 hover:border-zinc-300"
          >
            {showApiKey ? <EyeOff className="h-4 w-4" /> : <Eye className="h-4 w-4" />}
          </button>
          <button
            type="button"
            onClick={testConnection}
            disabled={isTestingConnection}
            className="inline-flex h-[42px] items-center gap-1.5 rounded-lg border border-zinc-200 bg-white px-3 text-[12px] font-medium text-zinc-600 shadow-[0_1px_2px_rgba(0,0,0,0.04)] transition-all hover:border-zinc-300 hover:text-zinc-900 disabled:opacity-50"
          >
            {isTestingConnection ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <Sparkles className="h-3.5 w-3.5" />}
            <span className="hidden sm:inline">测试</span>
          </button>
        </div>
      </FieldGroup>

      <AnimatePresence>
        {connectionStatus !== "idle" && (
          <motion.div
            initial={{ opacity: 0, height: 0 }}
            animate={{ opacity: 1, height: "auto" }}
            exit={{ opacity: 0, height: 0 }}
            className={`overflow-hidden rounded-xl border px-4 py-3 text-[12px] leading-relaxed ${
              connectionStatus === "success"
                ? "border-emerald-200 bg-emerald-50/60 text-emerald-700"
                : "border-red-200 bg-red-50/60 text-red-600"
            }`}
          >
            {connectionMessage}
          </motion.div>
        )}
      </AnimatePresence>

      <SectionDivider label="安全说明" />

      <div className="space-y-2.5">
        <InfoCard text="凭证仅保存在当前浏览器本地，不会自动同步到其他设备。" />
        <InfoCard text="只有你主动触发模型请求时，API Key 才会用于调用上游接口。" />
        <InfoCard text="共享设备建议在使用后清理站点缓存与本地存储。" variant="warning" />
      </div>
    </div>
  );

  const renderModels = () => (
    <div className="space-y-6">
      <InfoCard text="后端实际使用的模型来自 settings.yaml。修改这些值请编辑 settings.yaml 并重启后端。" />
      <BackendSettingList
        entries={getBackendEntries("models").filter((entry) =>
          [
            "models.primary",
            "models.reason",
            "models.light",
            "models.extract",
            "models.embedding",
            "models.embedding_dim",
            "models.ocr",
            "models.mermaid",
            "models.image_generation",
          ].includes(entry.key),
        )}
        loading={isOverviewLoading}
        error={overviewError}
      />

      <SectionDivider label="本机实验模型" />

      <FieldGroup label="模型提供方标识" hint="用于标记上游 API 路由的供应商">
        <TextInput value={draft.modelProvider} onChange={(v) => patch("modelProvider", v)} />
      </FieldGroup>

      <SectionDivider label="模型选择" />

      <FieldGroup label="主模型" hint="用于教学对话与主要回答">
        <TextInput value={draft.primaryModel} onChange={(v) => patch("primaryModel", v)} />
      </FieldGroup>
      <FieldGroup label="推理模型" hint="用于复杂分析与长链推理">
        <TextInput value={draft.reasoningModel} onChange={(v) => patch("reasoningModel", v)} />
      </FieldGroup>
      <FieldGroup label="向量模型" hint="用于召回与检索嵌入">
        <TextInput value={draft.embeddingModel} onChange={(v) => patch("embeddingModel", v)} />
      </FieldGroup>
      <FieldGroup label="兜底模型" hint="主模型不可用时备用">
        <TextInput value={draft.fallbackModel} onChange={(v) => patch("fallbackModel", v)} />
      </FieldGroup>
    </div>
  );

  const renderParser = () => (
    <div className="space-y-6">
      <InfoCard text="资料解析和检索的全局默认值来自后端 settings.yaml；上传时可用本机偏好临时指定 MinerU 参数。" />
      <BackendSettingList
        entries={getBackendEntries("ingest", "search").filter((entry) =>
          [
            "files.max_upload_size_mb",
            "ingest.parse_concurrency",
            "ingest.parser_timeout_s",
            "mineru.api_token",
            "ocr.api_key",
            "rag.top_k",
            "rag.similarity_threshold",
            "rag.rerank_model",
            "local_rag.priority",
            "local_rag.min_results",
            "web_search.retriever_profile",
            "web_search.retrievers",
            "search.parallel_retrievers",
            "search.max_parallel_retrievers",
            "search.fusion_k",
            "search.tavily_key",
            "search.brave_key",
            "search.exa_key",
            "search.searxng_url",
            "reader.jina_enabled",
          ].includes(entry.key),
        )}
        loading={isOverviewLoading}
        error={overviewError}
      />

      <SectionDivider label="本机上传偏好" />

      <FieldGroup label="解析引擎">
        <SelectInput
          value={draft.parserProvider}
          onChange={(v) => patch("parserProvider", v as ParserProvider)}
          options={[
            { value: "docling", label: "Docling" },
            { value: "unstructured", label: "Unstructured" },
            { value: "mineru", label: "MinerU" },
          ]}
        />
      </FieldGroup>

      {draft.parserProvider === "mineru" && (
        <motion.div
          initial={{ opacity: 0, height: 0 }}
          animate={{ opacity: 1, height: "auto" }}
          exit={{ opacity: 0, height: 0 }}
          className="space-y-5 overflow-hidden rounded-2xl border border-zinc-100 bg-zinc-50/30 p-4"
        >
          <FieldGroup
            label="MinerU API Token"
            hint="该 Token 仅保存在浏览器本地设置中；上传文件时会随请求传给后端用于本次解析。若部署端已配置 MINERU_API_TOKEN，可留空。"
          >
            <TextInput type="password" value={draft.mineruApiToken} onChange={(v) => patch("mineruApiToken", v)} placeholder="Bearer Token..." />
          </FieldGroup>
          <FieldGroup label="MinerU 模型版本">
            <SelectInput
              value={draft.mineruModelVersion}
              onChange={(v) => patch("mineruModelVersion", v as "vlm" | "pipeline")}
              options={[
                { value: "vlm", label: "vlm（推荐）" },
                { value: "pipeline", label: "pipeline" },
              ]}
            />
          </FieldGroup>
          <SwitchRow title="启用公式识别" description="尽量将公式转为可读文本而非图片。" enabled={draft.mineruEnableFormula} onToggle={() => patch("mineruEnableFormula", !draft.mineruEnableFormula)} />
          <SwitchRow title="启用表格识别" description="尽量保留表格结构。" enabled={draft.mineruEnableTable} onToggle={() => patch("mineruEnableTable", !draft.mineruEnableTable)} />
          <SwitchRow title="启用 OCR" description="针对图片型/扫描件启用文字识别（可能更慢）。" enabled={draft.mineruIsOcr} onToggle={() => patch("mineruIsOcr", !draft.mineruIsOcr)} />
        </motion.div>
      )}

      <SectionDivider label="解析模式" />

      <FieldGroup label="解析模式">
        <SelectInput
          value={draft.parserMode}
          onChange={(v) => patch("parserMode", v as ParserMode)}
          options={[
            { value: "balanced", label: "平衡" },
            { value: "quality", label: "质量优先" },
            { value: "speed", label: "速度优先" },
          ]}
        />
      </FieldGroup>

      <FieldGroup label="OCR 策略">
        <SelectInput
          value={draft.ocrProvider}
          onChange={(v) => patch("ocrProvider", v as OcrProvider)}
          options={[
            { value: "none", label: "关闭 OCR" },
            { value: "tesseract", label: "Tesseract" },
            { value: "azure-document-intelligence", label: "Azure Document Intelligence" },
          ]}
        />
      </FieldGroup>

      <SectionDivider label="切片参数" />

      <div className="grid grid-cols-2 gap-4">
        <FieldGroup label="分块长度（Chunk Size）">
          <NumberInput value={draft.parserChunkSize} onChange={(v) => patch("parserChunkSize", v)} min={256} max={4096} step={32} />
        </FieldGroup>
        <FieldGroup label="分块重叠（Overlap）">
          <NumberInput value={draft.parserChunkOverlap} onChange={(v) => patch("parserChunkOverlap", v)} min={0} max={1024} step={8} />
        </FieldGroup>
      </div>
      <SwitchRow title="表格抽取增强" description="启用后尽量保留文档中的表格结构。" enabled={draft.parserTableExtraction} onToggle={() => patch("parserTableExtraction", !draft.parserTableExtraction)} />

      <SectionDivider label="召回参数" />

      <div className="grid grid-cols-2 gap-4">
        <FieldGroup label="召回 Top-K">
          <NumberInput value={draft.retrievalTopK} onChange={(v) => patch("retrievalTopK", v)} min={1} max={30} step={1} />
        </FieldGroup>
        <div>
          <SliderInput label="召回阈值" value={draft.retrievalScoreThreshold} onChange={(v) => patch("retrievalScoreThreshold", v)} min={0} max={1} step={0.01} />
        </div>
      </div>
      <SwitchRow title="启用重排（Rerank）" description="先召回后重排，提升上下文质量。" enabled={draft.enableRerank} onToggle={() => patch("enableRerank", !draft.enableRerank)} />
      <SwitchRow title="允许联网补充" description="知识库不足时可用外部搜索补充。" enabled={draft.enableWebSearch} onToggle={() => patch("enableWebSearch", !draft.enableWebSearch)} />
    </div>
  );

  const renderGeneration = () => (
    <div className="space-y-6">
      <InfoCard text="这些生成参数目前是浏览器本机实验偏好；后端主流程的模型路由、温度和重试策略仍以代码与 settings.yaml 为准。" variant="warning" />
      <SliderInput label="采样温度（Temperature）" value={draft.generationTemperature} onChange={(v) => patch("generationTemperature", v)} min={0} max={2} step={0.05} />
      <SliderInput label="核心采样（Top-P）" value={draft.generationTopP} onChange={(v) => patch("generationTopP", v)} min={0} max={1} step={0.01} />

      <SectionDivider label="惩罚参数" />

      <div className="grid grid-cols-2 gap-4">
        <FieldGroup label="存在惩罚">
          <NumberInput value={draft.generationPresencePenalty} onChange={(v) => patch("generationPresencePenalty", v)} min={-2} max={2} step={0.1} />
        </FieldGroup>
        <FieldGroup label="频次惩罚">
          <NumberInput value={draft.generationFrequencyPenalty} onChange={(v) => patch("generationFrequencyPenalty", v)} min={-2} max={2} step={0.1} />
        </FieldGroup>
      </div>

      <SectionDivider label="输出控制" />

      <div className="grid grid-cols-2 gap-4">
        <FieldGroup label="最大输出长度">
          <NumberInput value={draft.generationMaxTokens} onChange={(v) => patch("generationMaxTokens", v)} min={256} max={32768} step={128} />
        </FieldGroup>
        <FieldGroup label="Seed（0 = 随机）">
          <NumberInput value={draft.generationSeed} onChange={(v) => patch("generationSeed", v)} min={0} max={999999999} step={1} />
        </FieldGroup>
      </div>
      <SwitchRow title="启用流式输出" description="对话时增量返回 token，首字更快。" enabled={draft.generationStream} onToggle={() => patch("generationStream", !draft.generationStream)} />
    </div>
  );

  const renderRuntime = () => (
    <div className="space-y-6">
      <InfoCard text="存储、数据库、LangSmith、缓存和安全护栏由后端环境变量与 settings.yaml 控制；下面先展示当前生效状态。" />
      <BackendSettingList
        entries={getBackendEntries("storage", "observability")}
        loading={isOverviewLoading}
        error={overviewError}
      />

      <SectionDivider label="本机联调" />

      <FieldGroup label="FastAPI 地址">
        <TextInput value={draft.apiUrl} onChange={(v) => patch("apiUrl", v)} placeholder="http://localhost:8000" />
      </FieldGroup>
      <FieldGroup label="请求超时（ms）">
        <NumberInput value={draft.runtimeRequestTimeoutMs} onChange={(v) => patch("runtimeRequestTimeoutMs", v)} min={3000} max={120000} step={500} />
      </FieldGroup>
      <SwitchRow title="启用本地 Mock" description="开启后优先使用前端 Mock 数据。" enabled={draft.useMock} onToggle={() => patch("useMock", !draft.useMock)} />

      <SectionDivider label="性能参数" />

      <FieldGroup label="最大并发任务数">
        <NumberInput value={draft.runtimeMaxConcurrency} onChange={(v) => patch("runtimeMaxConcurrency", v)} min={1} max={16} step={1} />
      </FieldGroup>
      <SwitchRow title="自动保存设置" description="开启后会在修改后自动落盘。" enabled={draft.autoSaveSettings} onToggle={() => patch("autoSaveSettings", !draft.autoSaveSettings)} />

      <SectionDivider label="调试" />

      <SwitchRow title="调试模式" description="显示更多中间调试信息，便于排查问题。" enabled={draft.debugMode} onToggle={() => patch("debugMode", !draft.debugMode)} />
    </div>
  );

  const RENDERERS: Record<SectionType, () => React.ReactNode> = {
    credentials: renderCredentials,
    models: renderModels,
    parser: renderParser,
    generation: renderGeneration,
    runtime: renderRuntime,
  };

  if (!isOpen) return null;

  return (
    <AnimatePresence>
      <motion.div
        initial={{ opacity: 0 }}
        animate={{ opacity: 1 }}
        exit={{ opacity: 0 }}
        transition={{ duration: 0.2 }}
        className="fixed inset-0 z-[100]"
      >
        {/* Backdrop */}
        <div className="absolute inset-0 bg-black/40 backdrop-blur-sm" onClick={onClose} />

        {/* Modal Container */}
        <div className="pointer-events-none absolute inset-0 flex items-center justify-center p-4 sm:p-8">
          <motion.div
            initial={{ opacity: 0, y: 16, scale: 0.97 }}
            animate={{ opacity: 1, y: 0, scale: 1 }}
            exit={{ opacity: 0, y: 10, scale: 0.97 }}
            transition={{ type: "spring", stiffness: 400, damping: 32 }}
            className="pointer-events-auto flex h-[min(720px,85vh)] w-full max-w-[880px] overflow-hidden rounded-2xl border border-zinc-200/60 bg-white shadow-[0_25px_80px_-20px_rgba(0,0,0,0.35)]"
          >
            {/* ── Left Navigation ── */}
            <nav className="flex w-[220px] shrink-0 flex-col border-r border-zinc-100 bg-zinc-50/70">
              {/* Header */}
              <div className="px-5 pt-5 pb-4">
                <h2 className="text-[15px] font-bold text-zinc-900">设置</h2>
              </div>

              {/* Nav Items */}
              <div className="flex-1 space-y-0.5 px-2.5 overflow-y-auto">
                {SECTIONS.map((entry) => {
                  const Icon = entry.icon;
                  const active = activeSection === entry.id;
                  return (
                    <button
                      key={entry.id}
                      type="button"
                      onClick={() => setActiveSection(entry.id)}
                      className={`flex w-full items-center gap-2.5 rounded-xl px-3 py-2.5 text-left transition-all duration-150 ${
                        active
                          ? "bg-white text-zinc-900 shadow-[0_1px_3px_rgba(0,0,0,0.06)]"
                          : "text-zinc-500 hover:bg-white/60 hover:text-zinc-700"
                      }`}
                    >
                      <span className={`inline-flex h-8 w-8 items-center justify-center rounded-lg transition-colors ${active ? "bg-zinc-900 text-white" : "bg-zinc-100 text-zinc-400"}`}>
                        <Icon className="h-4 w-4" />
                      </span>
                      <span className="text-[13px] font-medium">{entry.label}</span>
                    </button>
                  );
                })}
              </div>

              {/* Status badges */}
              <div className="flex flex-wrap gap-1.5 border-t border-zinc-100 px-4 py-3">
                <span className={`inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-[10px] font-medium ${
                  providerConfigured
                    ? "bg-emerald-50 text-emerald-600"
                    : "bg-amber-50 text-amber-600"
                }`}>
                  <span className={`h-1.5 w-1.5 rounded-full ${providerConfigured ? "bg-emerald-500" : "bg-amber-500"}`} />
                  {providerConfigured ? "凭证已配置" : "凭证未配置"}
                </span>
                <span className={`inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-[10px] font-medium ${
                  draft.useMock
                    ? "bg-amber-50 text-amber-600"
                    : "bg-emerald-50 text-emerald-600"
                }`}>
                  <span className={`h-1.5 w-1.5 rounded-full ${draft.useMock ? "bg-amber-500" : "bg-emerald-500"}`} />
                  {draft.useMock ? "Mock 模式" : "真实后端"}
                </span>
              </div>
            </nav>

            {/* ── Right Content ── */}
            <div className="flex min-w-0 flex-1 flex-col">
              {/* Content Header */}
              <div className="flex items-center justify-between border-b border-zinc-100 px-6 py-4">
                <div>
                  <h3 className="text-[16px] font-bold text-zinc-900">{activeSectionConfig.label}</h3>
                  <p className="mt-0.5 text-[12px] text-zinc-400">{activeSectionConfig.description}</p>
                </div>
                <button
                  type="button"
                  onClick={onClose}
                  className="inline-flex h-8 w-8 items-center justify-center rounded-lg text-zinc-400 transition-colors hover:bg-zinc-100 hover:text-zinc-600"
                  aria-label="关闭设置"
                >
                  <X className="h-4 w-4" />
                </button>
              </div>

              {/* Scrollable Content */}
              <div className="min-h-0 flex-1 overflow-y-auto px-6 py-5">
                <AnimatePresence mode="wait">
                  <motion.div
                    key={activeSection}
                    variants={contentVariants}
                    initial="initial"
                    animate="animate"
                    exit="exit"
                  >
                    {RENDERERS[activeSection]()}
                  </motion.div>
                </AnimatePresence>
              </div>

              {/* Footer */}
              <div className="flex items-center justify-between border-t border-zinc-100 bg-zinc-50/50 px-6 py-3">
                <div className="flex items-center gap-1.5 text-[12px] text-zinc-400">
                  <AnimatePresence mode="wait">
                    {saveState === "saved" ? (
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
                    onClick={() => setDraft({ ...DEFAULT_SETTINGS })}
                    className="rounded-lg px-3 py-1.5 text-[12px] font-medium text-zinc-500 transition-colors hover:bg-zinc-100 hover:text-zinc-700"
                  >
                    恢复默认
                  </button>
                  <button
                    type="button"
                    onClick={saveSettings}
                    disabled={!hasChanges}
                    className={`rounded-lg px-4 py-1.5 text-[12px] font-semibold transition-all duration-200 ${
                      hasChanges
                        ? "bg-zinc-900 text-white shadow-sm hover:bg-zinc-800 active:scale-[0.98]"
                        : "bg-zinc-100 text-zinc-300 cursor-not-allowed"
                    }`}
                  >
                    保存设置
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
