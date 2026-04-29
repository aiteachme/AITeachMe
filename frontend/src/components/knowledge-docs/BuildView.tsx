import { memo, useEffect, useMemo, useRef, useState } from "react";
import { motion } from "framer-motion";
import { Check, CheckCircle2, ChevronRight, Code2, FileText, Loader2, PanelRightClose, PanelRightOpen, PlayCircle } from "lucide-react";

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
  isDocumentReady?: boolean;
  className?: string;
  /** Course ID for SSE streaming — enables live build updates */
  courseId?: string;
}

const EVENT_STAGE_LABELS: Record<string, string> = {
  build_accepted: "已受理",
  search_only_mode: "联网模式",
  planner_confirmed: "方案确认",
  preparing_docgen_context: "理解资料",
  dispatch_ready: "执行合同",
  building_document_backbone: "文档骨架",
  generating_chapters: "章节写作",
  chapter_generating: "章节启动",
  chapter_research_ready: "检索完成",
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
  "publishing",
  "completed",
]);

const ACTIVE_CHAPTER_STATUSES = new Set(["generating", "drafting", "enhancing", "reviewing", "researching"]);
const DONE_CHAPTER_STATUSES = new Set(["generated", "completed", "enhanced", "reviewed"]);
const LIVE_MARKDOWN_RENDER_LIMIT = 24000;
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
  return false;
}

const BUILD_MODE_LABELS: Record<string, string> = {
  confirmed_build_plan: "已确认构建方案",
  search_only_mode: "仅使用联网资料",
  local_material_mode: "基于本地资料",
};

function isCompletionStatusText(statusText: string): boolean {
  return /完成|已发布|已生成/.test(statusText);
}

function formatBuildModeReason(reason?: string | null): string | null {
  const normalized = (reason ?? "").trim();
  if (!normalized) return null;
  return BUILD_MODE_LABELS[normalized] ?? null;
}

function formatCompactCount(value: number): string {
  return Math.max(0, Math.round(value)).toLocaleString("zh-CN");
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

interface LiveMarkdownRenderState {
  markdown: string;
  sourceLength: number;
  displayedLength: number;
  truncated: boolean;
}

function prepareLiveMarkdownContent(content: string, isStreaming: boolean): LiveMarkdownRenderState {
  const source = String(content ?? "");
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
  isDocumentReady = false,
  className,
  courseId,
}: Props) {
  const [selectedPreviewChapter, setSelectedPreviewChapter] = useState<number | null>(null);
  const [detailsOpen, setDetailsOpen] = useState(shouldOpenDetailsByDefault);

  const isBuildActive = Boolean(
    buildStage && !(["completed", "failed", "cancelled"] as string[]).includes(buildStage)
  );
  const { snapshot: sseSnapshot, connected: sseConnected, previewStreams, buildEvents } = useBuildEventStream({
    courseId: courseId ?? "",
    enabled: Boolean(courseId) && isBuildActive,
  });

  const mergedChapters = useMemo(() => {
    const sseChapters = sseSnapshot?.docgen_preview?.chapter_progress;
    if (sseChapters && sseChapters.length > 0) return sseChapters;
    return buildPreview?.chapter_progress ?? [];
  }, [sseSnapshot?.docgen_preview?.chapter_progress, buildPreview?.chapter_progress]);

  const mergedEvents = useMemo(() => {
    const sseEvents = sseSnapshot?.docgen_preview?.recent_events;
    const baseEvents = sseEvents && sseEvents.length > 0 ? sseEvents : buildPreview?.recent_events ?? [];
    if (buildEvents.length === 0) return uniqueBuildEvents(baseEvents);
    return uniqueBuildEvents([...buildEvents, ...baseEvents]);
  }, [sseSnapshot?.docgen_preview?.recent_events, buildPreview?.recent_events, buildEvents]);

  const mergedChapterPreviews = useMemo(() => {
    const sseChapterPreviews = sseSnapshot?.docgen_preview?.chapter_previews;
    if (sseChapterPreviews && sseChapterPreviews.length > 0) return sseChapterPreviews;
    return buildPreview?.chapter_previews ?? [];
  }, [sseSnapshot?.docgen_preview?.chapter_previews, buildPreview?.chapter_previews]);

  const mergePreview = useMemo(() => {
    return sseSnapshot?.docgen_preview?.merge_preview ?? buildPreview?.merge_preview ?? null;
  }, [sseSnapshot?.docgen_preview?.merge_preview, buildPreview?.merge_preview]);

  const timelineSteps = useBuildTimelineSteps(buildStage);
  const chapters = mergedChapters;
  const events = mergedEvents;
  const chapterPreviews = mergedChapterPreviews;
  const rawProgress = Math.max(0, Math.min(100, Math.round(
    sseSnapshot?.docgen?.progress_pct ?? progress
  )));
  const isBuildCompleted =
    isDocumentReady && (buildStage === "completed" || (rawProgress >= 95 && isCompletionStatusText(statusText)));
  const roundedProgress = isBuildCompleted ? 100 : Math.min(rawProgress, 99);
  const progressIsActive = isBuildActive && !isBuildCompleted;
  const visibleProgress = progressIsActive ? Math.max(6, roundedProgress) : roundedProgress;

  const draftExcerpt = (
    mergePreview?.draft_excerpt ||
    sseSnapshot?.docgen_preview?.draft_excerpt ||
    buildPreview?.draft_excerpt ||
    ""
  ).trim();
  const planSummary = (sseSnapshot?.docgen_preview?.plan_summary ?? buildPreview?.plan_summary ?? "").trim();

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
              <span className="inline-flex h-8 w-8 items-center justify-center rounded-lg bg-zinc-950 text-white shadow-sm shadow-zinc-900/10 dark:bg-zinc-100 dark:text-slate-950 dark:shadow-none">
                {isFetching ? <Loader2 className="h-4 w-4 animate-spin" /> : <Code2 className="h-4 w-4" />}
              </span>
              <div className="min-w-0">
                <h2 className="truncate text-[16px] font-semibold leading-6 text-zinc-950 dark:text-zinc-50">
                  {statusText || "正在准备知识文档..."}
                </h2>
                <div className="mt-1.5 flex flex-wrap items-center gap-1.5 text-[11px] text-zinc-500 dark:text-slate-400">
                  <span className="rounded-md bg-zinc-50 px-2 py-0.5 ring-1 ring-zinc-200 dark:bg-slate-900 dark:ring-slate-800">
                    {chapters.length > 0 ? `${chapters.length} 个章节` : "等待章节计划"}
                  </span>
                  {buildModeLabel ? (
                    <span className="rounded-md bg-zinc-50 px-2 py-0.5 ring-1 ring-zinc-200 dark:bg-slate-900 dark:ring-slate-800">
                      {buildModeLabel}
                    </span>
                  ) : null}
                  {(sseConnected || isBuildActive) ? (
                    <span className="inline-flex items-center gap-1.5 rounded-md bg-blue-50 px-2 py-0.5 text-blue-600 ring-1 ring-blue-100 dark:bg-blue-500/10 dark:text-blue-300 dark:ring-blue-500/20">
                      <span className={cn("h-1.5 w-1.5 rounded-full", sseConnected ? "build-live-dot text-blue-500" : "bg-zinc-300 dark:bg-slate-600")} />
                      {sseConnected ? "实时更新" : "等待实时更新"}
                    </span>
                  ) : null}
                  <button
                    type="button"
                    onClick={() => setDetailsOpen((value) => !value)}
                    aria-expanded={detailsOpen}
                    className={cn(
                      "inline-flex items-center gap-1 rounded-md px-2 py-0.5 text-[11px] ring-1 transition",
                      detailsOpen
                        ? "bg-zinc-950 text-white ring-zinc-950 dark:bg-zinc-100 dark:text-slate-950 dark:ring-zinc-100"
                        : "bg-zinc-50 text-zinc-500 ring-zinc-200 hover:bg-white hover:text-zinc-900 dark:bg-slate-900 dark:text-slate-400 dark:ring-slate-800 dark:hover:text-slate-100"
                    )}
                  >
                    {detailsOpen ? <PanelRightClose className="h-3 w-3" /> : <PanelRightOpen className="h-3 w-3" />}
                    {detailsOpen ? "收起细节" : "查看细节"}
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
                      ? "bg-gradient-to-r from-emerald-400 via-emerald-500 to-teal-500"
                      : progressIsActive
                        ? "bg-blue-500 build-loading-progress-fill"
                        : "bg-blue-500"
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
              <span className="w-12 rounded-md bg-zinc-50 px-2 py-1 text-right text-[13px] font-semibold tabular-nums text-zinc-900 ring-1 ring-zinc-200 dark:bg-slate-900 dark:text-zinc-100 dark:ring-slate-800">
                {roundedProgress}%
              </span>
            </div>
          </div>
        </div>

        <div className="relative mt-4 overflow-x-auto pb-1 build-scroll">
          <div className="flex min-w-max items-center gap-3">
            {timelineSteps.map((step, idx) => {
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
                    {isDone ? <Check className="h-2.5 w-2.5" strokeWidth={3} /> : idx + 1}
                  </span>
                  <span className="whitespace-nowrap font-medium">{step.title}</span>
                  {isActive ? <span className="hidden text-[11px] text-blue-500/70 md:inline">{step.description}</span> : null}
                </div>
              );
            })}
          </div>
        </div>
      </div>

      <div className="flex-1 min-h-0 flex bg-white dark:bg-slate-950">
        <div className="flex-1 min-w-0 flex flex-col lg:flex-row">
          <div className="w-full shrink-0 border-b border-zinc-200 bg-zinc-50/60 dark:border-slate-800 dark:bg-slate-950 lg:w-[292px] lg:border-b-0 lg:border-r">
            <div className="flex items-center justify-between px-4 py-3.5">
              <div>
                <div className="text-[12px] font-semibold text-zinc-800 dark:text-slate-100">章节进度</div>
                <div className="mt-0.5 text-[11px] text-zinc-400 dark:text-slate-500">选择章节查看生成预览</div>
              </div>
              <ChevronRight className="hidden h-4 w-4 text-zinc-300 lg:block" />
            </div>
            <div className="max-h-52 overflow-y-auto px-2.5 pb-3 build-scroll lg:max-h-none lg:h-[calc(100%-64px)]">
              {chapters.map((chapter) => {
                const isSelected = selectedPreviewChapter === chapter.chapter_index;
                const isStreaming = spotlightChapter?.chapter_index === chapter.chapter_index;
                const isDone = DONE_CHAPTER_STATUSES.has(chapter.status);

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
                        {String(chapter.chapter_index).padStart(2, "0")}. {chapter.title}
                      </div>
                      <div className={cn("mt-1 text-[10.5px]", isSelected ? "text-blue-500 dark:text-blue-300" : "text-zinc-400 dark:text-slate-500")}>
                        {buildChapterStatusLabel(chapter.status)}
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

          <div className="relative flex h-full min-w-0 flex-1 flex-col bg-white dark:bg-slate-900">
            {selectedPreviewChapter ? (() => {
              const selChapter = chapters.find((chapter) => chapter.chapter_index === selectedPreviewChapter);
              const preview = selectedChapterPreview;
              const streamPreview = previewStreams[selectedPreviewChapter] ?? null;
              const selectedStatus =
                streamPreview?.status === "drafting"
                  ? streamPreview.status
                  : preview?.status ?? streamPreview?.status ?? selChapter?.status ?? "planned";
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
              const canUseMergeFallback = Boolean(buildStage && MERGE_PREVIEW_STAGES.has(buildStage));
              const selectedExcerpt = streamExcerpt.trim()
                ? streamExcerpt
                : previewExcerpt.trim()
                  ? previewExcerpt
                  : canUseMergeFallback
                    ? draftExcerpt
                    : "";
              const selectedHeadings = preview?.latest_headings ?? [];
              const selectedWordCount = preview?.word_count ?? selChapter?.word_count ?? 0;
              const previewUpdatedAt = streamPreview?.updatedAt
                ? formatBuildEventTime(streamPreview.updatedAt)
                : preview?.updated_at
                  ? formatBuildEventTime(preview.updated_at)
                  : null;
              const usingMergeFallback = !streamExcerpt.trim() && !previewExcerpt.trim() && canUseMergeFallback && Boolean(selectedExcerpt.trim());
              const usingSseDelta = Boolean(streamExcerpt.trim());
              const hasPreviewMeta =
                selectedWordCount > 0 ||
                usingMergeFallback ||
                usingSseDelta;

              return (
                <>
                  <div className="flex items-center justify-between gap-4 border-b border-zinc-100 bg-white px-5 py-3 dark:border-slate-800 dark:bg-slate-900 md:px-8">
                    <div className="min-w-0">
                      <div className="truncate text-[13px] font-semibold leading-5 text-zinc-900 dark:text-slate-100">
                        {String(selectedPreviewChapter).padStart(2, "0")}. {selectedTitle}
                      </div>
                      <div className="mt-1 flex flex-wrap items-center gap-2">
                        <span className="rounded-md bg-zinc-50 px-2 py-0.5 text-[11px] font-medium text-zinc-500 ring-1 ring-zinc-200 dark:bg-slate-950 dark:text-slate-400 dark:ring-slate-800">
                          {buildChapterStatusLabel(selectedStatus)}
                        </span>
                        {previewUpdatedAt ? (
                          <span className="text-[11px] text-zinc-400 dark:text-slate-500">
                            更新于 {previewUpdatedAt}
                          </span>
                        ) : null}
                      </div>
                    </div>
                    {(isStreaming || sseConnected) && (
                      <div className="shrink-0 flex items-center gap-2 rounded-md bg-blue-50 px-2.5 py-1 ring-1 ring-blue-100 dark:bg-blue-500/10 dark:ring-blue-500/20">
                        <span className="relative flex h-2 w-2">
                          <span className="build-live-dot h-2 w-2 text-blue-500 dark:text-blue-400" />
                        </span>
                        <span className="text-[11px] text-blue-500 dark:text-blue-400 font-medium">
                          {usingSseDelta ? "实时流" : "进行中"}
                        </span>
                      </div>
                    )}
                  </div>

                  <div className="build-scroll flex-1 overflow-y-auto bg-white px-5 py-6 dark:bg-slate-900 md:px-8 md:py-8">
                    {selectedExcerpt.trim() ? (
                      <div
                        className={cn(
                          "mx-auto grid w-full gap-8 pb-12",
                          detailsOpen
                            ? "max-w-[980px]"
                            : "max-w-[1280px] 2xl:grid-cols-[minmax(0,920px)_300px]",
                        )}
                      >
                        <div className="min-w-0 space-y-5">
                          {hasPreviewMeta ? (
                            <div className="flex flex-wrap items-center gap-x-3 gap-y-1 text-[12px] text-zinc-500 dark:text-slate-400">
                              {selectedWordCount > 0 ? (
                                <span>
                                  约 {selectedWordCount} 字
                                </span>
                              ) : null}
                              {usingMergeFallback ? (
                                <span className="text-blue-600 dark:text-blue-400">
                                  当前显示整本合并预览
                                </span>
                              ) : null}
                              {usingSseDelta ? (
                                <span className="text-blue-600 dark:text-blue-400">
                                  实时增量
                                </span>
                              ) : null}
                            </div>
                          ) : null}

                          {selectedHeadings.length > 0 ? (
                            <p className="max-w-[960px] text-[12px] leading-6 text-zinc-500 dark:text-slate-400">
                              <span className="text-zinc-400 dark:text-slate-500">生成聚焦：</span>
                              {selectedHeadings.join(" / ")}
                            </p>
                          ) : null}

                          <LiveTextDocument
                            key={selectedPreviewChapter}
                            content={selectedExcerpt}
                            isStreaming={isStreaming}
                          />

                          {detailsOpen && selectedChapterEvents.length > 0 ? (
                            <EventTrail events={selectedChapterEvents} selectedPreviewChapter={selectedPreviewChapter} />
                          ) : null}
                        </div>

                      </div>
                    ) : selectedChapterEvents.length > 0 ? (
                      <div className="mx-auto w-full max-w-[1120px] space-y-4 pb-10">
                        <div className="flex flex-wrap items-center gap-x-3 gap-y-1 text-[12px] text-zinc-500 dark:text-slate-400">
                          <span className="text-blue-600 dark:text-blue-400">
                            正在捕获章节执行事件
                          </span>
                        </div>
                        <EventTrail events={selectedChapterEvents} selectedPreviewChapter={selectedPreviewChapter} />
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
            })() : (
              <div className="h-full flex flex-col items-center justify-center text-zinc-300 gap-3">
                <PlayCircle className="w-10 h-10 text-zinc-200" strokeWidth={1.5} />
                <span className="text-[12px]">选择左侧章节查看流</span>
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
                <p className="text-[12px] font-semibold text-zinc-800 dark:text-slate-100">构建细节</p>
                <p className="mt-1 text-[11px] text-zinc-400 dark:text-slate-500">记录实时事件和方案摘要</p>
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
                <p className="text-[11px] font-medium tracking-[0.18em] text-zinc-400 dark:text-slate-500">方案摘要</p>
                <p className="mt-2 line-clamp-6 text-[12px] leading-6 text-zinc-600 dark:text-slate-300">
                  {planSummary}
                </p>
              </div>
            ) : null}
            <div className="flex-1 overflow-y-auto px-3 py-3 build-scroll">
              <p className="px-1 pb-2 text-[11px] font-medium tracking-[0.18em] text-zinc-400 dark:text-slate-500">
                最近事件
              </p>
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
                    等待构建事件...
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

function EventTrail({
  events,
  selectedPreviewChapter,
}: {
  events: Array<{ stage?: string | null; summary?: string | null }>;
  selectedPreviewChapter: number;
}) {
  return (
    <div className="space-y-2 border-t border-zinc-100 pt-5 dark:border-slate-800">
      <p className="text-[11px] font-medium uppercase tracking-[0.18em] text-zinc-400 dark:text-slate-500">
        改进轨迹
      </p>
      <div className="divide-y divide-zinc-100 border-y border-zinc-100 dark:divide-slate-800 dark:border-slate-800">
        {events.map((event, index) => (
          <div
            key={`${selectedPreviewChapter}-${event.stage}-${index}`}
            className="py-3 text-[12px] leading-6 text-zinc-600 dark:text-slate-300"
          >
            {event.summary}
          </div>
        ))}
      </div>
    </div>
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
  const statusText = renderState.pending
    ? "正在整理新片段"
    : isStreaming
      ? "Markdown 实时渲染"
      : "预览已稳定";

  return (
    <article>
      <div className="mb-5 flex flex-wrap items-center justify-between gap-3 border-b border-zinc-100 pb-3 dark:border-slate-800">
        <div className="flex min-w-0 items-center gap-2 text-zinc-500 dark:text-slate-400">
          <FileText className="h-4 w-4 shrink-0" />
          <div className="min-w-0">
            <p className="truncate text-[12px] font-medium text-zinc-700 dark:text-slate-200">章节草稿</p>
            <p className="mt-0.5 text-[11px] text-zinc-400 dark:text-slate-500">
              {formatCompactCount(renderState.sourceLength)} 字符已接收
            </p>
          </div>
        </div>
        <div
          className={cn(
            "inline-flex items-center gap-2 rounded-md px-2.5 py-1 text-[11px] font-medium ring-1",
            isStreaming
              ? "bg-blue-50 text-blue-600 ring-blue-100 dark:bg-blue-500/10 dark:text-blue-300 dark:ring-blue-500/20"
              : "bg-emerald-50 text-emerald-700 ring-emerald-100 dark:bg-emerald-500/10 dark:text-emerald-300 dark:ring-emerald-500/20",
          )}
          aria-live="polite"
        >
          <span
            className={cn(
              "h-1.5 w-1.5 rounded-full",
              isStreaming ? "build-live-dot text-blue-500" : "bg-emerald-500",
            )}
          />
          {statusText}
        </div>
      </div>

      <div className="feishu-doc-content build-live-markdown max-w-[920px] break-words [&>*:first-child]:!mt-0 [&>*:last-child]:!mb-0">
        <MarkdownViewer content={renderState.markdown} variant="document" />
      </div>

      {renderState.truncated ? (
        <div className="mt-5 border-l-2 border-amber-400 bg-amber-50/60 px-3 py-2 text-[12px] leading-5 text-amber-800 dark:bg-amber-500/10 dark:text-amber-200">
          实时预览先渲染前 {formatCompactCount(renderState.displayedLength)} 字符，完整正文仍会继续写入最终文档。
        </div>
      ) : null}

      {isStreaming ? (
        <div className="mt-5 flex items-center gap-2 text-[12px] text-blue-600 dark:text-blue-300">
          <motion.span className="inline-block h-[15px] w-[2px] animate-blink bg-blue-500 align-middle dark:bg-blue-400" />
          <span>{renderState.pending ? "新内容已到达，正在排版..." : "保持接收中..."}</span>
        </div>
      ) : null}
    </article>
  );
});
