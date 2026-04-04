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

interface ItemConfig {
  id: string;
  label: string;
  description: string;
}

type SaveState = "idle" | "saved";
type ConnectionStatus = "idle" | "success" | "error";

const DEFAULT_PROVIDER_BASE_URL = "https://api.openai.com/v1";

const SECTIONS: SectionConfig[] = [
  { id: "credentials", label: "接口与凭证", description: "上游模型接口与密钥", icon: KeyRound },
  { id: "models", label: "模型配置", description: "主模型与辅助模型", icon: Bot },
  { id: "parser", label: "解析与检索", description: "文档解析与召回策略", icon: Wrench },
  { id: "generation", label: "生成参数", description: "采样、惩罚与输出", icon: SlidersHorizontal },
  { id: "runtime", label: "运行与调试", description: "后端联调与性能控制", icon: Server },
];

const SECTION_ITEMS: Record<SectionType, ItemConfig[]> = {
  credentials: [
    { id: "provider_access", label: "服务商接入", description: "接口地址、密钥、连接测试" },
    { id: "credential_security", label: "安全说明", description: "凭证落地与数据边界" },
  ],
  models: [
    { id: "provider", label: "模型提供方", description: "当前模型路由供应商标识" },
    { id: "primary", label: "主模型", description: "用于教学对话与主要回答" },
    { id: "reasoning", label: "推理模型", description: "用于复杂分析与长链推理" },
    { id: "embedding", label: "向量模型", description: "用于召回与检索嵌入" },
    { id: "fallback", label: "兜底模型", description: "主模型不可用时备用" },
  ],
  parser: [
    { id: "engine", label: "解析引擎", description: "文档解析器选择" },
    { id: "mode", label: "解析模式", description: "平衡 / 质量 / 速度" },
    { id: "ocr", label: "OCR 策略", description: "扫描文档识别方案" },
    { id: "chunking", label: "切片参数", description: "分块长度、重叠、表格抽取" },
    { id: "retrieval", label: "召回参数", description: "TopK、阈值、重排、联网" },
  ],
  generation: [
    { id: "sampling", label: "采样控制", description: "温度与 Top-P" },
    { id: "penalties", label: "惩罚参数", description: "存在惩罚与频次惩罚" },
    { id: "output", label: "输出控制", description: "最大长度、随机种子、流式输出" },
  ],
  runtime: [
    { id: "backend", label: "后端联调", description: "API 地址、Mock、超时" },
    { id: "performance", label: "性能参数", description: "并发与自动保存策略" },
    { id: "debug", label: "调试开关", description: "调试模式可见性" },
  ],
};

function clamp(value: number, min: number, max: number): number {
  if (!Number.isFinite(value)) return min;
  if (value < min) return min;
  if (value > max) return max;
  return value;
}

function toggleClass(enabled: boolean): string {
  return enabled ? "bg-slate-900" : "bg-slate-200";
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
      className="flex w-full items-center justify-between gap-4 rounded-xl border border-slate-200 bg-white px-4 py-3 text-left transition hover:border-slate-300"
    >
      <span>
        <span className="block text-sm font-semibold text-slate-900">{title}</span>
        <span className="mt-1 block text-sm text-slate-500">{description}</span>
      </span>
      <span className={`relative inline-flex h-6 w-11 items-center rounded-full ${toggleClass(enabled)}`}>
        <span
          className={`inline-block h-5 w-5 rounded-full bg-white shadow transition-transform ${
            enabled ? "translate-x-5" : "translate-x-0.5"
          }`}
        />
      </span>
    </button>
  );
}

export function SettingsPanel({ isOpen, onClose }: SettingsModalProps) {
  const { settings, updateSettings } = useSettings();
  const [draft, setDraft] = useState<AppSettings>({ ...settings });
  const [activeSection, setActiveSection] = useState<SectionType>("credentials");
  const [activeItemMap, setActiveItemMap] = useState<Record<SectionType, string>>({
    credentials: "provider_access",
    models: "provider",
    parser: "engine",
    generation: "sampling",
    runtime: "backend",
  });
  const [showApiKey, setShowApiKey] = useState(false);
  const [isTestingConnection, setIsTestingConnection] = useState(false);
  const [saveState, setSaveState] = useState<SaveState>("idle");
  const [connectionStatus, setConnectionStatus] = useState<ConnectionStatus>("idle");
  const [connectionMessage, setConnectionMessage] = useState("");

  useEffect(() => {
    if (!isOpen) return;
    setDraft({ ...settings });
    setActiveSection("credentials");
    setActiveItemMap({
      credentials: "provider_access",
      models: "provider",
      parser: "engine",
      generation: "sampling",
      runtime: "backend",
    });
    setShowApiKey(false);
    setIsTestingConnection(false);
    setSaveState("idle");
    setConnectionStatus("idle");
    setConnectionMessage("");
  }, [isOpen, settings]);

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
  const currentItems = SECTION_ITEMS[activeSection];
  const activeItemId = activeItemMap[activeSection] ?? currentItems[0].id;
  const activeItem = useMemo(
    () => currentItems.find((entry) => entry.id === activeItemId) ?? currentItems[0],
    [activeItemId, currentItems],
  );
  const hasChanges = JSON.stringify(draft) !== JSON.stringify(settings);
  const providerConfigured = draft.providerApiKey.trim().length > 0;

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

  const renderPanel = () => {
    if (activeSection === "credentials") {
      if (activeItem.id === "provider_access") {
        return (
          <div className="space-y-4">
            <div className="space-y-2">
              <label className="text-sm font-medium text-slate-700">模型服务地址（Base URL）</label>
              <input
                value={draft.providerBaseUrl}
                onChange={(event) => patch("providerBaseUrl", event.target.value)}
                placeholder={DEFAULT_PROVIDER_BASE_URL}
                className="w-full rounded-xl border border-slate-200 bg-slate-50 px-3 py-2.5 text-sm"
              />
            </div>
            <div className="space-y-2">
              <label className="text-sm font-medium text-slate-700">访问密钥（API Key）</label>
              <div className="flex gap-2">
                <input
                  type={showApiKey ? "text" : "password"}
                  value={draft.providerApiKey}
                  onChange={(event) => patch("providerApiKey", event.target.value)}
                  placeholder="sk-..."
                  className="min-w-0 flex-1 rounded-xl border border-slate-200 bg-slate-50 px-3 py-2.5 text-sm"
                />
                <button type="button" onClick={() => setShowApiKey((value) => !value)} className="rounded-xl border border-slate-200 bg-white px-3">
                  {showApiKey ? <EyeOff className="h-4 w-4" /> : <Eye className="h-4 w-4" />}
                </button>
                <button type="button" onClick={testConnection} disabled={isTestingConnection} className="inline-flex items-center rounded-xl border border-slate-200 bg-white px-3 text-sm text-slate-700">
                  {isTestingConnection ? <Loader2 className="h-4 w-4 animate-spin" /> : <Sparkles className="h-4 w-4" />}
                </button>
              </div>
            </div>
            {connectionStatus !== "idle" ? (
              <div className={`rounded-xl border px-3 py-2 text-sm ${connectionStatus === "success" ? "border-emerald-200 bg-emerald-50 text-emerald-700" : "border-red-200 bg-red-50 text-red-700"}`}>
                {connectionMessage}
              </div>
            ) : null}
          </div>
        );
      }
      return (
        <div className="space-y-3 text-sm text-slate-600">
          <div className="rounded-xl border border-slate-200 bg-slate-50 px-3 py-2.5">凭证仅保存在当前浏览器本地，不会自动同步到其他设备。</div>
          <div className="rounded-xl border border-slate-200 bg-slate-50 px-3 py-2.5">只有你主动触发模型请求时，API Key 才会用于调用上游接口。</div>
          <div className="rounded-xl border border-amber-200 bg-amber-50 px-3 py-2.5 text-amber-800">共享设备建议在使用后清理站点缓存与本地存储。</div>
        </div>
      );
    }

    if (activeSection === "models") {
      if (activeItem.id === "provider") {
        return (
          <div className="space-y-2">
            <label className="text-sm font-medium text-slate-700">模型提供方标识</label>
            <input value={draft.modelProvider} onChange={(event) => patch("modelProvider", event.target.value)} className="w-full rounded-xl border border-slate-200 bg-slate-50 px-3 py-2.5 text-sm" />
          </div>
        );
      }
      const modelField =
        activeItem.id === "primary"
          ? "primaryModel"
          : activeItem.id === "reasoning"
            ? "reasoningModel"
            : activeItem.id === "embedding"
              ? "embeddingModel"
              : "fallbackModel";
      return (
        <div className="space-y-2">
          <label className="text-sm font-medium text-slate-700">模型 ID</label>
          <input value={draft[modelField]} onChange={(event) => patch(modelField, event.target.value)} className="w-full rounded-xl border border-slate-200 bg-slate-50 px-3 py-2.5 text-sm" />
        </div>
      );
    }

    if (activeSection === "parser") {
      if (activeItem.id === "engine") {
        return (
          <div className="space-y-4">
            <div className="space-y-2">
              <label className="text-sm font-medium text-slate-700">解析引擎</label>
              <select
                value={draft.parserProvider}
                onChange={(event) => patch("parserProvider", event.target.value as ParserProvider)}
                className="w-full rounded-xl border border-slate-200 bg-slate-50 px-3 py-2.5 text-sm"
              >
                <option value="docling">Docling</option>
                <option value="unstructured">Unstructured</option>
                <option value="mineru">MinerU</option>
              </select>
            </div>

            {draft.parserProvider === "mineru" ? (
              <div className="space-y-4">
                <div className="space-y-2">
                  <label className="text-sm font-medium text-slate-700">MinerU API Token</label>
                  <input
                    type="password"
                    value={draft.mineruApiToken}
                    onChange={(event) => patch("mineruApiToken", event.target.value)}
                    placeholder="Bearer Token..."
                    className="w-full rounded-xl border border-slate-200 bg-slate-50 px-3 py-2.5 text-sm"
                  />
                  <p className="text-xs text-slate-500">
                    该 Token 仅保存在浏览器本地设置中；上传文件时会随请求传给后端用于本次解析。
                  </p>
                </div>

                <SwitchRow
                  title="启用公式识别（enable_formula）"
                  description="尽量将公式转为可读文本而非图片。"
                  enabled={draft.mineruEnableFormula}
                  onToggle={() => patch("mineruEnableFormula", !draft.mineruEnableFormula)}
                />
                <SwitchRow
                  title="启用表格识别（enable_table）"
                  description="尽量保留表格结构。"
                  enabled={draft.mineruEnableTable}
                  onToggle={() => patch("mineruEnableTable", !draft.mineruEnableTable)}
                />
                <SwitchRow
                  title="启用 OCR（is_ocr）"
                  description="针对图片型/扫描件启用文字识别（可能更慢）。"
                  enabled={draft.mineruIsOcr}
                  onToggle={() => patch("mineruIsOcr", !draft.mineruIsOcr)}
                />
              </div>
            ) : null}
          </div>
        );
      }
      if (activeItem.id === "mode") {
        return <select value={draft.parserMode} onChange={(event) => patch("parserMode", event.target.value as ParserMode)} className="w-full rounded-xl border border-slate-200 bg-slate-50 px-3 py-2.5 text-sm"><option value="balanced">平衡</option><option value="quality">质量优先</option><option value="speed">速度优先</option></select>;
      }
      if (activeItem.id === "ocr") {
        return <select value={draft.ocrProvider} onChange={(event) => patch("ocrProvider", event.target.value as OcrProvider)} className="w-full rounded-xl border border-slate-200 bg-slate-50 px-3 py-2.5 text-sm"><option value="none">关闭 OCR</option><option value="tesseract">Tesseract</option><option value="azure-document-intelligence">Azure Document Intelligence</option></select>;
      }
      if (activeItem.id === "chunking") {
        return (
          <div className="space-y-4">
            <div className="space-y-2">
              <label className="text-sm font-medium text-slate-700">分块长度（Chunk Size）</label>
              <input type="number" min={256} max={4096} step={32} value={draft.parserChunkSize} onChange={(event) => patch("parserChunkSize", Math.round(clamp(Number(event.target.value), 256, 4096)))} className="w-full rounded-xl border border-slate-200 bg-slate-50 px-3 py-2.5 text-sm" />
            </div>
            <div className="space-y-2">
              <label className="text-sm font-medium text-slate-700">分块重叠（Overlap）</label>
              <input type="number" min={0} max={1024} step={8} value={draft.parserChunkOverlap} onChange={(event) => patch("parserChunkOverlap", Math.round(clamp(Number(event.target.value), 0, 1024)))} className="w-full rounded-xl border border-slate-200 bg-slate-50 px-3 py-2.5 text-sm" />
            </div>
            <SwitchRow title="表格抽取增强" description="启用后尽量保留文档中的表格结构。" enabled={draft.parserTableExtraction} onToggle={() => patch("parserTableExtraction", !draft.parserTableExtraction)} />
          </div>
        );
      }
      return (
        <div className="space-y-4">
          <div className="space-y-2">
            <label className="text-sm font-medium text-slate-700">召回 Top-K</label>
            <input type="number" min={1} max={30} value={draft.retrievalTopK} onChange={(event) => patch("retrievalTopK", Math.round(clamp(Number(event.target.value), 1, 30)))} className="w-full rounded-xl border border-slate-200 bg-slate-50 px-3 py-2.5 text-sm" />
          </div>
          <div className="space-y-2">
            <label className="text-sm font-medium text-slate-700">召回阈值：{draft.retrievalScoreThreshold.toFixed(2)}</label>
            <input type="range" min={0} max={1} step={0.01} value={draft.retrievalScoreThreshold} onChange={(event) => patch("retrievalScoreThreshold", clamp(Number(event.target.value), 0, 1))} className="w-full accent-slate-900" />
          </div>
          <SwitchRow title="启用重排（Rerank）" description="先召回后重排，提升上下文质量。" enabled={draft.enableRerank} onToggle={() => patch("enableRerank", !draft.enableRerank)} />
          <SwitchRow title="允许联网补充" description="知识库不足时可用外部搜索补充。" enabled={draft.enableWebSearch} onToggle={() => patch("enableWebSearch", !draft.enableWebSearch)} />
        </div>
      );
    }

    if (activeSection === "generation") {
      if (activeItem.id === "sampling") {
        return (
          <div className="space-y-4">
            <div className="space-y-2">
              <label className="text-sm font-medium text-slate-700">采样温度（Temperature）：{draft.generationTemperature.toFixed(2)}</label>
              <input type="range" min={0} max={2} step={0.05} value={draft.generationTemperature} onChange={(event) => patch("generationTemperature", clamp(Number(event.target.value), 0, 2))} className="w-full accent-slate-900" />
            </div>
            <div className="space-y-2">
              <label className="text-sm font-medium text-slate-700">核心采样（Top-P）：{draft.generationTopP.toFixed(2)}</label>
              <input type="range" min={0} max={1} step={0.01} value={draft.generationTopP} onChange={(event) => patch("generationTopP", clamp(Number(event.target.value), 0, 1))} className="w-full accent-slate-900" />
            </div>
          </div>
        );
      }
      if (activeItem.id === "penalties") {
        return (
          <div className="space-y-4">
            <div className="space-y-2">
              <label className="text-sm font-medium text-slate-700">存在惩罚（Presence Penalty）</label>
              <input type="number" min={-2} max={2} step={0.1} value={draft.generationPresencePenalty} onChange={(event) => patch("generationPresencePenalty", clamp(Number(event.target.value), -2, 2))} className="w-full rounded-xl border border-slate-200 bg-slate-50 px-3 py-2.5 text-sm" />
            </div>
            <div className="space-y-2">
              <label className="text-sm font-medium text-slate-700">频次惩罚（Frequency Penalty）</label>
              <input type="number" min={-2} max={2} step={0.1} value={draft.generationFrequencyPenalty} onChange={(event) => patch("generationFrequencyPenalty", clamp(Number(event.target.value), -2, 2))} className="w-full rounded-xl border border-slate-200 bg-slate-50 px-3 py-2.5 text-sm" />
            </div>
          </div>
        );
      }
      return (
        <div className="space-y-4">
          <div className="space-y-2">
            <label className="text-sm font-medium text-slate-700">最大输出长度（Max Tokens）</label>
            <input type="number" min={256} max={32768} step={128} value={draft.generationMaxTokens} onChange={(event) => patch("generationMaxTokens", Math.round(clamp(Number(event.target.value), 256, 32768)))} className="w-full rounded-xl border border-slate-200 bg-slate-50 px-3 py-2.5 text-sm" />
          </div>
          <div className="space-y-2">
            <label className="text-sm font-medium text-slate-700">Seed（0 表示随机）</label>
            <input type="number" min={0} max={999999999} step={1} value={draft.generationSeed} onChange={(event) => patch("generationSeed", Math.round(clamp(Number(event.target.value), 0, 999999999)))} className="w-full rounded-xl border border-slate-200 bg-slate-50 px-3 py-2.5 text-sm" />
          </div>
          <SwitchRow title="启用流式输出" description="对话时增量返回 token，首字更快。" enabled={draft.generationStream} onToggle={() => patch("generationStream", !draft.generationStream)} />
        </div>
      );
    }

    if (activeItem.id === "backend") {
      return (
        <div className="space-y-4">
          <div className="space-y-2">
            <label className="text-sm font-medium text-slate-700">FastAPI 地址</label>
            <input value={draft.apiUrl} onChange={(event) => patch("apiUrl", event.target.value)} placeholder="http://localhost:8000" className="w-full rounded-xl border border-slate-200 bg-slate-50 px-3 py-2.5 text-sm" />
          </div>
          <div className="space-y-2">
            <label className="text-sm font-medium text-slate-700">请求超时（ms）</label>
            <input type="number" min={3000} max={120000} step={500} value={draft.runtimeRequestTimeoutMs} onChange={(event) => patch("runtimeRequestTimeoutMs", Math.round(clamp(Number(event.target.value), 3000, 120000)))} className="w-full rounded-xl border border-slate-200 bg-slate-50 px-3 py-2.5 text-sm" />
          </div>
          <SwitchRow title="启用本地 Mock" description="开启后优先使用前端 Mock 数据。" enabled={draft.useMock} onToggle={() => patch("useMock", !draft.useMock)} />
        </div>
      );
    }

    if (activeItem.id === "performance") {
      return (
        <div className="space-y-4">
          <div className="space-y-2">
            <label className="text-sm font-medium text-slate-700">最大并发任务数</label>
            <input type="number" min={1} max={16} value={draft.runtimeMaxConcurrency} onChange={(event) => patch("runtimeMaxConcurrency", Math.round(clamp(Number(event.target.value), 1, 16)))} className="w-full rounded-xl border border-slate-200 bg-slate-50 px-3 py-2.5 text-sm" />
          </div>
          <SwitchRow title="自动保存设置" description="开启后会在修改后自动落盘。" enabled={draft.autoSaveSettings} onToggle={() => patch("autoSaveSettings", !draft.autoSaveSettings)} />
        </div>
      );
    }

    return <SwitchRow title="调试模式" description="显示更多中间调试信息，便于排查问题。" enabled={draft.debugMode} onToggle={() => patch("debugMode", !draft.debugMode)} />;
  };

  if (!isOpen) return null;

  return (
    <AnimatePresence>
      <motion.div
        initial={{ opacity: 0 }}
        animate={{ opacity: 1 }}
        exit={{ opacity: 0 }}
        className="fixed inset-0 z-[100]"
      >
        <div className="absolute inset-0 bg-slate-950/45 backdrop-blur-sm" onClick={onClose} />
        <div className="pointer-events-none absolute inset-0 flex items-center justify-center p-3 sm:p-5">
          <motion.div
            initial={{ opacity: 0, y: 12, scale: 0.98 }}
            animate={{ opacity: 1, y: 0, scale: 1 }}
            exit={{ opacity: 0, y: 10, scale: 0.98 }}
            transition={{ type: "spring", stiffness: 340, damping: 30 }}
            className="pointer-events-auto h-[90vh] w-full max-w-[1240px] overflow-hidden rounded-[24px] border border-slate-200 bg-[linear-gradient(180deg,#f8fafc_0%,#eef2f7_100%)] shadow-[0_35px_130px_-40px_rgba(15,23,42,0.55)]"
          >
            <div className="grid h-full grid-cols-1 lg:grid-cols-[260px_300px_1fr]">
              <aside className="border-r border-slate-200 bg-white/70 p-3">
                <div className="mb-3 rounded-xl border border-slate-200 bg-white px-3 py-3">
                  <div className="text-xs uppercase tracking-[0.16em] text-slate-400">AITeachMe</div>
                  <div className="mt-1 text-lg font-semibold text-slate-900">设置中心</div>
                  <div className="mt-1 text-xs text-slate-500">全中文配置面板，按类别聚合管理。</div>
                </div>

                {SECTIONS.map((entry) => {
                  const Icon = entry.icon;
                  const active = activeSection === entry.id;
                  return (
                    <button
                      key={entry.id}
                      type="button"
                      onClick={() => setActiveSection(entry.id)}
                      className={`mb-2 flex w-full items-start gap-3 rounded-xl border px-3 py-2.5 text-left ${
                        active
                          ? "border-slate-900 bg-slate-900 text-white"
                          : "border-transparent bg-white text-slate-700 hover:border-slate-200 hover:bg-slate-50"
                      }`}
                    >
                      <span className={`mt-0.5 inline-flex h-7 w-7 items-center justify-center rounded-lg ${active ? "bg-white/10" : "bg-slate-100"}`}>
                        <Icon className="h-4 w-4" />
                      </span>
                      <span>
                        <span className="block text-sm font-semibold">{entry.label}</span>
                        <span className={`block text-xs ${active ? "text-slate-300" : "text-slate-500"}`}>
                          {entry.description}
                        </span>
                      </span>
                    </button>
                  );
                })}

                <div className="mt-3 flex flex-wrap gap-2">
                  <span className={`rounded-full border px-2 py-0.5 text-xs ${providerConfigured ? "border-emerald-200 bg-emerald-50 text-emerald-700" : "border-amber-200 bg-amber-50 text-amber-700"}`}>
                    {providerConfigured ? "凭证已配置" : "凭证未配置"}
                  </span>
                  <span className={`rounded-full border px-2 py-0.5 text-xs ${draft.useMock ? "border-amber-200 bg-amber-50 text-amber-700" : "border-emerald-200 bg-emerald-50 text-emerald-700"}`}>
                    {draft.useMock ? "Mock 模式" : "真实后端"}
                  </span>
                </div>
              </aside>

              <aside className="border-r border-slate-200 bg-white/60 p-3">
                <div className="mb-3 text-sm font-semibold text-slate-900">{activeSectionConfig.label}</div>
                <div className="space-y-2">
                  {currentItems.map((entry) => (
                    <button
                      key={entry.id}
                      type="button"
                      onClick={() => setActiveItemMap((prev) => ({ ...prev, [activeSection]: entry.id }))}
                      className={`w-full rounded-xl border px-3 py-2.5 text-left ${
                        activeItem.id === entry.id
                          ? "border-slate-300 bg-slate-50"
                          : "border-transparent bg-white hover:border-slate-200 hover:bg-slate-50"
                      }`}
                    >
                      <div className="text-sm font-semibold text-slate-900">{entry.label}</div>
                      <div className="text-xs text-slate-500">{entry.description}</div>
                    </button>
                  ))}
                </div>
              </aside>

              <section className="flex min-h-0 flex-col">
                <div className="flex items-center justify-between border-b border-white/80 bg-white/55 px-6 py-4">
                  <div>
                    <div className="text-xs uppercase tracking-[0.16em] text-slate-400">{activeSectionConfig.label}</div>
                    <h2 className="text-2xl font-semibold text-slate-950">{activeItem.label}</h2>
                    <p className="mt-1 text-sm text-slate-500">{activeItem.description}</p>
                  </div>
                  <button
                    type="button"
                    onClick={onClose}
                    className="inline-flex h-10 w-10 items-center justify-center rounded-xl border border-slate-200 bg-white text-slate-500 hover:text-slate-900"
                    aria-label="关闭设置"
                  >
                    <X className="h-4 w-4" />
                  </button>
                </div>

                <div className="min-h-0 flex-1 overflow-y-auto px-6 py-5">{renderPanel()}</div>

                <div className="flex items-center justify-between border-t border-white/80 bg-white/65 px-6 py-3">
                  <div className="flex items-center gap-2 text-sm text-slate-500">
                    {saveState === "saved" ? (
                      <>
                        <CheckCircle2 className="h-4 w-4 text-emerald-600" />
                        <span>设置已保存</span>
                      </>
                    ) : hasChanges ? (
                      <>
                        <RefreshCcw className="h-4 w-4 text-amber-600" />
                        <span>有未保存修改</span>
                      </>
                    ) : (
                      <>
                        <CheckCircle2 className="h-4 w-4 text-slate-400" />
                        <span>当前已同步</span>
                      </>
                    )}
                  </div>

                  <div className="flex gap-2">
                    <button
                      type="button"
                      onClick={() => setDraft({ ...DEFAULT_SETTINGS })}
                      className="rounded-xl border border-slate-200 bg-white px-3 py-2 text-sm"
                    >
                      恢复默认
                    </button>
                    <button
                      type="button"
                      onClick={onClose}
                      className="rounded-xl border border-transparent px-3 py-2 text-sm text-slate-600 hover:bg-slate-100"
                    >
                      关闭
                    </button>
                    <button
                      type="button"
                      onClick={saveSettings}
                      disabled={!hasChanges}
                      className="rounded-xl bg-slate-950 px-4 py-2 text-sm text-white disabled:cursor-not-allowed disabled:bg-slate-300"
                    >
                      保存设置
                    </button>
                  </div>
                </div>
              </section>
            </div>
          </motion.div>
        </div>
      </motion.div>
    </AnimatePresence>
  );
}
