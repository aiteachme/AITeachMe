import { useEffect, useMemo, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import {
  AlertTriangle,
  CheckCircle2,
  Clock3,
  Loader2,
  Network,
  Sparkles,
} from "lucide-react";

import {
  buildKnowledgeBuildRuntimeQueryKey,
  buildRuntimeFailureBackoffMs,
  fetchKnowledgeBuildRuntime,
  type KnowledgeBuildLaneRuntime,
  type KnowledgeBuildRuntimeResponse,
} from "../../lib/knowledgeBuildRuntime";

interface DerivedBuildState {
  aggregate: KnowledgeBuildLaneRuntime;
  docgen: KnowledgeBuildLaneRuntime | null;
  graph: KnowledgeBuildLaneRuntime | null;
  activeLane: KnowledgeBuildLaneRuntime;
  focus: BuildProgressFocus;
  progress: number;
  statusText: string;
  isActive: boolean;
  isFailed: boolean;
  isCompleted: boolean;
}

type BuildProgressFocus = "aggregate" | "docgen" | "graph";

const ACTIVE_BUILD_STATUSES = new Set(["accepted", "running", "publishing"]);

function fallbackLane(
  lane: "aggregate" | "docgen" | "graph",
  overrides?: Partial<KnowledgeBuildLaneRuntime>,
): KnowledgeBuildLaneRuntime {
  return {
    lane,
    status: "idle",
    stage: "idle",
    progress_pct: 0,
    current_stage_description: null,
    metrics: {},
    ...overrides,
  };
}

function toneClasses(state: DerivedBuildState): string {
  if (state.isFailed) return "border-rose-200 bg-rose-50 dark:border-rose-500/30 dark:bg-rose-500/10";
  if (state.isCompleted) return "border-emerald-200 bg-emerald-50 dark:border-emerald-500/30 dark:bg-emerald-500/10";
  if (state.isActive) return "border-sky-200 bg-sky-50 dark:border-sky-500/30 dark:bg-sky-500/10";
  return "border-slate-200 bg-white dark:border-slate-800 dark:bg-slate-950/80";
}

function laneBadgeTone(status?: string | null): string {
  switch ((status ?? "").trim()) {
    case "completed":
      return "bg-emerald-100 text-emerald-700 dark:bg-emerald-500/10 dark:text-emerald-300";
    case "failed":
    case "cancelled":
    case "partial_failed":
      return "bg-rose-100 text-rose-700 dark:bg-rose-500/10 dark:text-rose-300";
    case "skipped":
      return "bg-amber-100 text-amber-700 dark:bg-amber-500/10 dark:text-amber-300";
    case "accepted":
    case "running":
    case "publishing":
      return "bg-sky-100 text-sky-700 dark:bg-sky-500/10 dark:text-sky-300";
    default:
      return "bg-slate-100 text-slate-600 dark:bg-slate-800 dark:text-slate-300";
  }
}

function stageLabel(stage?: string | null): string {
  return (stage ?? "").trim() || "idle";
}

function formatLatency(ms?: number): string | null {
  if (!ms || ms <= 0) return null;
  return ms < 1000 ? `${Math.round(ms)}ms` : `${(ms / 1000).toFixed(1)}s`;
}

function focusFallbackText(focus: BuildProgressFocus, status: string): string {
  if (focus === "graph") {
    if (status === "completed") return "知识图谱已完成";
    if (status === "skipped") return "当前图谱步骤已跳过";
    if (status === "idle") return "等待知识图谱构建任务";
    return "知识图谱构建进行中";
  }
  if (focus === "docgen") {
    if (status === "completed") return "知识文档已发布";
    if (status === "skipped") return "本轮文档构建已跳过";
    if (status === "idle") return "等待新的知识文档构建任务";
    return "知识文档构建进行中";
  }
  if (status === "partial_failed") return "知识文档已发布，但图谱构建失败";
  if (status === "completed") return "知识构建已完成";
  if (status === "skipped") return "当前图谱步骤已跳过";
  if (status === "idle") return "等待新的知识构建任务";
  return "知识构建进行中";
}

function deriveBuildState(
  data: KnowledgeBuildRuntimeResponse | undefined,
  focus: BuildProgressFocus = "aggregate",
): DerivedBuildState {
  const aggregate = data?.aggregate ?? fallbackLane("aggregate");
  const docgen = data?.docgen ?? null;
  const graph = data?.graph ?? null;
  const activeLane =
    focus === "docgen"
      ? docgen ?? fallbackLane("docgen")
      : focus === "graph"
        ? graph ?? fallbackLane("graph")
        : aggregate;
  const status = (activeLane.status ?? "").trim();
  const statusText =
    activeLane.current_stage_description?.trim() ||
    activeLane.error_message?.trim() ||
    focusFallbackText(focus, status);

  return {
    aggregate,
    docgen,
    graph,
    activeLane,
    focus,
    progress: Math.max(0, Math.min(100, Math.round(Number(activeLane.progress_pct ?? 0)))),
    statusText,
    isActive: ACTIVE_BUILD_STATUSES.has(status),
    isFailed: new Set(["failed", "cancelled", "partial_failed"]).has(status),
    isCompleted: status === "completed",
  };
}

export function useKnowledgeDocsBuildState(subject: string) {
  return useQuery({
    queryKey: buildKnowledgeBuildRuntimeQueryKey(subject),
    queryFn: () => fetchKnowledgeBuildRuntime(subject),
    enabled: Boolean(subject),
    refetchInterval: (query) => {
      const failureBackoff = buildRuntimeFailureBackoffMs(query.state.fetchFailureCount);
      if (failureBackoff !== null) return failureBackoff;
      const statuses = [
        query.state.data?.aggregate?.status,
        query.state.data?.docgen?.status,
        query.state.data?.graph?.status,
      ].map((status) => (status ?? "").trim());
      return statuses.some((status) => ACTIVE_BUILD_STATUSES.has(status)) ? 2500 : false;
    },
  });
}

function LaneBadge({
  label,
  lane,
}: {
  label: string;
  lane: KnowledgeBuildLaneRuntime | null;
}) {
  const status = (lane?.status ?? "idle").trim() || "idle";
  return (
    <span className={`rounded-full px-2.5 py-1 text-[11px] font-medium ${laneBadgeTone(status)}`}>
      {label}: {status}
    </span>
  );
}

export function DigestBuildProgress({
  subject,
  compact = false,
  className = "",
  focus = "aggregate",
}: {
  subject: string;
  compact?: boolean;
  className?: string;
  focus?: BuildProgressFocus;
}) {
  const { data, isFetching } = useKnowledgeDocsBuildState(subject);
  const state = useMemo(() => deriveBuildState(data, focus), [data, focus]);
  const preview = data?.docgen_preview ?? null;
  const metrics = data?.docgen_metrics ?? null;
  const [animatedProgress, setAnimatedProgress] = useState(state.progress);

  useEffect(() => {
    setAnimatedProgress((previous) => {
      if (state.isActive) return Math.max(previous, state.progress);
      return state.progress;
    });
  }, [state.isActive, state.progress]);

  const tone = toneClasses(state);
  const llmCallLabel =
    (metrics?.llm_total_calls ?? 0) > 0 ? `${metrics?.llm_total_calls ?? 0} LLM calls` : null;
  const latencyLabel = formatLatency(metrics?.llm_avg_latency_ms);
  const previewCards = preview?.sample_cards ?? [];
  const previewNodes = preview?.sample_nodes ?? [];
  const latestTitles = preview?.latest_chapter_titles ?? [];
  const draftExcerpt = preview?.draft_excerpt?.trim() ?? "";

  return (
    <section className={`rounded-2xl border px-4 py-4 shadow-sm ${tone} ${className}`.trim()}>
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="min-w-0 flex-1">
          <div className="flex items-center gap-2 text-slate-900 dark:text-slate-100">
            {state.isFailed ? (
              <AlertTriangle className="h-4 w-4 text-rose-600" />
            ) : state.isCompleted ? (
              <CheckCircle2 className="h-4 w-4 text-emerald-600" />
            ) : state.isActive ? (
              <Loader2 className="h-4 w-4 animate-spin text-sky-600" />
            ) : (
              <Sparkles className="h-4 w-4 text-slate-500" />
            )}
            <p className="text-sm font-semibold">{state.statusText}</p>
          </div>
          <p className="mt-1 text-xs leading-5 text-slate-600 dark:text-slate-400">
            {state.focus === "graph"
              ? "从已发布知识文档抽取知识点与关系，可自动同步，也可手动重建。"
              : state.focus === "docgen"
                ? "正在整理章节、证据和发布状态。"
                : "知识文档与知识图谱会按顺序推进。"}
          </p>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <LaneBadge label="aggregate" lane={state.aggregate} />
          <LaneBadge label="docgen" lane={state.docgen} />
          <LaneBadge label="graph" lane={state.graph} />
        </div>
      </div>

      <div className="mt-4">
        <div className="flex items-center justify-between text-xs text-slate-600 dark:text-slate-400">
          <div className="flex items-center gap-2">
            <span>{animatedProgress}%</span>
            <span>{stageLabel(state.activeLane.stage)}</span>
          </div>
          {state.activeLane.started_at ? (
            <span className="inline-flex items-center gap-1">
              <Clock3 className="h-3.5 w-3.5" />
              {new Date(state.activeLane.started_at).toLocaleString("zh-CN")}
            </span>
          ) : null}
        </div>
        <div className="mt-2 h-2 overflow-hidden rounded-full bg-white/90 dark:bg-slate-900/80">
          <div
            className="h-full rounded-full bg-[linear-gradient(90deg,#0f172a_0%,#0ea5e9_55%,#22c55e_100%)] transition-[width] duration-500"
            style={{ width: `${animatedProgress}%` }}
          />
        </div>
      </div>

      {llmCallLabel || latencyLabel ? (
        <div className="mt-3 flex flex-wrap gap-2 text-[11px] text-slate-600 dark:text-slate-400">
          {llmCallLabel ? <span className="rounded-full bg-white/80 px-2.5 py-1 dark:bg-slate-900/80">{llmCallLabel}</span> : null}
          {latencyLabel ? <span className="rounded-full bg-white/80 px-2.5 py-1 dark:bg-slate-900/80">avg {latencyLabel}</span> : null}
        </div>
      ) : null}

      {!compact && previewCards.length > 0 ? (
        <div className="mt-4 grid gap-3 md:grid-cols-2">
          {previewCards.slice(0, 4).map((card) => (
            <article key={`${card.card_type}-${card.title}`} className="rounded-xl border border-slate-200 bg-white/80 px-3 py-3 dark:border-slate-800 dark:bg-slate-900/70">
              <div className="flex items-center justify-between gap-2">
                <p className="text-sm font-medium text-slate-900 dark:text-slate-100">{card.title}</p>
                <span className="rounded-full bg-slate-100 px-2 py-0.5 text-[10px] uppercase tracking-wide text-slate-500 dark:bg-slate-800 dark:text-slate-400">
                  {card.card_type}
                </span>
              </div>
              <p className="mt-2 text-xs leading-5 text-slate-600 dark:text-slate-400">{card.summary}</p>
            </article>
          ))}
        </div>
      ) : null}

      {!compact && previewCards.length === 0 && previewNodes.length > 0 ? (
        <div className="mt-4 rounded-xl border border-slate-200 bg-white/80 px-3 py-3 dark:border-slate-800 dark:bg-slate-900/70">
          <p className="text-xs font-medium uppercase tracking-wide text-slate-500">Preview Nodes</p>
          <div className="mt-2 flex flex-wrap gap-2">
            {previewNodes.slice(0, 6).map((node) => (
              <span key={`${node.knowledge_unit_type}-${node.name}`} className="rounded-full border border-slate-200 bg-slate-50 px-2.5 py-1 text-[11px] text-slate-600 dark:border-slate-700 dark:bg-slate-800 dark:text-slate-300">
                {node.knowledge_unit_type}: {node.name}
              </span>
            ))}
          </div>
        </div>
      ) : null}

      {!compact && (latestTitles.length > 0 || draftExcerpt) ? (
        <div className="mt-4 rounded-xl border border-slate-200 bg-white/80 px-3 py-3 dark:border-slate-800 dark:bg-slate-900/70">
          {latestTitles.length > 0 ? (
            <>
              <p className="text-xs font-medium uppercase tracking-wide text-slate-500">Draft Outline</p>
              <div className="mt-2 flex flex-wrap gap-2">
                {latestTitles.slice(0, 4).map((title) => (
                  <span key={title} className="rounded-full bg-slate-100 px-2.5 py-1 text-[11px] text-slate-600 dark:bg-slate-800 dark:text-slate-300">
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

      {state.activeLane.error_message ? <p className="mt-3 text-xs text-rose-600 dark:text-rose-300">{state.activeLane.error_message}</p> : null}
      {isFetching ? <p className="mt-2 text-[11px] text-slate-500 dark:text-slate-500">Syncing latest build state...</p> : null}
    </section>
  );
}

export function KnowledgeGraphBuildProgress({
  subject,
  className = "",
}: {
  subject: string;
  className?: string;
}) {
  const { data, isFetching } = useKnowledgeDocsBuildState(subject);
  const state = useMemo(() => deriveBuildState(data, "graph"), [data]);
  const status = String(state.activeLane.status ?? "").trim();

  if (!status || status === "idle" || status === "skipped") {
    return null;
  }

  const metrics = state.activeLane.metrics ?? {};
  const graphMetrics = data?.graph_metrics ?? null;
  const processedChunks = Number(graphMetrics?.processed_chunks ?? metrics.processed_chunks ?? 0);
  const docSyncSections = Number(graphMetrics?.doc_sync_section_count ?? metrics.doc_sync_section_count ?? 0);
  const unitChanges = Number(graphMetrics?.doc_sync_unit_changes ?? metrics.doc_sync_unit_changes ?? 0);
  const edgeChanges = Number(graphMetrics?.doc_sync_edge_changes ?? metrics.doc_sync_edge_changes ?? 0);
  const revisionNo = Number(graphMetrics?.revision_no ?? metrics.revision_no ?? 0);
  const docVersionNo = Number(graphMetrics?.last_synced_doc_version_no ?? metrics.last_synced_doc_version_no ?? 0);
  const sourceRefCount = Number(graphMetrics?.source_ref_count ?? metrics.source_ref_count ?? 0);
  const backboneUnitCount = Number(graphMetrics?.backbone_unit_count ?? metrics.backbone_unit_count ?? 0);
  const backboneEdgeCount = Number(graphMetrics?.backbone_edge_count ?? metrics.backbone_edge_count ?? 0);
  const deprecatedUnitCount = Number(graphMetrics?.deprecated_unit_count ?? metrics.deprecated_unit_count ?? 0);
  const deprecatedEdgeCount = Number(graphMetrics?.deprecated_edge_count ?? metrics.deprecated_edge_count ?? 0);
  const tone = state.isFailed
    ? "border-rose-200 bg-rose-50 dark:border-rose-500/30 dark:bg-rose-500/10"
    : state.isCompleted
      ? "border-emerald-200 bg-emerald-50 dark:border-emerald-500/30 dark:bg-emerald-500/10"
      : "border-sky-200 bg-sky-50 dark:border-sky-500/30 dark:bg-sky-500/10";
  const icon = state.isFailed ? (
    <AlertTriangle className="h-4 w-4 text-rose-600" />
  ) : state.isCompleted ? (
    <CheckCircle2 className="h-4 w-4 text-emerald-600" />
  ) : state.isActive || isFetching ? (
    <Loader2 className="h-4 w-4 animate-spin text-sky-600" />
  ) : (
    <Network className="h-4 w-4 text-slate-500" />
  );

  return (
    <section className={`rounded-lg border px-4 py-3 shadow-sm ${tone} ${className}`.trim()}>
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="min-w-0 flex-1">
          <div className="flex items-center gap-2 text-slate-900 dark:text-slate-100">
            {icon}
            <p className="text-sm font-semibold">知识图谱构建</p>
          </div>
          <p className="mt-1 text-xs leading-5 text-slate-600 dark:text-slate-400">{state.statusText}</p>
        </div>
        <div className="flex items-center gap-2 text-xs text-slate-600 dark:text-slate-400">
          <span>{stageLabel(state.activeLane.stage)}</span>
          <span className="font-medium tabular-nums">{state.progress}%</span>
        </div>
      </div>
      <div className="mt-3 h-1.5 overflow-hidden rounded-full bg-white/90 dark:bg-slate-900/80">
        <div
          className="h-full rounded-full bg-[linear-gradient(90deg,#0f172a_0%,#0ea5e9_55%,#22c55e_100%)] transition-[width] duration-500"
          style={{ width: `${state.progress}%` }}
        />
      </div>
      {(processedChunks > 0 || docSyncSections > 0 || unitChanges > 0 || edgeChanges > 0 || sourceRefCount > 0 || revisionNo > 0 || state.activeLane.started_at) && (
        <div className="mt-2 flex flex-wrap gap-2 text-[11px] text-slate-500 dark:text-slate-400">
          {processedChunks > 0 ? <span>已处理 {processedChunks} 个片段</span> : null}
          {docSyncSections > 0 ? <span>已同步 {docSyncSections} 个章节段落</span> : null}
          {unitChanges > 0 ? <span>知识点更新 {unitChanges} 个</span> : null}
          {edgeChanges > 0 ? <span>关系更新 {edgeChanges} 条</span> : null}
          {sourceRefCount > 0 ? <span>来源记录 {sourceRefCount} 条</span> : null}
          {backboneUnitCount > 0 ? <span>骨架知识点 {backboneUnitCount} 个</span> : null}
          {backboneEdgeCount > 0 ? <span>骨架关系 {backboneEdgeCount} 条</span> : null}
          {deprecatedUnitCount > 0 ? <span>下线知识点 {deprecatedUnitCount} 个</span> : null}
          {deprecatedEdgeCount > 0 ? <span>下线关系 {deprecatedEdgeCount} 条</span> : null}
          {revisionNo > 0 ? <span>图谱版本 {revisionNo}</span> : null}
          {docVersionNo > 0 ? <span>文档版本 {docVersionNo}</span> : null}
          {state.activeLane.started_at ? (
            <span>开始于 {new Date(state.activeLane.started_at).toLocaleString("zh-CN")}</span>
          ) : null}
        </div>
      )}
    </section>
  );
}

export function DigestBuildStatusMeta({ subject }: { subject: string }) {
  const { data } = useKnowledgeDocsBuildState(subject);
  const state = useMemo(() => deriveBuildState(data), [data]);

  return (
    <div className="flex items-center gap-2 text-[11px] text-slate-500 dark:text-slate-400">
      <Clock3 className="h-3 w-3" />
      <span>{state.statusText}</span>
    </div>
  );
}
