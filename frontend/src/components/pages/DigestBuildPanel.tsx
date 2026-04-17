import { createContext, useContext, useEffect, useMemo, useState, type ReactNode } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import {
  CheckCircle2,
  Clock3,
  FileText,
  Loader2,
  Play,
  Sparkles,
  Target,
} from "lucide-react";

import { apiClient } from "../../api/client";
import type { ApiResponse } from "../../api/types";
import { useKnowledgeBuildFlow } from "../../hooks/useKnowledgeBuildFlow";
import type { FileRecord } from "../../types/files";
import { KnowledgeBuildResolutionModal } from "./KnowledgeBuildResolutionModal";
import { Button } from "../ui/Button";
import { Modal } from "../ui/Modal";

interface DigestBuildContextValue {
  subject: string;
}

interface FilesData {
  items: FileRecord[];
}

interface DocBuildStatus {
  status?: string | null;
  requested_at?: string | null;
  stage?: string | null;
  error_message?: string | null;
  draft_available?: boolean;
}

interface BuildSampleCard {
  title: string;
  card_type: string;
  summary: string;
}

interface BuildPreviewNode {
  name: string;
  knowledge_unit_type: string;
}

interface KnowledgeBuildPreview {
  current_stage_description?: string | null;
  digest_mode?: string | null;
  mode_reason?: string | null;
  processed_chunks?: number;
  total_chunks?: number;
  discovered_node_count?: number;
  discovered_node_types?: Record<string, number>;
  sample_nodes?: BuildPreviewNode[];
  sample_cards?: BuildSampleCard[];
  latest_chapter_titles?: string[];
  draft_excerpt?: string;
}

interface KnowledgeBuildMetrics {
  llm_total_calls?: number;
  failed_llm_call_count?: number;
  llm_avg_latency_ms?: number;
  call_count_by_lane?: Record<string, number>;
}

interface KnowledgeDocsBuildState {
  exists: boolean;
  markdown?: string;
  updated_at?: string | null;
  draft_markdown?: string;
  draft_updated_at?: string | null;
  build?: DocBuildStatus | null;
  build_preview?: KnowledgeBuildPreview | null;
  build_metrics?: KnowledgeBuildMetrics | null;
}

interface DerivedBuildState {
  status: string;
  statusText: string;
  progressFloor: number;
  progressCap: number;
  hasLiveVersion: boolean;
  hasDraftVersion: boolean;
  isActive: boolean;
  isFailed: boolean;
  isCompleted: boolean;
}

const DigestBuildContext = createContext<DigestBuildContextValue | null>(null);
const ACTIVE_BUILD_STATUSES = new Set(["accepted", "running", "publishing"]);

const STAGE_PROGRESS_FLOOR: Record<string, number> = {
  build_accepted: 8,
  planner_confirmed: 16,
  prepare_shared: 22,
  preparing_docgen_context: 30,
  generating_chapters: 46,
  enhancing_chapters: 62,
  chapters_enhanced: 72,
  merge_reviewed: 82,
  doc_lane_staged: 90,
  docgen_finalized: 94,
  graph_ready: 96,
  publishing: 93,
  completed: 100,
};

const STAGE_PROGRESS_CAP: Record<string, number> = {
  build_accepted: 20,
  planner_confirmed: 28,
  prepare_shared: 42,
  preparing_docgen_context: 42,
  generating_chapters: 66,
  enhancing_chapters: 78,
  chapters_enhanced: 84,
  merge_reviewed: 90,
  doc_lane_staged: 94,
  docgen_finalized: 97,
  graph_ready: 98,
  publishing: 98,
  completed: 100,
};

const STAGE_TEXT: Record<string, string> = {
  idle: "等待新的知识构建任务",
  build_accepted: "已接收构建请求，正在准备资料",
  planner_confirmed: "已读取确认方案",
  prepare_shared: "正在分析资料结构并准备共享输入",
  preparing_docgen_context: "正在增强大纲、识别写法并摘要材料",
  generating_chapters: "正在并行生成章节",
  enhancing_chapters: "正在增强章节图示、例题和小结",
  chapters_enhanced: "章节增强已完成",
  merge_reviewed: "整本文档检查完成，准备发布",
  doc_lane_staged: "知识文档草稿已生成，正在发布正式版",
  docgen_finalized: "知识文档已发布，正在同步知识图谱",
  graph_ready: "知识图谱已就绪，正在推导课程结构",
  publishing: "正在发布正式版知识文档",
  completed: "最新知识文档已发布",
  failed: "知识构建失败，请稍后重试",
  cancelled: "本轮知识构建已取消",
};

async function fetchCompletedFiles(subject: string): Promise<FileRecord[]> {
  const response = await apiClient<ApiResponse<FilesData>>({
    method: "GET",
    url: `/api/v1/subjects/${subject}/files`,
  });
  return (response.data?.items ?? []).filter((file) => file.markdown_ready);
}

async function fetchKnowledgeDocsBuildState(subject: string): Promise<KnowledgeDocsBuildState> {
  const response = await apiClient<ApiResponse<KnowledgeDocsBuildState>>({
    method: "POST",
    url: `/api/v1/subjects/${subject}/knowledge/docs`,
  });
  return (
    response.data ?? {
      exists: false,
      markdown: "",
      draft_markdown: "",
      build: {
        status: "idle",
        stage: "idle",
      },
    }
  );
}

function parseIsoTimestamp(value?: string | null): number | null {
  if (!value) {
    return null;
  }
  const parsed = Date.parse(value);
  return Number.isNaN(parsed) ? null : parsed;
}

function deriveBuildState(data: KnowledgeDocsBuildState | undefined): DerivedBuildState {
  const liveMarkdown = data?.markdown ?? "";
  const draftMarkdown = data?.draft_markdown ?? "";
  const build = data?.build ?? null;
  const preview = data?.build_preview ?? null;
  const stage = build?.stage?.trim() || "idle";
  const status = build?.status?.trim() || (data?.exists ? "completed" : "idle");

  const hasLiveVersion = Boolean(data?.exists && liveMarkdown.trim().length > 0);
  const hasDraftVersion = Boolean(draftMarkdown.trim().length > 0);
  const isCompleted = status === "completed" || (hasLiveVersion && !ACTIVE_BUILD_STATUSES.has(status));
  const isFailed = status === "failed" || status === "cancelled";
  const isActive = ACTIVE_BUILD_STATUSES.has(status);

  let statusText =
    preview?.current_stage_description?.trim() ||
    STAGE_TEXT[stage] ||
    STAGE_TEXT[status] ||
    "Building knowledge content";
  if (build?.error_message?.trim()) {
    statusText = build.error_message;
  } else if (status === "idle" && hasLiveVersion) {
    statusText = "Latest published knowledge document is available.";
  } else if (status === "idle" && !hasLiveVersion) {
    statusText = "Waiting for the next knowledge build.";
  }

  if (isCompleted) {
    return {
      status,
      statusText,
      progressFloor: 100,
      progressCap: 100,
      hasLiveVersion,
      hasDraftVersion,
      isActive: false,
      isFailed: false,
      isCompleted: true,
    };
  }

  return {
    status,
    statusText,
    progressFloor: STAGE_PROGRESS_FLOOR[stage] ?? (hasDraftVersion ? 62 : 0),
    progressCap: STAGE_PROGRESS_CAP[stage] ?? (hasDraftVersion ? 78 : 45),
    hasLiveVersion,
    hasDraftVersion,
    isActive,
    isFailed,
    isCompleted: false,
  };
}
function statusTone(state: DerivedBuildState): string {
  if (state.isFailed) {
    return "border-rose-200 bg-rose-50";
  }
  if (state.isCompleted) {
    return "border-emerald-200 bg-emerald-50";
  }
  if (state.isActive) {
    return "border-sky-200 bg-sky-50";
  }
  return "border-slate-200 bg-white";
}

function previewCardTone(cardType?: string): string {
  switch ((cardType ?? "").toLowerCase()) {
    case "mode":
      return "border-sky-200 bg-sky-50";
    case "topic":
      return "border-emerald-200 bg-emerald-50";
    case "concept":
      return "border-blue-200 bg-blue-50";
    case "method":
      return "border-amber-200 bg-amber-50";
    default:
      return "border-slate-200 bg-slate-50";
  }
}

function formatLatency(ms?: number): string | null {
  if (!ms || ms <= 0) {
    return null;
  }
  if (ms < 1000) {
    return `${Math.round(ms)}ms`;
  }
  return `${(ms / 1000).toFixed(1)}s`;
}

export function DigestBuildProvider({
  subject,
  children,
}: {
  subject: string;
  children: ReactNode;
}) {
  return <DigestBuildContext.Provider value={{ subject }}>{children}</DigestBuildContext.Provider>;
}

function useDigestBuild() {
  const context = useContext(DigestBuildContext);
  if (!context) {
    throw new Error("useDigestBuild must be used inside DigestBuildProvider");
  }
  return context;
}

export function useKnowledgeDocsBuildState(subjectOverride?: string) {
  const context = useContext(DigestBuildContext);
  const subject = subjectOverride ?? context?.subject ?? "";

  return useQuery({
    queryKey: ["knowledge-doc-build", subject],
    queryFn: () => fetchKnowledgeDocsBuildState(subject),
    enabled: Boolean(subject),
    refetchInterval: (query) => {
      const data = query.state.data;
      const buildStatus = data?.build?.status ?? null;

      if (buildStatus && ACTIVE_BUILD_STATUSES.has(buildStatus)) {
        return 2500;
      }

      if (!buildStatus || buildStatus === "idle") {
        return 10000;
      }

      const requestedAtMs = parseIsoTimestamp(data?.build?.requested_at);
      const updatedAtMs = parseIsoTimestamp(data?.updated_at);
      if (requestedAtMs !== null && (updatedAtMs === null || updatedAtMs < requestedAtMs)) {
        return 2500;
      }

      return 10000;
    },
  });
}

export function DigestBuildProgress({
  subject: subjectOverride,
  compact = false,
  className = "",
}: {
  subject?: string;
  compact?: boolean;
  className?: string;
}) {
  const { data, isFetching } = useKnowledgeDocsBuildState(subjectOverride);
  const derived = useMemo(() => deriveBuildState(data), [data]);
  const [animatedProgress, setAnimatedProgress] = useState(derived.progressFloor);

  useEffect(() => {
    if (derived.isCompleted) {
      setAnimatedProgress(100);
      return;
    }

    if (derived.isFailed || (!derived.isActive && !derived.hasDraftVersion)) {
      setAnimatedProgress(derived.progressFloor);
      return;
    }

    setAnimatedProgress((previous) => Math.max(previous, derived.progressFloor));

    const timer = window.setInterval(() => {
      setAnimatedProgress((previous) => {
        if (previous >= derived.progressCap) {
          return derived.progressCap;
        }
        if (previous < 20) {
          return Math.min(derived.progressCap, previous + 6);
        }
        if (previous < 50) {
          return Math.min(derived.progressCap, previous + 4);
        }
        if (previous < 75) {
          return Math.min(derived.progressCap, previous + 2.5);
        }
        return Math.min(derived.progressCap, previous + 1.2);
      });
    }, 600);

    return () => window.clearInterval(timer);
  }, [
    derived.hasDraftVersion,
    derived.isActive,
    derived.isCompleted,
    derived.isFailed,
    derived.progressCap,
    derived.progressFloor,
  ]);

  const progress = Math.max(0, Math.min(100, Math.round(animatedProgress)));
  const tone = statusTone(derived);
  const stageBadge = data?.build?.stage?.trim() || "idle";
  const preview = data?.build_preview ?? null;
  const metrics = data?.build_metrics ?? null;
  const displayStatusText = preview?.current_stage_description?.trim() || derived.statusText;
  const throughputLabel =
    (preview?.total_chunks ?? 0) > 0 ? `${preview?.processed_chunks ?? 0}/${preview?.total_chunks ?? 0} chunks` : null;
  const nodeCountLabel =
    (preview?.discovered_node_count ?? 0) > 0 ? `${preview?.discovered_node_count ?? 0} nodes` : null;
  const llmCallLabel =
    (metrics?.llm_total_calls ?? 0) > 0 ? `${metrics?.llm_total_calls ?? 0} LLM calls` : null;
  const latencyLabel = formatLatency(metrics?.llm_avg_latency_ms);
  const laneLabels = Object.entries(metrics?.call_count_by_lane ?? {})
    .filter(([, count]) => count > 0)
    .slice(0, compact ? 2 : 3)
    .map(([lane, count]) => `${lane}:${count}`);
  const previewCards = preview?.sample_cards ?? [];
  const previewNodes = preview?.sample_nodes ?? [];
  const latestChapterTitles = preview?.latest_chapter_titles ?? [];
  const draftExcerpt = preview?.draft_excerpt?.trim() ?? "";

  return (
    <section className={`rounded-2xl border px-4 py-4 shadow-sm ${tone} ${className}`.trim()}>
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="min-w-0 flex-1">
          <div className="flex items-center gap-2 text-slate-900">
            {derived.isActive ? (
              <Loader2 className="h-4 w-4 animate-spin text-sky-600" />
            ) : (
              <Sparkles className="h-4 w-4 text-sky-600" />
            )}
            <p className="text-sm font-semibold">{displayStatusText}</p>
          </div>
          <p className="mt-1 text-xs leading-5 text-slate-600">
            {derived.hasDraftVersion
              ? "Draft is available. The page keeps polling and will switch after document publish."
              : "Progress is estimated on the frontend and synced via POST /knowledge/docs polling."}
          </p>
        </div>
        <div className="flex flex-wrap items-center gap-2 text-[11px] text-slate-600">
          <span className="rounded-full bg-white/80 px-2.5 py-1 font-medium">{stageBadge}</span>
          {derived.hasLiveVersion ? <span className="rounded-full bg-white/80 px-2.5 py-1">published</span> : null}
          {derived.hasDraftVersion ? <span className="rounded-full bg-white/80 px-2.5 py-1">draft</span> : null}
        </div>
      </div>

      <div className="mt-4">
        <div className="flex items-center justify-between text-xs text-slate-600">
          <div className="flex items-center gap-2">
            <Target className="h-3.5 w-3.5" />
            <span>{progress}%</span>
          </div>
          <span>{derived.status}</span>
        </div>
        <div className="mt-2 h-2 overflow-hidden rounded-full bg-white/90">
          <div
            className="h-full rounded-full bg-[linear-gradient(90deg,#0f172a_0%,#0ea5e9_55%,#22c55e_100%)] transition-[width] duration-500"
            style={{ width: `${progress}%` }}
          />
        </div>
      </div>

      {throughputLabel || nodeCountLabel || llmCallLabel || latencyLabel || laneLabels.length > 0 ? (
        <div className="mt-3 flex flex-wrap gap-2 text-[11px] text-slate-600">
          {throughputLabel ? <span className="rounded-full bg-white/80 px-2.5 py-1">{throughputLabel}</span> : null}
          {nodeCountLabel ? <span className="rounded-full bg-white/80 px-2.5 py-1">{nodeCountLabel}</span> : null}
          {llmCallLabel ? <span className="rounded-full bg-white/80 px-2.5 py-1">{llmCallLabel}</span> : null}
          {latencyLabel ? <span className="rounded-full bg-white/80 px-2.5 py-1">avg {latencyLabel}</span> : null}
          {laneLabels.map((label) => (
            <span key={label} className="rounded-full bg-white/80 px-2.5 py-1">
              {label}
            </span>
          ))}
        </div>
      ) : null}

      {!compact ? (
        <div className="mt-3 flex flex-wrap gap-2 text-[11px] text-slate-600">
          <span className="rounded-full bg-white/80 px-2.5 py-1">
            {derived.hasLiveVersion ? "Live published doc available" : "No live published doc yet"}
          </span>
          <span className="rounded-full bg-white/80 px-2.5 py-1">
            {derived.hasDraftVersion ? "Draft preview available" : "Draft preview not ready"}
          </span>
          {data?.build?.requested_at ? (
            <span className="rounded-full bg-white/80 px-2.5 py-1">
              <Clock3 className="mr-1 inline h-3 w-3" />
              {new Date(data.build.requested_at).toLocaleString("zh-CN")}
            </span>
          ) : null}
        </div>
      ) : null}

      {!compact && previewCards.length > 0 ? (
        <div className="mt-4 grid gap-3 md:grid-cols-2">
          {previewCards.slice(0, 4).map((card) => (
            <article
              key={`${card.card_type}-${card.title}`}
              className={`rounded-xl border px-3 py-3 ${previewCardTone(card.card_type)}`}
            >
              <div className="flex items-center justify-between gap-2">
                <p className="text-sm font-medium text-slate-900">{card.title}</p>
                <span className="rounded-full bg-white/80 px-2 py-0.5 text-[10px] uppercase tracking-wide text-slate-500">
                  {card.card_type}
                </span>
              </div>
              <p className="mt-2 text-xs leading-5 text-slate-600">{card.summary}</p>
            </article>
          ))}
        </div>
      ) : null}

      {!compact && previewCards.length === 0 && previewNodes.length > 0 ? (
        <div className="mt-4 rounded-xl border border-slate-200 bg-white/80 px-3 py-3">
          <p className="text-xs font-medium uppercase tracking-wide text-slate-500">Preview Nodes</p>
          <div className="mt-2 flex flex-wrap gap-2">
            {previewNodes.slice(0, 6).map((node) => (
              <span
                key={`${node.knowledge_unit_type}-${node.name}`}
                className="rounded-full border border-slate-200 bg-slate-50 px-2.5 py-1 text-[11px] text-slate-600"
              >
                {node.knowledge_unit_type}: {node.name}
              </span>
            ))}
          </div>
        </div>
      ) : null}

      {!compact && (latestChapterTitles.length > 0 || draftExcerpt) ? (
        <div className="mt-4 rounded-xl border border-slate-200 bg-white/80 px-3 py-3">
          {latestChapterTitles.length > 0 ? (
            <>
              <p className="text-xs font-medium uppercase tracking-wide text-slate-500">Draft Outline</p>
              <div className="mt-2 flex flex-wrap gap-2">
                {latestChapterTitles.slice(0, 4).map((title) => (
                  <span key={title} className="rounded-full bg-slate-100 px-2.5 py-1 text-[11px] text-slate-600">
                    {title}
                  </span>
                ))}
              </div>
            </>
          ) : null}
          {draftExcerpt ? (
            <pre className="mt-3 overflow-hidden whitespace-pre-wrap rounded-lg bg-slate-950 px-3 py-3 text-[11px] leading-5 text-slate-100">
              {draftExcerpt}
            </pre>
          ) : null}
        </div>
      ) : null}

      {data?.build?.error_message ? <p className="mt-3 text-xs text-rose-600">{data.build.error_message}</p> : null}
      {isFetching ? <p className="mt-2 text-[11px] text-slate-500">Syncing latest build state...</p> : null}
    </section>
  );
}
export function DigestBuildButton() {
  const { subject } = useDigestBuild();
  const queryClient = useQueryClient();

  const [showFileSelect, setShowFileSelect] = useState(false);
  const [selectedFileUids, setSelectedFileUids] = useState<Set<string>>(new Set());
  const [lastBuildError, setLastBuildError] = useState("");
  const [lastBuildMessage, setLastBuildMessage] = useState("");

  const { data: readyFiles = [], isLoading: filesLoading } = useQuery({
    queryKey: ["digest-files", subject],
    queryFn: () => fetchCompletedFiles(subject),
    enabled: showFileSelect && Boolean(subject),
  });

  useEffect(() => {
    if (!showFileSelect || readyFiles.length === 0 || selectedFileUids.size > 0) {
      return;
    }
    setSelectedFileUids(new Set(readyFiles.map((file) => file.uid)));
  }, [readyFiles, selectedFileUids.size, showFileSelect]);

  const selectedFiles = useMemo(
    () => readyFiles.filter((file) => selectedFileUids.has(file.uid)),
    [readyFiles, selectedFileUids],
  );

  const knowledgeBuild = useKnowledgeBuildFlow({
    subjectId: subject,
    buildRequest: () => ({
      file_uids: Array.from(selectedFileUids),
    }),
    fallbackErrorMessage: "触发知识构建失败。",
    onSuccess: (data) => {
      queryClient.invalidateQueries({ queryKey: ["knowledge-doc-build", subject] });
      queryClient.invalidateQueries({ queryKey: ["knowledge-overview", subject] });
      queryClient.invalidateQueries({ queryKey: ["docgen-content", subject] });
      setShowFileSelect(false);
      setSelectedFileUids(new Set());
      setLastBuildError("");
      setLastBuildMessage(
        `已触发知识构建，本轮纳入 ${(data.accepted_file_uids ?? []).length} 份资料，文档和图谱会同步刷新。`,
      );
    },
  });

  useEffect(() => {
    if (!knowledgeBuild.errorMessage) {
      return;
    }
    setLastBuildMessage("");
    setLastBuildError(knowledgeBuild.errorMessage);
  }, [knowledgeBuild.errorMessage]);

  const isBuilding = knowledgeBuild.isPending;

  const toggleFile = (fileUid: string) => {
    setSelectedFileUids((previous) => {
      const next = new Set(previous);
      if (next.has(fileUid)) {
        next.delete(fileUid);
      } else {
        next.add(fileUid);
      }
      return next;
    });
  };

  const openModal = () => {
    setLastBuildError("");
    setShowFileSelect(true);
  };

  const closeModal = () => {
    if (isBuilding) {
      return;
    }
    setShowFileSelect(false);
  };

  return (
    <>
      <Button onClick={openModal} variant="outline" size="sm" disabled={isBuilding}>
        {isBuilding ? (
          <>
            <Loader2 className="mr-1 h-4 w-4 animate-spin" />
            构建中...
          </>
        ) : (
          <>
            <Sparkles className="mr-1 h-4 w-4" />
            开始构建
          </>
        )}
      </Button>

      {lastBuildMessage ? <p className="mt-2 text-xs text-emerald-600">{lastBuildMessage}</p> : null}
      {lastBuildError ? <p className="mt-2 text-xs text-rose-500">{lastBuildError}</p> : null}

      <Modal open={showFileSelect} onClose={closeModal} title="选择本轮知识构建使用的文件">
        <div className="space-y-4">
          <p className="text-sm leading-6 text-slate-500">
            这里选中的已解析文件会进入本轮 digest，系统会同步刷新知识文档和知识图谱。
          </p>

          {filesLoading ? (
            <div className="flex items-center py-4 text-sm text-slate-400">
              <Loader2 className="mr-2 h-4 w-4 animate-spin" />
              正在加载可用文件...
            </div>
          ) : null}

          {!filesLoading && readyFiles.length === 0 ? (
            <p className="py-4 text-sm text-slate-400">
              当前还没有可用于构建的已解析文件，请先上传并等待解析完成。
            </p>
          ) : null}

          {readyFiles.length > 0 ? (
            <>
              <div className="max-h-60 space-y-2 overflow-y-auto">
                {readyFiles.map((file) => {
                  const checked = selectedFileUids.has(file.uid);
                  return (
                    <label
                      key={file.uid}
                      className={`flex cursor-pointer items-center gap-3 rounded-lg border p-3 transition-colors ${
                        checked ? "border-slate-400 bg-slate-50" : "border-slate-200 hover:bg-slate-50"
                      }`}
                    >
                      <input
                        type="checkbox"
                        checked={checked}
                        onChange={() => toggleFile(file.uid)}
                        className="rounded border-slate-300"
                      />
                      <FileText className="h-4 w-4 text-slate-400" />
                      <div className="min-w-0 flex-1">
                        <p className="truncate text-sm text-slate-700">{file.filename}</p>
                        <p className="text-xs text-slate-400">
                          {file.filetype.toUpperCase()} · {file.status}
                        </p>
                      </div>
                      {checked ? <CheckCircle2 className="h-4 w-4 text-emerald-500" /> : null}
                    </label>
                  );
                })}
              </div>

              <div className="rounded-lg border border-slate-200 bg-slate-50 px-3 py-2 text-xs text-slate-500">
                已选择 {selectedFiles.length} 份文件进入本轮知识构建。
              </div>
            </>
          ) : null}

          <div className="flex justify-end gap-2 pt-2">
            <Button variant="outline" onClick={closeModal} disabled={isBuilding}>
              取消
            </Button>
            <Button onClick={() => knowledgeBuild.submitBuild()} disabled={selectedFileUids.size === 0 || isBuilding}>
              {isBuilding ? (
                <>
                  <Loader2 className="mr-1 h-4 w-4 animate-spin" />
                  提交中...
                </>
              ) : (
                <>
                  <Play className="mr-1 h-4 w-4" />
                  开始构建
                </>
              )}
            </Button>
          </div>
        </div>
      </Modal>

      <KnowledgeBuildResolutionModal
        open={knowledgeBuild.precheckConflict !== null}
        conflict={knowledgeBuild.precheckConflict}
        isSubmitting={knowledgeBuild.isPending}
        onClose={knowledgeBuild.closePrecheckConflict}
        onResolve={knowledgeBuild.resolvePrecheckConflict}
      />
    </>
  );
}

export function DigestBuildStatusMeta({ subject }: { subject: string }) {
  const { data } = useKnowledgeDocsBuildState(subject);
  const derived = useMemo(() => deriveBuildState(data), [data]);

  return (
    <div className="flex items-center gap-2 text-[11px] text-slate-500">
      <Clock3 className="h-3 w-3" />
      <span>{derived.statusText}</span>
    </div>
  );
}

