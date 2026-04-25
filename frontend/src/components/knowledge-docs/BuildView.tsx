import { memo, useEffect, useMemo, useState } from "react";
import { motion } from "framer-motion";
import { Check, CheckCircle2, ChevronRight, Code2, Loader2, PanelRightClose, PanelRightOpen, PlayCircle } from "lucide-react";

import { cn } from "../../lib/utils";
import type { FileRecord } from "../../api/generated/model";
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
  className?: string;
  /** Subject ID for SSE streaming — enables live build updates */
  subjectId?: string;
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

const BUILD_MODE_LABELS: Record<string, string> = {
  confirmed_build_plan: "已确认构建方案",
  search_only_mode: "仅使用联网资料",
  local_material_mode: "基于本地资料",
};

const FAILED_BUILD_STAGES = new Set(["failed", "cancelled"]);

function isCompletionStatusText(statusText: string): boolean {
  return /完成|已发布|已生成/.test(statusText);
}

function formatBuildModeReason(reason?: string | null): string | null {
  const normalized = (reason ?? "").trim();
  if (!normalized) return null;
  return BUILD_MODE_LABELS[normalized] ?? null;
}

export function BuildView({
  isFetching,
  progress,
  statusText,
  buildPreview,
  buildStage,
  className,
  subjectId,
}: Props) {
  const [selectedPreviewChapter, setSelectedPreviewChapter] = useState<number | null>(null);
  const [detailsOpen, setDetailsOpen] = useState(false);

  const isBuildActive = Boolean(
    buildStage && !(["completed", "failed", "cancelled"] as string[]).includes(buildStage)
  );
  const { snapshot: sseSnapshot, connected: sseConnected, previewStreams, buildEvents } = useBuildEventStream({
    subjectId: subjectId ?? "",
    enabled: Boolean(subjectId) && isBuildActive,
  });

  const mergedChapters = useMemo(() => {
    const sseChapters = sseSnapshot?.docgen_preview?.chapter_progress;
    if (sseChapters && sseChapters.length > 0) return sseChapters;
    return buildPreview?.chapter_progress ?? [];
  }, [sseSnapshot?.docgen_preview?.chapter_progress, buildPreview?.chapter_progress]);

  const mergedEvents = useMemo(() => {
    const sseEvents = sseSnapshot?.docgen_preview?.recent_events;
    const baseEvents = sseEvents && sseEvents.length > 0 ? sseEvents : buildPreview?.recent_events ?? [];
    if (buildEvents.length === 0) return baseEvents;
    const seen = new Set<string>();
    return [...buildEvents, ...baseEvents].filter((event) => {
      const key = [
        event.created_at ?? "",
        event.stage ?? "",
        event.chapter_index ?? "",
        event.summary ?? "",
      ].join("|");
      if (seen.has(key)) return false;
      seen.add(key);
      return true;
    });
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
  const isBuildFailed = FAILED_BUILD_STAGES.has((buildStage ?? "").trim());
  const isBuildCompleted = buildStage === "completed" || (rawProgress >= 95 && isCompletionStatusText(statusText));
  const roundedProgress = isBuildCompleted ? 100 : rawProgress;
  const shouldAnimateProgress = roundedProgress < 100 && !isBuildFailed;

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
    return events.filter((event) => event.chapter_index === selectedPreviewChapter).slice(0, 5);
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
      <div className="relative overflow-hidden border-b border-zinc-100/80 bg-[radial-gradient(circle_at_12%_0%,rgba(99,102,241,0.10),transparent_30%),radial-gradient(circle_at_88%_8%,rgba(14,165,233,0.08),transparent_28%),linear-gradient(180deg,#ffffff_0%,#f8fbff_100%)] px-5 py-4 dark:border-slate-800 dark:bg-[radial-gradient(circle_at_12%_0%,rgba(99,102,241,0.16),transparent_30%),radial-gradient(circle_at_88%_8%,rgba(14,165,233,0.12),transparent_28%),linear-gradient(180deg,#0f172a_0%,#0b1120_100%)] lg:px-8">
        <div className="pointer-events-none absolute right-8 top-3 h-24 w-24 rounded-full bg-blue-100/40 blur-3xl dark:bg-blue-500/10" />
        <div className="relative flex flex-col gap-4">
          <div className="min-w-0 flex-1">
            <div className="flex flex-wrap items-center gap-2">
              <span className="inline-flex h-9 w-9 items-center justify-center rounded-xl bg-zinc-950 text-white shadow-sm shadow-zinc-900/20 dark:bg-zinc-100 dark:text-slate-950 dark:shadow-none">
                {isFetching ? <Loader2 className="h-4 w-4 animate-spin" /> : <Code2 className="h-4 w-4" />}
              </span>
              <div className="min-w-0">
                <h2 className="truncate text-[16px] font-semibold leading-6 text-zinc-950 dark:text-zinc-50">
                  {statusText || "正在准备知识文档..."}
                </h2>
                <div className="mt-1.5 flex flex-wrap items-center gap-1.5 text-[11px] text-zinc-500 dark:text-slate-400">
                  <span className="rounded-full bg-white/72 px-2 py-0.5 shadow-[inset_0_1px_2px_rgba(15,23,42,0.03)] ring-1 ring-zinc-200/70 backdrop-blur dark:bg-slate-900/70 dark:ring-slate-800">
                    {chapters.length > 0 ? `${chapters.length} 个章节` : "等待章节计划"}
                  </span>
                  {buildModeLabel ? (
                    <span className="rounded-full bg-white/72 px-2 py-0.5 shadow-[inset_0_1px_2px_rgba(15,23,42,0.03)] ring-1 ring-zinc-200/70 backdrop-blur dark:bg-slate-900/70 dark:ring-slate-800">
                      {buildModeLabel}
                    </span>
                  ) : null}
                  {(sseConnected || isBuildActive) ? (
                    <span className="inline-flex items-center gap-1.5 rounded-full bg-blue-50 px-2 py-0.5 text-blue-600 ring-1 ring-blue-100 dark:bg-blue-500/10 dark:text-blue-300 dark:ring-blue-500/20">
                      <span className={cn("h-1.5 w-1.5 rounded-full", sseConnected ? "animate-pulse bg-blue-500" : "bg-zinc-300 dark:bg-slate-600")} />
                      {sseConnected ? "实时更新" : "等待实时更新"}
                    </span>
                  ) : null}
                  <button
                    type="button"
                    onClick={() => setDetailsOpen((value) => !value)}
                    aria-expanded={detailsOpen}
                    className={cn(
                      "inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-[11px] ring-1 transition",
                      detailsOpen
                        ? "bg-zinc-950 text-white ring-zinc-950 dark:bg-zinc-100 dark:text-slate-950 dark:ring-zinc-100"
                        : "bg-white/72 text-zinc-500 ring-zinc-200/70 hover:bg-white hover:text-zinc-900 dark:bg-slate-900/70 dark:text-slate-400 dark:ring-slate-800 dark:hover:text-slate-100"
                    )}
                  >
                    {detailsOpen ? <PanelRightClose className="h-3 w-3" /> : <PanelRightOpen className="h-3 w-3" />}
                    {detailsOpen ? "收起细节" : "查看细节"}
                  </button>
                </div>
              </div>
            </div>
            <div className="mt-4 flex items-center gap-4">
              <div className="relative h-2.5 flex-1 overflow-hidden rounded-full bg-zinc-100 shadow-inner shadow-zinc-200/60 dark:bg-slate-800 dark:shadow-black/20">
                <motion.div
                  className={cn(
                    "relative h-full overflow-hidden rounded-full",
                    roundedProgress === 100
                      ? "bg-gradient-to-r from-emerald-400 via-emerald-500 to-teal-500"
                      : "bg-gradient-to-r from-blue-500 via-sky-400 to-blue-500"
                  )}
                  initial={{ width: 0 }}
                  animate={{
                    width: `${roundedProgress}%`,
                    boxShadow: shouldAnimateProgress
                      ? [
                        "0 0 0 rgba(59,130,246,0)",
                        "0 0 18px rgba(59,130,246,0.42)",
                        "0 0 0 rgba(59,130,246,0)",
                      ]
                      : "0 0 0 rgba(59,130,246,0)",
                  }}
                  transition={{
                    width: { duration: 0.45 },
                    boxShadow: { duration: 1.8, repeat: shouldAnimateProgress ? Infinity : 0, ease: "easeInOut" },
                  }}
                >
                  {shouldAnimateProgress ? (
                    <motion.span
                      className="absolute inset-y-0 w-24 -skew-x-12 bg-gradient-to-r from-transparent via-white/55 to-transparent"
                      initial={{ left: "-20%" }}
                      animate={{ left: "105%" }}
                      transition={{ duration: 1.9, repeat: Infinity, ease: "easeInOut" }}
                    />
                  ) : null}
                </motion.div>
              </div>
              <span className="w-12 rounded-full bg-white px-2 py-1 text-right text-[13px] font-semibold tabular-nums text-zinc-900 shadow-sm ring-1 ring-zinc-100 dark:bg-slate-900 dark:text-zinc-100 dark:ring-slate-800">
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
                    "group flex items-center gap-2 rounded-full px-2 py-1.5 text-[12px] transition-colors",
                    isActive
                      ? "bg-white/82 text-indigo-700 shadow-sm ring-1 ring-indigo-100 dark:bg-indigo-500/10 dark:text-indigo-300 dark:ring-indigo-500/20"
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
                        ? "border-indigo-500 bg-white text-indigo-600 dark:bg-slate-900"
                        : "border-zinc-200 text-zinc-400 dark:border-slate-700",
                  )}>
                    {isDone ? <Check className="h-2.5 w-2.5" strokeWidth={3} /> : idx + 1}
                  </span>
                  <span className="whitespace-nowrap font-medium">{step.title}</span>
                  {isActive ? <span className="hidden text-[11px] text-indigo-500/70 md:inline">{step.description}</span> : null}
                </div>
              );
            })}
          </div>
        </div>
      </div>

      <div className="flex-1 min-h-0 flex bg-[#fbfcff] dark:bg-slate-950">
        <div className="flex-1 min-w-0 flex flex-col lg:flex-row">
          <div className="w-full shrink-0 border-b border-zinc-200/60 bg-white/80 dark:border-slate-800 dark:bg-slate-950/60 lg:w-[292px] lg:border-b-0 lg:border-r">
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
                        ? "border-blue-500 bg-blue-50/60 text-zinc-950 dark:border-blue-400 dark:bg-blue-500/10 dark:text-zinc-100"
                        : "border-transparent text-zinc-600 hover:border-zinc-200 hover:bg-white dark:text-slate-400 dark:hover:border-slate-700 dark:hover:bg-slate-900/60"
                    )}
                  >
                    <div className="mt-1 relative flex items-center justify-center shrink-0 w-3 h-3">
                      {isStreaming ? (
                        <>
                          <span className={cn("animate-ping absolute inline-flex h-full w-full rounded-full opacity-75", isSelected ? "bg-blue-300" : "bg-blue-400")} />
                          <span className={cn("relative inline-flex rounded-full h-1.5 w-1.5", isSelected ? "bg-blue-300" : "bg-blue-500")} />
                        </>
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
              const isStreaming =
                spotlightChapter?.chapter_index === selectedPreviewChapter ||
                ["generating", "drafting", "enhancing", "reviewing"].includes(selectedStatus);
              const isDone = DONE_CHAPTER_STATUSES.has(selectedStatus);
              const streamExcerpt = streamPreview?.text.trim() ?? "";
              const previewExcerpt = preview?.excerpt?.trim() ?? "";
              const canUseMergeFallback = Boolean(buildStage && MERGE_PREVIEW_STAGES.has(buildStage));
              const selectedExcerpt = (
                streamExcerpt ||
                previewExcerpt ||
                (canUseMergeFallback ? draftExcerpt : "")
              ).trim();
              const selectedHeadings = preview?.latest_headings ?? [];
              const selectedWordCount = preview?.word_count ?? selChapter?.word_count ?? 0;
              const selectedSourceCount = preview?.source_count ?? selChapter?.source_count ?? 0;
              const previewUpdatedAt = streamPreview?.updatedAt
                ? formatBuildEventTime(streamPreview.updatedAt)
                : preview?.updated_at
                  ? formatBuildEventTime(preview.updated_at)
                  : null;
              const usingMergeFallback = !streamExcerpt && !previewExcerpt && canUseMergeFallback && Boolean(selectedExcerpt);
              const usingSseDelta = Boolean(streamExcerpt);

              return (
                <>
                  <div className="flex items-center justify-between border-b border-zinc-100/80 bg-white px-5 py-3 dark:border-slate-800 dark:bg-slate-900 md:px-8">
                    <div className="min-w-0">
                      <span className="text-[12px] font-medium text-zinc-500 dark:text-slate-400">
                        {buildChapterStatusLabel(selectedStatus)}
                      </span>
                      {previewUpdatedAt ? (
                        <span className="ml-2 text-[11px] text-zinc-300 dark:text-slate-600">
                          更新于 {previewUpdatedAt}
                        </span>
                      ) : null}
                    </div>
                    {(isStreaming || sseConnected) && (
                      <div className="flex items-center gap-2 rounded-full bg-blue-50 px-2.5 py-1 ring-1 ring-blue-100 dark:bg-blue-500/10 dark:ring-blue-500/20">
                        <span className="relative flex h-2 w-2">
                          <span className="animate-ping absolute inline-flex h-full w-full rounded-full bg-blue-400 dark:bg-blue-500 opacity-75" />
                          <span className="relative inline-flex rounded-full h-2 w-2 bg-blue-500 dark:bg-blue-400" />
                        </span>
                        <span className="text-[11px] text-blue-500 dark:text-blue-400 font-medium">
                          {usingSseDelta ? "实时流" : "进行中"}
                        </span>
                      </div>
                    )}
                  </div>

                  <div className="build-scroll flex-1 overflow-y-auto bg-white px-5 py-6 dark:bg-slate-900 md:px-8 md:py-8">
                    {selectedExcerpt ? (
                      <div className="w-full max-w-[1120px] space-y-5 pb-12">
                        <div className="flex flex-wrap items-center gap-x-3 gap-y-1 text-[12px] text-zinc-500 dark:text-slate-400">
                          <span className="font-medium text-zinc-600 dark:text-slate-300">
                            {buildChapterStatusLabel(selectedStatus)}
                          </span>
                          {selectedWordCount > 0 ? (
                            <span>
                              约 {selectedWordCount} 字
                            </span>
                          ) : null}
                          {selectedSourceCount > 0 ? (
                            <span>
                              {selectedSourceCount} 个来源
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

                        {selectedHeadings.length > 0 ? (
                          <p className="max-w-[960px] text-[12px] leading-6 text-zinc-500 dark:text-slate-400">
                            <span className="text-zinc-400 dark:text-slate-500">生成聚焦：</span>
                            {selectedHeadings.join(" / ")}
                          </p>
                        ) : null}

                        <LiveTextDocument
                          content={selectedExcerpt}
                          isStreaming={isStreaming}
                        />

                        {detailsOpen && selectedChapterEvents.length > 0 ? (
                          <EventTrail events={selectedChapterEvents} selectedPreviewChapter={selectedPreviewChapter} />
                        ) : null}
                      </div>
                    ) : selectedChapterEvents.length > 0 ? (
                      <div className="w-full max-w-[1120px] space-y-4 pb-10">
                        <div className="flex flex-wrap items-center gap-x-3 gap-y-1 text-[12px] text-zinc-500 dark:text-slate-400">
                          <span className="font-medium text-zinc-600 dark:text-slate-300">
                            {buildChapterStatusLabel(selectedStatus)}
                          </span>
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
  return (
    <article className="pt-2">
      <div className="whitespace-pre-wrap break-words text-[15px] leading-8 text-zinc-800 dark:text-slate-100">
        {content}
        {isStreaming && (
          <motion.span className="ml-0.5 inline-block h-[16px] w-[2px] animate-blink bg-blue-500 align-middle dark:bg-blue-400" />
        )}
      </div>
    </article>
  );
});
