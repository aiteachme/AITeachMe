import { memo, useEffect, useMemo, useRef, useState } from "react";
import { motion } from "framer-motion";
import { Check, CheckCircle2, ChevronRight, Code2, Loader2, PanelRightClose, PanelRightOpen, PlayCircle } from "lucide-react";

import { cn } from "../../lib/utils";
import type { FileRecord } from "../../api/generated/model";
import { MarkdownViewer } from "../ui/MarkdownViewer";
import type {
  KnowledgeBuildMetrics,
  KnowledgeBuildPreview,
} from "./types";
import { useBuildTimelineSteps } from "./BuildProcessTimeline";
import { buildChapterStatusLabel, formatBuildEventTime } from "./utils";
import { useBuildEventStream } from "../../hooks/useBuildEventStream";

interface Props {
  isFetching: boolean;
  progress: number;
  statusText: string;
  buildPreview: KnowledgeBuildPreview | null;
  buildMetrics: KnowledgeBuildMetrics | null;
  sourceFiles: FileRecord[];
  sourceFilesFetching: boolean;
  buildStage: string | null | undefined;
  buildStatus?: string | null;
  isDocumentReady?: boolean;
  className?: string;
  /** Course ID for SSE streaming — enables live build updates */
  courseId?: string;
}

const EVENT_STAGE_LABELS: Record<string, string> = {
  build_accepted: "已受理",
  search_only_mode: "联网模式",
  planner_confirmed: "方案确认",
  preparing_docgen_global_seed: "准备全局上下文",
  docgen_global_seed_started: "准备全局上下文",
  docgen_global_seed_ready: "全局上下文就绪",
  chapter_title_locked: "章节标题锁定",
  chapter_titles_locked: "章节标题就绪",
  preparing_docgen_context: "理解资料",
  dispatch_ready: "执行合同",
  building_document_backbone: "文档骨架",
  document_backbone_progress: "骨架生成中",
  document_backbone_section: "骨架内容",
  chapter_execution_brief_ready: "章节 brief",
  document_backbone_repairing: "结构校验",
  document_backbone_ready: "骨架就绪",
  chapter_tasks_ready: "章节任务就绪",
  generating_chapters: "章节写作",
  chapter_generating: "章节启动",
  chapter_research_ready: "检索完成",
  chapter_unit_test_generating: "生成章末测试",
  chapter_unit_test_ready: "章末测试就绪",
  chapter_generated: "初稿完成",
  enhancing_chapters: "章节增强",
  chapter_enhanced: "增强完成",
  chapters_enhanced: "增强完成",
  reviewing_content: "复核中",
  chapter_reviewed: "章节复核",
  content_reviewed: "复核完成",
  repairing_or_routing: "回流处理",
  repair_routed: "回流记录",
  merge_reviewed: "整本检查",
  titles_finalized: "标题收口",
  publishing: "发布中",
  completed: "已发布",
};

const MERGE_PREVIEW_STAGES = new Set([
  "merge_reviewed",
  "titles_finalized",
  "doc_lane_staged",
  "docgen_finalized",
  "graph_pending",
  "graph_docs_sync",
  "publishing",
  "completed",
]);

const TERMINAL_BUILD_STATUSES = new Set(["completed", "failed", "cancelled", "partial_failed", "skipped"]);
const TERMINAL_BUILD_STAGES = new Set(["completed", "failed", "cancelled", "partial_failed", "skipped"]);
const GRAPH_BUILD_STAGES = new Set([
  "graph_pending",
  "manual_graph_requested",
  "queued_after_docgen",
  "graph_docs_sync",
  "graph_ready",
]);
const BACKBONE_WORKSPACE_STAGES = new Set([
  "planner_confirmed",
  "plan_ready",
  "preparing_docgen_global_seed",
  "docgen_global_seed_started",
  "docgen_global_seed_ready",
  "chapter_title_locked",
  "chapter_titles_locked",
  "dispatch_ready",
  "backbone_seed_ready",
  "building_document_backbone",
  "preparing_chapter_execution_briefs",
  "document_backbone_ready",
  "chapter_tasks_ready",
]);
const ACTIVE_CHAPTER_STATUSES = new Set(["generating", "drafting", "enhancing", "reviewing", "researching"]);
const DONE_CHAPTER_STATUSES = new Set(["generated", "completed", "enhanced", "reviewed"]);
const LIVE_MARKDOWN_RENDER_LIMIT = 24000;

function DocumentBackboneWorkspace({
  chapterCount,
  sseConnected,
  stage,
  statusText,
  events,
}: {
  chapterCount: number;
  sseConnected: boolean;
  stage: string;
  statusText: string;
  events: BuildEventItem[];
}) {
  const scrollRef = useRef<HTMLDivElement | null>(null);
  const isPinnedToLatestRef = useRef(true);
  const latestEvent = events[0];
  const stageLabel = EVENT_STAGE_LABELS[stage] ?? "文档骨架";
  const visibleEvents = events.slice(0, 60).reverse();
  const latestEventKey = latestEvent ? buildEventIdentity(latestEvent) : "";

  useEffect(() => {
    if (!isPinnedToLatestRef.current) return;
    const frame = window.requestAnimationFrame(() => {
      const container = scrollRef.current;
      if (container) {
        container.scrollTop = container.scrollHeight;
      }
    });
    return () => window.cancelAnimationFrame(frame);
  }, [latestEventKey, visibleEvents.length]);

  const handleTimelineScroll = () => {
    const container = scrollRef.current;
    if (!container) return;
    const distanceToBottom = container.scrollHeight - container.scrollTop - container.clientHeight;
    isPinnedToLatestRef.current = distanceToBottom <= 56;
  };

  return (
    <div
      ref={scrollRef}
      onScroll={handleTimelineScroll}
      className="build-scroll h-full min-h-0 overflow-y-auto overscroll-contain bg-white dark:bg-slate-900"
      aria-label="文档构建实时历史"
    >
      <div className="mx-auto w-full max-w-[900px] px-6 py-7 md:px-10 md:py-9">
        <div className="flex min-w-0 flex-wrap items-center gap-x-2 gap-y-1 text-[11px] text-zinc-400 dark:text-slate-500">
          <span className={cn("h-1.5 w-1.5 shrink-0 rounded-full", sseConnected ? "build-live-dot bg-blue-500 text-blue-500" : "bg-zinc-300 dark:bg-slate-600")} />
          <span className="font-medium text-zinc-600 dark:text-slate-300">
            {sseConnected ? "SSE 实时生成" : "正在恢复实时连接"}
          </span>
          <span aria-hidden="true">·</span>
          <span>{stageLabel}</span>
          {latestEvent?.created_at ? (
            <span className="ml-auto tabular-nums">{formatBuildEventTime(latestEvent.created_at)}</span>
          ) : null}
        </div>

        <div className="mt-4 max-w-[760px]" aria-live="polite">
          <p className="text-[14px] font-medium leading-7 text-zinc-800 dark:text-slate-200 md:text-[15px]">
            {latestEvent?.summary?.trim() || statusText || "正在准备文档结构与章节上下文"}
            {sseConnected ? <span className="build-stream-caret ml-1 inline-block h-[1em] w-[2px] translate-y-[0.14em] bg-blue-500" aria-hidden="true" /> : null}
          </p>
          <p className="mt-1.5 text-[11.5px] leading-5 text-zinc-400 dark:text-slate-500">
            {chapterCount > 0
              ? `骨架就绪后，${chapterCount} 个章节将并行写作，正文会直接出现在这里。`
              : "骨架就绪后，各章节将并行写作，正文会直接出现在这里。"}
          </p>
        </div>

        {visibleEvents.length > 0 ? (
          <ol className="mt-7 max-w-[760px] border-l border-zinc-200 pl-5 pb-6 dark:border-slate-700">
            {visibleEvents.map((event, index) => {
              const isCurrent = index === visibleEvents.length - 1;
              const eventLabel = EVENT_STAGE_LABELS[String(event.stage ?? "")] ?? "构建进展";
              return (
                <li
                  key={buildEventIdentity(event)}
                  className={cn(
                    "relative pb-5 last:pb-0",
                    isCurrent ? "text-zinc-900 dark:text-slate-100" : "text-zinc-500 dark:text-slate-400",
                  )}
                >
                  <span
                    className={cn(
                      "absolute -left-[23px] top-[7px] h-1.5 w-1.5 rounded-full ring-4 ring-white dark:ring-slate-900",
                      isCurrent ? "build-live-dot bg-blue-500 text-blue-500" : "bg-zinc-300 dark:bg-slate-600",
                    )}
                    aria-hidden="true"
                  />
                  <div className="flex min-w-0 items-baseline gap-2">
                    <span className={cn("shrink-0 text-[11px] font-medium", isCurrent ? "text-blue-600 dark:text-blue-300" : "text-zinc-500 dark:text-slate-400")}>
                      {eventLabel}
                    </span>
                    {event.created_at ? (
                      <time className="ml-auto shrink-0 text-[10.5px] tabular-nums text-zinc-400 dark:text-slate-500">
                        {formatBuildEventTime(event.created_at)}
                      </time>
                    ) : null}
                  </div>
                  <p className="mt-1 text-[12.5px] leading-6 text-zinc-600 dark:text-slate-300">
                    {event.summary?.trim() || statusText || "正在继续构建"}
                    {isCurrent && sseConnected ? <span className="build-stream-caret ml-1 inline-block h-[0.9em] w-px translate-y-[0.12em] bg-blue-500" aria-hidden="true" /> : null}
                  </p>
                </li>
              );
            })}
          </ol>
        ) : null}
      </div>
    </div>
  );
}
const LIVE_MARKDOWN_FLUSH_INTERVAL_MS = 320;
const LIVE_MARKDOWN_IMMEDIATE_LENGTH = 1600;
const LIVE_MARKDOWN_LARGE_JUMP = 4200;

type BuildEventItem = {
  stage?: string | null;
  summary?: string | null;
  created_at?: string | null;
  chapter_index?: number | null;
  title?: string | null;
};

function shouldOpenDetailsByDefault(): boolean {
  return typeof window !== "undefined" && window.matchMedia("(min-width: 1024px)").matches;
}

const BUILD_MODE_LABELS: Record<string, string> = {
  confirmed_build_plan: "已确认构建方案",
  search_only_mode: "仅使用联网资料",
  local_material_mode: "基于本地资料",
};

function isCompletionStatusText(statusText: string): boolean {
  return /完成|已发布|已生成/.test(statusText);
}

function polishBuildPlanSummary(text: string): string {
  return String(text || "")
    .replace(/^\s*(?:你好[！!。]?\s*)?我是你的\s*AITeachMe\s*学习规划师[。！!，,]?\s*/u, "")
    .trim();
}

function formatBuildModeReason(reason?: string | null): string | null {
  const normalized = (reason ?? "").trim();
  if (!normalized) return null;
  return BUILD_MODE_LABELS[normalized] ?? null;
}

const PREVIEW_DEBUG_SECTION_HEADINGS = [
  "检索结果",
  "执行过的查询",
  "仍需补强的点",
];

function stripLivePreviewDebugSections(value: string): string {
  const lines = String(value ?? "").split(/\r?\n/);
  const kept: string[] = [];
  let skipping = false;
  for (const line of lines) {
    const trimmed = line.trim();
    if (PREVIEW_DEBUG_SECTION_HEADINGS.includes(trimmed)) {
      skipping = true;
      continue;
    }
    if (skipping && /^#{1,6}\s+\S/.test(trimmed)) {
      skipping = false;
    }
    if (skipping) continue;
    if (/^检索与证据整理已完成/.test(trimmed)) continue;
    if (/^(本地命中|联网命中|已执行查询|已打开网页|已纳入文档)[：:]/.test(trimmed)) continue;
    kept.push(line);
  }
  return kept.join("\n").trim();
}

function buildEventIdentity(event: BuildEventItem): string {
  return [
    event.stage ?? "",
    event.chapter_index ?? "",
    event.title ?? "",
    event.summary ?? "",
  ].join("|").trim();
}

function uniqueBuildEvents<T extends BuildEventItem>(items: T[]): T[] {
  const seen = new Set<string>();
  return items.filter((event) => {
    const key = buildEventIdentity(event);
    if (!key || seen.has(key)) return false;
    seen.add(key);
    return true;
  });
}

function mergeChapterIndexedItems<T extends { chapter_index?: number | null }>(
  baseItems: T[],
  liveItems: T[] | undefined | null,
): T[] {
  if (!liveItems || liveItems.length === 0) return baseItems;
  const byIndex = new Map<number, T>();
  for (const item of baseItems) {
    const index = Number(item.chapter_index ?? 0);
    if (index > 0) byIndex.set(index, item);
  }
  for (const item of liveItems) {
    const index = Number(item.chapter_index ?? 0);
    if (index > 0) byIndex.set(index, item);
  }
  return Array.from(byIndex.values()).sort((a, b) => Number(a.chapter_index ?? 0) - Number(b.chapter_index ?? 0));
}

interface LiveMarkdownRenderState {
  markdown: string;
  sourceLength: number;
  displayedLength: number;
  truncated: boolean;
}

function prepareLiveMarkdownContent(content: string, isStreaming: boolean): LiveMarkdownRenderState {
  const source = stripLivePreviewDebugSections(content);
  const limit = isStreaming ? LIVE_MARKDOWN_RENDER_LIMIT : LIVE_MARKDOWN_RENDER_LIMIT * 2;
  const shouldTruncate = source.length > limit;
  const markdown = shouldTruncate ? source.slice(0, limit).trimEnd() : source;

  return {
    markdown,
    sourceLength: source.length,
    displayedLength: markdown.length,
    truncated: shouldTruncate,
  };
}

function useLiveMarkdownRenderState(content: string, isStreaming: boolean): LiveMarkdownRenderState & { pending: boolean } {
  const [renderState, setRenderState] = useState<LiveMarkdownRenderState>(() => prepareLiveMarkdownContent(content, isStreaming));
  const renderStateRef = useRef(renderState);
  const latestPreparedRef = useRef(renderState);
  const latestSourceRef = useRef(content);
  const committedSourceRef = useRef(content);
  const flushTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  useEffect(() => {
    const clearTimer = () => {
      if (flushTimerRef.current) {
        clearTimeout(flushTimerRef.current);
        flushTimerRef.current = null;
      }
    };

    const commit = (next: LiveMarkdownRenderState, source: string) => {
      renderStateRef.current = next;
      committedSourceRef.current = source;
      setRenderState(next);
    };

    const prepared = prepareLiveMarkdownContent(content, isStreaming);
    latestPreparedRef.current = prepared;
    latestSourceRef.current = content;

    if (
      committedSourceRef.current === content &&
      renderStateRef.current.markdown === prepared.markdown &&
      renderStateRef.current.truncated === prepared.truncated
    ) {
      return;
    }

    const shouldCommitImmediately =
      !isStreaming ||
      renderStateRef.current.sourceLength === 0 ||
      prepared.sourceLength <= LIVE_MARKDOWN_IMMEDIATE_LENGTH ||
      Math.abs(prepared.displayedLength - renderStateRef.current.displayedLength) >= LIVE_MARKDOWN_LARGE_JUMP;

    if (shouldCommitImmediately) {
      clearTimer();
      commit(prepared, content);
      return;
    }

    if (!flushTimerRef.current) {
      flushTimerRef.current = setTimeout(() => {
        flushTimerRef.current = null;
        commit(latestPreparedRef.current, latestSourceRef.current);
      }, LIVE_MARKDOWN_FLUSH_INTERVAL_MS);
    }
  }, [content, isStreaming]);

  useEffect(() => {
    return () => {
      if (flushTimerRef.current) {
        clearTimeout(flushTimerRef.current);
      }
    };
  }, []);

  return {
    ...renderState,
    pending: committedSourceRef.current !== content,
  };
}

export function BuildView({
  isFetching,
  progress,
  statusText,
  buildPreview,
  buildStage,
  buildStatus,
  isDocumentReady = false,
  className,
  courseId,
}: Props) {
  const [selectedPreviewChapter, setSelectedPreviewChapter] = useState<number | null>(null);
  const [detailsOpen, setDetailsOpen] = useState(shouldOpenDetailsByDefault);

  const normalizedBuildStatus = (buildStatus ?? "").trim();
  const normalizedBuildStage = (buildStage ?? "").trim();
  const isBuildActive = Boolean(
    normalizedBuildStatus
      ? normalizedBuildStatus !== "idle" && !TERMINAL_BUILD_STATUSES.has(normalizedBuildStatus)
      : normalizedBuildStage && !TERMINAL_BUILD_STAGES.has(normalizedBuildStage)
  );
  const { snapshot: sseSnapshot, connected: sseConnected, previewStreams, buildEvents } = useBuildEventStream({
    courseId: courseId ?? "",
    enabled: Boolean(courseId) && isBuildActive,
  });
  const liveBuildStage = (
    sseSnapshot?.docgen?.stage ??
    sseSnapshot?.aggregate?.stage ??
    normalizedBuildStage
  ).trim();
  const liveIsGraphBuildStage = GRAPH_BUILD_STAGES.has(liveBuildStage);
  const liveStatusText = (
    sseSnapshot?.docgen?.current_stage_description ??
    sseSnapshot?.aggregate?.current_stage_description ??
    statusText
  ).trim();

  const mergedChapters = useMemo(() => {
    const sseChapters = sseSnapshot?.docgen_preview?.chapter_progress;
    return mergeChapterIndexedItems(buildPreview?.chapter_progress ?? [], sseChapters);
  }, [sseSnapshot?.docgen_preview?.chapter_progress, buildPreview?.chapter_progress]);

  const mergedEvents = useMemo(() => {
    const sseEvents = sseSnapshot?.docgen_preview?.recent_events;
    const baseEvents = sseEvents && sseEvents.length > 0 ? sseEvents : buildPreview?.recent_events ?? [];
    if (buildEvents.length === 0) return uniqueBuildEvents(baseEvents);
    return uniqueBuildEvents([...buildEvents, ...baseEvents]);
  }, [sseSnapshot?.docgen_preview?.recent_events, buildPreview?.recent_events, buildEvents]);

  const mergedChapterPreviews = useMemo(() => {
    const sseChapterPreviews = sseSnapshot?.docgen_preview?.chapter_previews;
    return mergeChapterIndexedItems(buildPreview?.chapter_previews ?? [], sseChapterPreviews);
  }, [sseSnapshot?.docgen_preview?.chapter_previews, buildPreview?.chapter_previews]);

  const mergePreview = useMemo(() => {
    return sseSnapshot?.docgen_preview?.merge_preview ?? buildPreview?.merge_preview ?? null;
  }, [sseSnapshot?.docgen_preview?.merge_preview, buildPreview?.merge_preview]);

  const timelineSteps = useBuildTimelineSteps(liveBuildStage);
  const chapters = mergedChapters;
  const events = mergedEvents;
  const chapterPreviews = mergedChapterPreviews;
  const streamProgress = sseSnapshot?.aggregate?.progress_pct ?? (
    liveIsGraphBuildStage ? sseSnapshot?.graph?.progress_pct : sseSnapshot?.docgen?.progress_pct
  );
  const rawProgress = Math.max(0, Math.min(100, Math.round(streamProgress ?? progress)));
  const isBuildCompleted =
    isDocumentReady && (liveBuildStage === "completed" || (rawProgress >= 95 && isCompletionStatusText(liveStatusText)));
  const roundedProgress = isBuildCompleted ? 100 : Math.min(rawProgress, 99);
  const progressIsActive = isBuildActive && !isBuildCompleted;
  const visibleProgress = progressIsActive ? Math.max(6, roundedProgress) : roundedProgress;

  const draftExcerpt = (
    mergePreview?.draft_excerpt ||
    sseSnapshot?.docgen_preview?.draft_excerpt ||
    buildPreview?.draft_excerpt ||
    ""
  ).trim();
  const planSummary = polishBuildPlanSummary(sseSnapshot?.docgen_preview?.plan ?? buildPreview?.plan ?? "");

  const spotlightChapter = chapters.find((chapter) => ACTIVE_CHAPTER_STATUSES.has(chapter.status))
    ?? chapters.find((chapter) => chapter.status !== "pending")
    ?? null;

  const chapterPreviewByIndex = useMemo(
    () => new Map(chapterPreviews.map((item) => [item.chapter_index, item])),
    [chapterPreviews],
  );

  const selectedChapterPreview = selectedPreviewChapter !== null
    ? chapterPreviewByIndex.get(selectedPreviewChapter) ?? null
    : null;

  const selectedChapterEvents = useMemo(() => {
    if (selectedPreviewChapter === null) return [];
    return uniqueBuildEvents(events.filter((event) => event.chapter_index === selectedPreviewChapter)).slice(0, 5);
  }, [events, selectedPreviewChapter]);

  const recentEvents = events.slice(0, 8);
  const buildModeLabel = formatBuildModeReason(buildPreview?.mode_reason);
  const isBackboneWorkspace = BACKBONE_WORKSPACE_STAGES.has(liveBuildStage);

  useEffect(() => {
    if (chapters.length === 0) {
      setSelectedPreviewChapter(null);
      return;
    }
    if (
      selectedPreviewChapter === null ||
      !chapters.some((chapter) => chapter.chapter_index === selectedPreviewChapter)
    ) {
      setSelectedPreviewChapter(spotlightChapter?.chapter_index ?? chapters[0].chapter_index);
    }
  }, [chapters, selectedPreviewChapter, spotlightChapter]);

  return (
    <motion.div
      initial={{ opacity: 0 }}
      animate={{ opacity: 1 }}
      transition={{ duration: 0.35 }}
      className={cn(
        "w-full h-full flex flex-col bg-white dark:bg-slate-900 overflow-hidden",
        className
      )}
    >
      <div className="relative border-b border-zinc-200 bg-white px-5 py-4 dark:border-slate-800 dark:bg-slate-950 lg:px-8">
        <div className="relative flex flex-col gap-4">
          <div className="min-w-0 flex-1">
            <div className="flex flex-wrap items-center gap-2">
              <span className="inline-flex h-8 w-8 items-center justify-center rounded-lg bg-blue-50 text-blue-600 ring-1 ring-blue-100 dark:bg-blue-500/10 dark:text-blue-300 dark:ring-blue-500/20">
                {isFetching ? <Loader2 className="h-4 w-4 animate-spin" /> : <Code2 className="h-4 w-4" />}
              </span>
              <div className="min-w-0">
                <h2 className="truncate text-[16px] font-semibold leading-6 text-zinc-950 dark:text-zinc-50">
                  {liveStatusText || "正在准备知识文档..."}
                </h2>
                <div className="mt-1.5 flex flex-wrap items-center gap-1.5 text-[11px] text-zinc-500 dark:text-slate-400">
                  {(sseConnected || isBuildActive) ? (
                    <span className="inline-flex items-center gap-1.5 rounded-md bg-blue-50 px-2 py-0.5 text-blue-600 ring-1 ring-blue-100 dark:bg-blue-500/10 dark:text-blue-300 dark:ring-blue-500/20">
                      <span className={cn("h-1.5 w-1.5 rounded-full", sseConnected ? "build-live-dot text-blue-500" : "bg-zinc-300 dark:bg-slate-600")} />
                      {sseConnected ? "实时" : "等待"}
                    </span>
                  ) : null}
                  <button
                    type="button"
                    onClick={() => setDetailsOpen((value) => !value)}
                    aria-expanded={detailsOpen}
                    className={cn(
                      "inline-flex items-center gap-1 rounded-md px-2 py-0.5 text-[11px] ring-1 transition",
                      detailsOpen
                        ? "bg-blue-50 text-blue-600 ring-blue-100 dark:bg-blue-500/10 dark:text-blue-300 dark:ring-blue-500/20"
                        : "bg-zinc-50 text-zinc-500 ring-zinc-200 hover:bg-white hover:text-zinc-900 dark:bg-slate-900 dark:text-slate-400 dark:ring-slate-800 dark:hover:text-slate-100"
                    )}
                  >
                    {detailsOpen ? <PanelRightClose className="h-3 w-3" /> : <PanelRightOpen className="h-3 w-3" />}
                    {detailsOpen ? "收起" : "动态"}
                  </button>
                </div>
              </div>
            </div>
            <div className="mt-4 flex items-center gap-4">
              <div
                className={cn(
                  "relative h-2 flex-1 overflow-hidden rounded-full bg-zinc-100 dark:bg-slate-800",
                  progressIsActive ? "build-loading-progress-track" : "",
                )}
              >
                <motion.div
                  className={cn(
                    "relative h-full overflow-hidden rounded-full",
                    roundedProgress === 100
                      ? "bg-gradient-to-r from-blue-500 via-blue-600 to-blue-500"
                      : progressIsActive
                        ? "bg-blue-600 build-loading-progress-fill"
                        : "bg-blue-600"
                  )}
                  initial={{ width: 0 }}
                  animate={{
                    width: `${visibleProgress}%`,
                  }}
                  transition={{
                    width: { duration: 0.35 },
                  }}
                />
              </div>
            </div>
          </div>
        </div>

        {detailsOpen ? (
        <div className="relative mt-4 overflow-x-auto pb-1 build-scroll">
          <div className="flex min-w-max items-center gap-3">
            {timelineSteps.map((step) => {
              const isDone = step.state === "done";
              const isActive = step.state === "active";
              return (
                <div
                  key={step.key}
                  className={cn(
                    "group flex items-center gap-2 rounded-md px-2 py-1.5 text-[12px] transition-colors",
                    isActive
                      ? "bg-blue-50 text-blue-700 ring-1 ring-blue-100 dark:bg-blue-500/10 dark:text-blue-300 dark:ring-blue-500/20"
                      : isDone
                        ? "text-emerald-700 dark:text-emerald-300"
                        : "text-zinc-400 dark:text-slate-500",
                  )}
                >
                  <span className={cn(
                    "flex h-4 w-4 items-center justify-center rounded-full border text-[9px]",
                    isDone
                      ? "border-emerald-500 bg-emerald-500 text-white"
                      : isActive
                        ? "border-blue-500 bg-white text-blue-600 dark:bg-slate-900"
                        : "border-zinc-200 text-zinc-400 dark:border-slate-700",
                  )}>
                    {isDone ? (
                      <Check className="h-2.5 w-2.5" strokeWidth={3} />
                    ) : (
                      <span className={cn(
                        "h-1.5 w-1.5 rounded-full",
                        isActive ? "bg-blue-500" : "bg-zinc-300 dark:bg-slate-600",
                      )} />
                    )}
                  </span>
                  <span className="whitespace-nowrap font-medium">{step.title}</span>
                  {isActive ? <span className="hidden text-[11px] text-blue-500/70 md:inline">{step.description}</span> : null}
                </div>
              );
            })}
          </div>
        </div>
        ) : null}
      </div>

      <div className="flex-1 min-h-0 flex bg-white dark:bg-slate-950">
        <div className="flex-1 min-w-0 flex flex-col lg:flex-row">
          {detailsOpen ? (
          <div className="w-full shrink-0 border-b border-zinc-200 bg-zinc-50/60 dark:border-slate-800 dark:bg-slate-950 lg:w-[292px] lg:border-b-0 lg:border-r">
            <div className="flex items-center justify-between px-4 py-3.5">
              <div>
                <div className="text-[12px] font-semibold text-zinc-800 dark:text-slate-100">章节进度</div>
                <div className="mt-0.5 text-[11px] text-zinc-400 dark:text-slate-500">
                  {chapters.length > 0 ? `${chapters.length} 章` : "等待章节"}
                  {buildModeLabel ? ` · ${buildModeLabel}` : ""}
                </div>
              </div>
              <ChevronRight className="hidden h-4 w-4 text-zinc-300 lg:block" />
            </div>
            <div className="max-h-52 overflow-y-auto px-2.5 pb-3 build-scroll lg:max-h-none lg:h-[calc(100%-64px)]">
              {chapters.map((chapter) => {
                const isSelected = selectedPreviewChapter === chapter.chapter_index;
                const streamStatus = previewStreams[chapter.chapter_index]?.status;
                const effectiveChapterStatus = streamStatus ?? chapter.status;
                const isStreaming = ACTIVE_CHAPTER_STATUSES.has(effectiveChapterStatus);
                const isDone = DONE_CHAPTER_STATUSES.has(effectiveChapterStatus);

                return (
                  <button
                    key={chapter.chapter_index}
                    onClick={() => setSelectedPreviewChapter(chapter.chapter_index)}
                    aria-pressed={isSelected}
                    className={cn(
                      "w-full border-l-2 text-left px-3 py-3 text-[12px] transition-colors flex items-start gap-2.5",
                      isSelected
                        ? "border-blue-500 bg-white text-zinc-950 shadow-[inset_0_0_0_1px_rgba(228,228,231,0.9)] dark:border-blue-400 dark:bg-slate-900 dark:text-zinc-100 dark:shadow-none"
                        : "border-transparent text-zinc-600 hover:border-zinc-200 hover:bg-white dark:text-slate-400 dark:hover:border-slate-700 dark:hover:bg-slate-900/60"
                    )}
                  >
                    <div className="mt-1 relative flex items-center justify-center shrink-0 w-3 h-3">
                      {isStreaming ? (
                        <span className={cn("build-live-dot h-1.5 w-1.5", isSelected ? "text-blue-300" : "text-blue-500")} />
                      ) : isDone ? (
                        <div className={cn("w-1.5 h-1.5 rounded-full", isSelected ? "bg-emerald-300" : "bg-emerald-400")} />
                      ) : (
                        <div className={cn("w-1.5 h-1.5 rounded-full", isSelected ? "bg-zinc-400" : "bg-zinc-300")} />
                      )}
                    </div>
                    <div className="flex-1 pr-1">
                      <div className="line-clamp-2 font-medium leading-snug">
                        {chapter.title}
                      </div>
                      <div className={cn("mt-1 text-[10.5px]", isSelected ? "text-blue-500 dark:text-blue-300" : "text-zinc-400 dark:text-slate-500")}>
                        {buildChapterStatusLabel(effectiveChapterStatus)}
                      </div>
                    </div>
                  </button>
                );
              })}
              {chapters.length === 0 && (
                <div className="text-[12px] text-zinc-300 text-center py-10">大纲未就绪</div>
              )}
            </div>
          </div>
          ) : null}

          <div className="relative flex h-full min-w-0 flex-1 flex-col bg-white dark:bg-slate-900">
            {selectedPreviewChapter ? (() => {
              const selChapter = chapters.find((chapter) => chapter.chapter_index === selectedPreviewChapter);
              const preview = selectedChapterPreview;
              const streamPreview = previewStreams[selectedPreviewChapter] ?? null;
              const selectedStatus = streamPreview?.status ?? preview?.status ?? selChapter?.status ?? "planned";
              const selectedTitle =
                preview?.title ??
                streamPreview?.title ??
                selChapter?.title ??
                `第 ${selectedPreviewChapter} 章`;
              const isStreaming =
                spotlightChapter?.chapter_index === selectedPreviewChapter ||
                ["generating", "drafting", "enhancing", "reviewing"].includes(selectedStatus);
              const isDone = DONE_CHAPTER_STATUSES.has(selectedStatus);
              const streamExcerpt = streamPreview?.text ?? "";
              const previewExcerpt = preview?.excerpt ?? "";
              const canUseMergeFallback = Boolean(liveBuildStage && MERGE_PREVIEW_STAGES.has(liveBuildStage));
              const selectedExcerpt = streamExcerpt.trim()
                ? streamExcerpt
                : previewExcerpt.trim()
                  ? previewExcerpt
                  : canUseMergeFallback
                    ? draftExcerpt
                    : "";
              const previewUpdatedAt = streamPreview?.updatedAt
                ? formatBuildEventTime(streamPreview.updatedAt)
                : preview?.updated_at
                  ? formatBuildEventTime(preview.updated_at)
                  : null;
              const usingSseDelta = Boolean(streamExcerpt.trim());
              const workspaceTitle = isBackboneWorkspace ? "整本文档知识骨架" : selectedTitle;
              const workspaceStatus = isBackboneWorkspace ? "跨章节准备" : buildChapterStatusLabel(selectedStatus);

              return (
                <>
                  <div className="flex items-center justify-between gap-4 border-b border-zinc-100 bg-white px-5 py-3 dark:border-slate-800 dark:bg-slate-900 md:px-8">
                    <div className="min-w-0">
                      <div className="truncate text-[13px] font-semibold leading-5 text-zinc-900 dark:text-slate-100">
                        {workspaceTitle}
                      </div>
                      {detailsOpen ? (
                      <div className="mt-1 flex flex-wrap items-center gap-2">
                        <span className="rounded-md bg-zinc-50 px-2 py-0.5 text-[11px] font-medium text-zinc-500 ring-1 ring-zinc-200 dark:bg-slate-950 dark:text-slate-400 dark:ring-slate-800">
                          {workspaceStatus}
                        </span>
                        {previewUpdatedAt ? (
                          <span className="text-[11px] text-zinc-400 dark:text-slate-500">
                            更新于 {previewUpdatedAt}
                          </span>
                        ) : null}
                      </div>
                      ) : null}
                    </div>
                    {(isStreaming || sseConnected) && (
                      <div className="shrink-0 flex items-center gap-2 rounded-md bg-blue-50 px-2.5 py-1 ring-1 ring-blue-100 dark:bg-blue-500/10 dark:ring-blue-500/20">
                        <span className="relative flex h-2 w-2">
                          <span className="build-live-dot h-2 w-2 text-blue-500 dark:text-blue-400" />
                        </span>
                        <span className="text-[11px] text-blue-600 dark:text-blue-300 font-medium">
                          {usingSseDelta ? "实时流" : "进行中"}
                        </span>
                      </div>
                    )}
                  </div>

                  <div className={cn(
                    "build-scroll min-h-0 flex-1 bg-white dark:bg-slate-900",
                    isBackboneWorkspace
                      ? "overflow-hidden"
                      : "overflow-y-auto px-5 py-6 md:px-8 md:py-8",
                  )}>
                    {selectedExcerpt.trim() ? (
                      <div
                        className={cn(
                          "mx-auto grid w-full gap-8 pb-12",
                          detailsOpen
                            ? "max-w-[980px]"
                            : "max-w-[940px]",
                        )}
                      >
                      <div className="min-w-0 space-y-5">
                          <LiveTextDocument
                            key={selectedPreviewChapter}
                            content={selectedExcerpt}
                            isStreaming={isStreaming}
                          />
                        </div>

                      </div>
                    ) : isBackboneWorkspace ? (
                      <DocumentBackboneWorkspace chapterCount={chapters.length} sseConnected={sseConnected} stage={liveBuildStage} statusText={liveStatusText} events={events} />
                    ) : detailsOpen && selectedChapterEvents.length > 0 ? (
                      <div className="mx-auto w-full max-w-[1120px] space-y-4 pb-10">
                        <div className="flex h-40 items-center justify-center text-[13px] text-zinc-400 dark:text-slate-500">
                          等待章节预览
                        </div>
                      </div>
                    ) : isDone ? (
                      <div className="h-full flex flex-col items-center justify-center text-zinc-400 dark:text-slate-500 space-y-3">
                        <CheckCircle2 className="w-10 h-10 text-emerald-200 dark:text-emerald-500/30" strokeWidth={1.5} />
                        <p className="text-[13px] text-zinc-400 dark:text-slate-500">此章已完成，但章节预览尚未刷新到工作台。</p>
                      </div>
                    ) : (
                      <div className="h-full flex flex-col items-center justify-center text-zinc-400 dark:text-slate-500 space-y-3">
                        <Loader2 className="w-10 h-10 text-zinc-200 dark:text-slate-700 animate-spin" strokeWidth={1.5} />
                        <p className="text-[13px] text-zinc-400 dark:text-slate-500">排列中，等待系统推进到此章...</p>
                      </div>
                    )}
                  </div>
                </>
              );
            })() : isBackboneWorkspace ? (
              <DocumentBackboneWorkspace chapterCount={chapters.length} sseConnected={sseConnected} stage={liveBuildStage} statusText={liveStatusText} events={events} />
            ) : (
              <div className="h-full flex flex-col items-center justify-center text-zinc-300 gap-3">
                <PlayCircle className="w-10 h-10 text-zinc-200" strokeWidth={1.5} />
                <span className="text-[12px]">等待章节预览</span>
              </div>
            )}
          </div>
        </div>

        {detailsOpen ? (
          <>
          <button
            type="button"
            className="fixed inset-0 z-[89] bg-slate-950/20 lg:hidden"
            aria-label="收起构建细节"
            onClick={() => setDetailsOpen(false)}
          />
          <aside className="fixed bottom-0 right-0 top-0 z-[90] flex w-[min(330px,calc(100vw-1rem))] shrink-0 flex-col border-l border-zinc-100 bg-white shadow-2xl dark:border-slate-800 dark:bg-slate-950 lg:static lg:z-auto lg:w-[330px] lg:shadow-none">
            <div className="flex items-center justify-between border-b border-zinc-100 px-4 py-4 dark:border-slate-800">
              <div>
                <p className="text-[12px] font-semibold text-zinc-800 dark:text-slate-100">构建动态</p>
                <p className="mt-0.5 flex items-center gap-1.5 text-[10.5px] text-zinc-400 dark:text-slate-500">
                  <span className={cn("h-1.5 w-1.5 rounded-full", sseConnected ? "build-live-dot bg-blue-500 text-blue-500" : "bg-zinc-300 dark:bg-slate-600")} />
                  {sseConnected ? "实时同步" : "等待连接"}
                </p>
              </div>
              <button
                type="button"
                onClick={() => setDetailsOpen(false)}
                className="inline-flex h-8 w-8 items-center justify-center rounded-lg text-zinc-400 transition hover:bg-white hover:text-zinc-700 dark:hover:bg-slate-800 dark:hover:text-slate-200"
                aria-label="收起构建细节"
              >
                <PanelRightClose className="h-4 w-4" />
              </button>
            </div>
            {planSummary ? (
              <div className="border-b border-zinc-100 px-4 py-4 dark:border-slate-800">
                <p className="text-[11px] font-medium text-zinc-400 dark:text-slate-500">方案摘要</p>
                <p className="mt-2 line-clamp-6 text-[12px] leading-6 text-zinc-600 dark:text-slate-300">
                  {planSummary}
                </p>
              </div>
            ) : null}
            <div className="flex-1 overflow-y-auto px-3 py-3 build-scroll">
              <div className="divide-y divide-zinc-100 dark:divide-slate-800">
                {recentEvents.map((event, index) => {
                  const stage = (event.stage ?? "").trim();
                  const stageLabel = EVENT_STAGE_LABELS[stage] ?? (stage || "事件");
                  return (
                    <div
                      key={`${event.stage}-${event.created_at}-${index}`}
                      className="px-1 py-3 text-[11.5px] leading-5 text-zinc-600 dark:text-slate-300"
                    >
                      <div className="mb-1 flex items-center justify-between gap-2">
                        <span className="truncate font-medium text-blue-500 dark:text-blue-400">{stageLabel}</span>
                        <span className="shrink-0 text-[10px] text-zinc-300 dark:text-slate-600">
                          {event.created_at ? formatBuildEventTime(event.created_at) : ""}
                        </span>
                      </div>
                      <p className="line-clamp-3">{event.summary}</p>
                    </div>
                  );
                })}
                {recentEvents.length === 0 ? (
                  <div className="py-8 text-center text-[12px] text-zinc-300 dark:text-slate-600">
                    等待事件
                  </div>
                ) : null}
              </div>
            </div>
          </aside>
          </>
        ) : null}
      </div>
    </motion.div>
  );
}

const LiveTextDocument = memo(function LiveTextDocument({
  content,
  isStreaming,
}: {
  content: string;
  isStreaming: boolean;
}) {
  const renderState = useLiveMarkdownRenderState(content, isStreaming);

  return (
    <article>
      <div className="feishu-doc-content build-live-markdown max-w-[860px] break-words [&>*:first-child]:!mt-0 [&>*:last-child]:!mb-0">
        <MarkdownViewer content={renderState.markdown} variant="document" />
      </div>

      {renderState.truncated ? (
        <div className="mt-5 border-l-2 border-amber-400 bg-amber-50/60 px-3 py-2 text-[12px] leading-5 text-amber-800 dark:bg-amber-500/10 dark:text-amber-200">
          实时预览已节选，完整正文仍会继续写入最终文档。
        </div>
      ) : null}

      {isStreaming ? (
        <span className="sr-only" aria-live="polite">
          {renderState.pending ? "正在更新预览" : "正在生成章节"}
        </span>
      ) : null}
    </article>
  );
});
