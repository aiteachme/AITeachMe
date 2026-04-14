import { useEffect, useState } from "react";
import { motion, AnimatePresence } from "framer-motion";
import { ChevronDown, ChevronUp, Loader2, Sparkles } from "lucide-react";

import { cn } from "../../lib/utils";
import type { FileRecord } from "../../api/generated/model";
import type { KnowledgeBuildMetrics, KnowledgeBuildPreview } from "./types";
import { BuildChapterProgress } from "./BuildChapterProgress";
import { BuildMaterialPipeline } from "./BuildMaterialPipeline";
import { BuildProcessTimeline, useBuildTimelineSteps } from "./BuildProcessTimeline";
import { BuildResearchSources } from "./BuildResearchSources";

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
}

function InlineMetrics({
  metrics,
  preview,
}: {
  metrics: KnowledgeBuildMetrics | null;
  preview: KnowledgeBuildPreview | null;
}) {
  const parts: string[] = [];
  const chunks = preview?.total_chunks;
  if (chunks && chunks > 0) parts.push(`${preview?.processed_chunks ?? 0}/${chunks} 分片`);
  const nodes = preview?.discovered_node_count;
  if (nodes && nodes > 0) parts.push(`${nodes} 节点`);
  const calls = metrics?.llm_total_calls;
  if (calls && calls > 0) parts.push(`${calls} 调用`);
  const latency = metrics?.llm_avg_latency_ms;
  if (latency && latency > 0) {
    parts.push(latency < 1000 ? `${Math.round(latency)}ms` : `${(latency / 1000).toFixed(1)}s`);
  }
  if (parts.length === 0) {
    return null;
  }

  return (
    <div className="flex flex-wrap gap-x-2 gap-y-0.5 text-[10px] text-stone-400">
      {parts.map((part) => (
        <span key={part} className="inline-flex items-center gap-0.5">
          <span className="inline-block h-1 w-1 rounded-full bg-stone-300" />
          {part}
        </span>
      ))}
    </div>
  );
}

function DocumentCanvas({
  draftExcerpt,
  chapterTitles,
  planSummary,
  chapters,
}: {
  draftExcerpt: string;
  chapterTitles: string[];
  planSummary: string;
  chapters: KnowledgeBuildPreview["chapter_progress"];
}) {
  const hasContent = draftExcerpt || chapterTitles.length > 0 || planSummary;

  if (!hasContent) {
    return (
      <motion.div
        initial={{ opacity: 0 }}
        animate={{ opacity: 1 }}
        className="flex flex-col items-center justify-center py-20 text-center"
      >
        <div className="relative">
          <div className="flex h-12 w-12 items-center justify-center rounded-2xl bg-stone-100">
            <Loader2 className="h-5 w-5 animate-spin text-stone-400" />
          </div>
          <motion.div
            className="absolute -inset-2 rounded-2xl border border-sky-300/30"
            animate={{ scale: [1, 1.15, 1], opacity: [0.6, 0, 0.6] }}
            transition={{ duration: 2.5, repeat: Infinity, ease: "easeInOut" }}
          />
        </div>
        <p className="mt-5 text-[13px] text-stone-500">正在准备知识文档...</p>
        <p className="mt-1 text-[11px] text-stone-400">AI 正在分析资料，预计 3-10 分钟</p>
      </motion.div>
    );
  }

  return (
    <motion.div
      initial={{ opacity: 0, y: 12 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.5, ease: "easeOut" }}
      className="relative"
    >
      <div className="overflow-hidden rounded-xl border border-stone-200/70 bg-white shadow-[0_1px_3px_rgba(0,0,0,0.04),0_8px_24px_-8px_rgba(0,0,0,0.06)]">
        <div className="h-[2px] overflow-hidden bg-stone-100">
          <motion.div
            className="h-full bg-gradient-to-r from-sky-400 via-blue-400 to-sky-400"
            animate={{ x: ["-100%", "100%"] }}
            transition={{ duration: 2, repeat: Infinity, ease: "linear" }}
            style={{ width: "50%" }}
          />
        </div>

        <div className="px-7 py-6 md:px-10 md:py-8">
          {chapterTitles.length > 0 ? (
            <motion.h1
              initial={{ opacity: 0 }}
              animate={{ opacity: 1 }}
              transition={{ delay: 0.2 }}
              className="text-xl font-semibold leading-tight tracking-tight text-stone-800"
              style={{ fontFamily: "var(--font-serif)" }}
            >
              {chapterTitles[0]}
            </motion.h1>
          ) : null}

          {planSummary ? (
            <motion.p
              initial={{ opacity: 0 }}
              animate={{ opacity: 1 }}
              transition={{ delay: 0.35 }}
              className="mt-3 text-[13.5px] leading-[1.9] text-stone-600"
              style={{ fontFamily: "var(--font-serif)" }}
            >
              {planSummary}
            </motion.p>
          ) : null}

          {chapterTitles.length > 1 ? (
            <div className="mt-5 space-y-1.5">
              {chapterTitles.slice(1).map((title, index) => {
                const chapter = (chapters ?? [])[index + 1];
                const isActive = chapter?.status === "drafting" || chapter?.status === "researching";
                const isDone = chapter?.status === "completed" || chapter?.status === "drafted";

                return (
                  <motion.div
                    key={title}
                    initial={{ opacity: 0, x: -6 }}
                    animate={{ opacity: 1, x: 0 }}
                    transition={{ delay: 0.3 + index * 0.08 }}
                    className="flex items-center gap-2.5 py-1"
                  >
                    <span
                      className={cn(
                        "h-1.5 w-1.5 shrink-0 rounded-full transition-colors",
                        isDone ? "bg-emerald-400" : isActive ? "animate-pulse bg-sky-400" : "bg-stone-300",
                      )}
                    />
                    <span
                      className={cn(
                        "text-[13px] font-medium",
                        isActive ? "text-sky-700" : isDone ? "text-stone-700" : "text-stone-400",
                      )}
                      style={{ fontFamily: "var(--font-serif)" }}
                    >
                      {title}
                    </span>
                    {isActive ? (
                      <span className="rounded bg-sky-50 px-1.5 py-0.5 text-[10px] text-sky-500">撰写中</span>
                    ) : null}
                  </motion.div>
                );
              })}
            </div>
          ) : null}

          {draftExcerpt ? (
            <motion.div
              initial={{ opacity: 0 }}
              animate={{ opacity: 1 }}
              transition={{ delay: 0.4 }}
              className="mt-6 border-t border-stone-100 pt-5"
            >
              <pre
                className="max-h-[320px] overflow-y-auto whitespace-pre-wrap text-[13.5px] leading-[2] text-stone-600"
                style={{ fontFamily: "var(--font-serif)" }}
              >
                {draftExcerpt}
                <motion.span className="ml-0.5 inline-block h-[15px] w-[2px] animate-blink rounded-sm bg-sky-500 align-middle" />
              </pre>
            </motion.div>
          ) : null}

          {draftExcerpt ? (
            <div className="relative z-10 -mt-12 h-12 bg-gradient-to-t from-white to-transparent pointer-events-none" />
          ) : null}
        </div>
      </div>
    </motion.div>
  );
}

export function BuildView({
  isFetching,
  progress,
  statusText,
  buildPreview,
  buildMetrics,
  sourceFiles,
  sourceFilesFetching,
  buildStage,
  className,
}: Props) {
  const timelineSteps = useBuildTimelineSteps(buildStage);
  const chapters = buildPreview?.chapter_progress ?? [];
  const events = buildPreview?.recent_events ?? [];
  const chapterTitles = buildPreview?.latest_chapter_titles ?? [];
  const draftExcerpt = buildPreview?.draft_excerpt?.trim() ?? "";
  const planSummary = buildPreview?.plan_summary?.trim() ?? "";
  const [isDesktop, setIsDesktop] = useState(
    () => typeof window === "undefined" || window.innerWidth >= 1024,
  );
  const [showDetails, setShowDetails] = useState(
    () => typeof window === "undefined" || window.innerWidth >= 1024,
  );

  useEffect(() => {
    if (typeof window === "undefined") {
      return undefined;
    }

    const handleResize = () => {
      const nextIsDesktop = window.innerWidth >= 1024;
      setIsDesktop(nextIsDesktop);
      if (nextIsDesktop) {
        setShowDetails(true);
      }
    };

    handleResize();
    window.addEventListener("resize", handleResize);
    return () => window.removeEventListener("resize", handleResize);
  }, []);

  const showDetailPanels = isDesktop || showDetails;

  return (
    <motion.div
      initial={{ opacity: 0 }}
      animate={{ opacity: 1 }}
      transition={{ duration: 0.4 }}
      className={cn("mx-auto w-full max-w-[1100px] py-6", className)}
    >
      <motion.div
        initial={{ opacity: 0, y: -8 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ delay: 0.08, duration: 0.35 }}
        className="mb-5 flex items-center gap-3"
      >
        <div className="relative shrink-0">
          <div className="flex h-9 w-9 items-center justify-center rounded-xl bg-gradient-to-br from-sky-500 to-blue-600 shadow-md shadow-sky-500/15">
            <Sparkles className="h-4 w-4 text-white" />
          </div>
          <motion.div
            className="absolute -inset-1 rounded-xl border border-sky-400/25"
            animate={{ scale: [1, 1.2, 1], opacity: [0.5, 0, 0.5] }}
            transition={{ duration: 2, repeat: Infinity }}
          />
        </div>

        <div className="min-w-0 flex-1">
          <div className="flex items-center gap-2">
            <p className="truncate text-sm font-medium text-stone-800">{statusText}</p>
            {isFetching ? <Loader2 className="h-3 w-3 shrink-0 animate-spin text-stone-300" /> : null}
            <span className="ml-auto shrink-0 text-[11px] font-semibold text-sky-600">{Math.round(progress)}%</span>
          </div>
          <div className="mt-1.5 h-[3px] overflow-hidden rounded-full bg-stone-100">
            <motion.div
              initial={{ width: 0 }}
              animate={{ width: `${progress}%` }}
              transition={{ duration: 0.8, ease: "easeOut" }}
              className="h-full rounded-full bg-gradient-to-r from-sky-500 to-blue-500"
            />
          </div>
          <div className="mt-1.5">
            <InlineMetrics metrics={buildMetrics} preview={buildPreview} />
          </div>
        </div>
      </motion.div>

      <div className="grid grid-cols-1 gap-5 lg:grid-cols-[220px_1fr]">
        <motion.div
          initial={{ opacity: 0, x: -12 }}
          animate={{ opacity: 1, x: 0 }}
          transition={{ delay: 0.12, duration: 0.35 }}
          className="lg:sticky lg:top-6 lg:self-start"
        >
          <BuildProcessTimeline steps={timelineSteps} />
          <BuildMaterialPipeline files={sourceFiles} isFetching={sourceFilesFetching} className="mt-4" />
        </motion.div>

        <motion.div
          initial={{ opacity: 0, y: 12 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ delay: 0.18, duration: 0.4 }}
          className="space-y-4"
        >
          <DocumentCanvas
            draftExcerpt={draftExcerpt}
            chapterTitles={chapterTitles}
            planSummary={planSummary}
            chapters={chapters}
          />

          {(chapters.length > 0 || events.length > 0) ? (
            <div>
              {isDesktop ? (
                <div className="text-[11px] font-medium text-stone-400">
                  研究详情 路 {chapters.length} 章{events.length > 0 ? ` 路 ${events.length} 条来源` : ""}
                </div>
              ) : (
                <button
                  type="button"
                  onClick={() => setShowDetails((prev) => !prev)}
                  className="inline-flex items-center gap-1.5 text-[11px] font-medium text-stone-400 transition-colors hover:text-stone-600"
                >
                  {showDetailPanels ? <ChevronUp className="h-3 w-3" /> : <ChevronDown className="h-3 w-3" />}
                  {showDetailPanels ? "收起详情" : "查看研究详情"}
                  {chapters.length > 0 ? <span className="text-stone-300">路 {chapters.length} 章</span> : null}
                  {events.length > 0 ? <span className="text-stone-300">路 {events.length} 条来源</span> : null}
                </button>
              )}

              <AnimatePresence initial={false}>
                {showDetailPanels ? (
                  <motion.div
                    initial={{ height: 0, opacity: 0 }}
                    animate={{ height: "auto", opacity: 1 }}
                    exit={{ height: 0, opacity: 0 }}
                    transition={{ duration: 0.25, ease: "easeInOut" }}
                    className="overflow-hidden"
                  >
                    <div className="space-y-4 pt-3">
                      <BuildChapterProgress chapters={chapters} />
                      <BuildResearchSources events={events} />
                    </div>
                  </motion.div>
                ) : null}
              </AnimatePresence>
            </div>
          ) : null}
        </motion.div>
      </div>
    </motion.div>
  );
}
