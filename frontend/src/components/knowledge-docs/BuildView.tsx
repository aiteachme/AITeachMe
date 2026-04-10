/* ------------------------------------------------------------------ */
/*  BuildView — Gemini Deep Research Canvas-first build view           */
/*  Center: live-updating document canvas with typewriter effect       */
/*  Left sidebar: compact timeline + metrics                           */
/* ------------------------------------------------------------------ */

import { useState } from "react";
import { motion, AnimatePresence } from "framer-motion";
import { Loader2, Sparkles, ChevronDown, ChevronUp } from "lucide-react";
import { cn } from "../../lib/utils";
import type { KnowledgeBuildPreview, KnowledgeBuildMetrics } from "./types";
import type { FileRecord } from "../../api/generated/model";
import { BuildProcessTimeline, useBuildTimelineSteps } from "./BuildProcessTimeline";
import { BuildChapterProgress } from "./BuildChapterProgress";
import { BuildResearchSources } from "./BuildResearchSources";
import { BuildMaterialPipeline } from "./BuildMaterialPipeline";

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

/* ---- Compact inline metrics ---- */
function InlineMetrics({ metrics, preview }: { metrics: KnowledgeBuildMetrics | null; preview: KnowledgeBuildPreview | null }) {
  const parts: string[] = [];
  const chunks = preview?.total_chunks;
  if (chunks && chunks > 0) parts.push(`${preview?.processed_chunks ?? 0}/${chunks} 分片`);
  const nodes = preview?.discovered_node_count;
  if (nodes && nodes > 0) parts.push(`${nodes} 节点`);
  const calls = metrics?.llm_total_calls;
  if (calls && calls > 0) parts.push(`${calls} 调用`);
  const lat = metrics?.llm_avg_latency_ms;
  if (lat && lat > 0) parts.push(lat < 1000 ? `${Math.round(lat)}ms` : `${(lat / 1000).toFixed(1)}s`);
  if (parts.length === 0) return null;
  return (
    <div className="flex flex-wrap gap-x-2 gap-y-0.5 text-[10px] text-stone-400">
      {parts.map((p) => (
        <span key={p} className="inline-flex items-center gap-0.5">
          <span className="w-1 h-1 rounded-full bg-stone-300 inline-block" />
          {p}
        </span>
      ))}
    </div>
  );
}

/* ---- Live Document Canvas ---- */
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
          <div className="w-12 h-12 rounded-2xl bg-stone-100 flex items-center justify-center">
            <Loader2 className="w-5 h-5 text-stone-400 animate-spin" />
          </div>
          <motion.div
            className="absolute -inset-2 rounded-2xl border border-sky-300/30"
            animate={{ scale: [1, 1.15, 1], opacity: [0.6, 0, 0.6] }}
            transition={{ duration: 2.5, repeat: Infinity, ease: "easeInOut" }}
          />
        </div>
        <p className="mt-5 text-[13px] text-stone-500">正在准备知识文档...</p>
        <p className="mt-1 text-[11px] text-stone-400">AI 正在分析材料，预计 3-10 分钟</p>
      </motion.div>
    );
  }

  /* Render a document-like canvas */
  return (
    <motion.div
      initial={{ opacity: 0, y: 12 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.5, ease: "easeOut" }}
      className="relative"
    >
      {/* Document surface */}
      <div className="rounded-xl border border-stone-200/70 bg-white shadow-[0_1px_3px_rgba(0,0,0,0.04),0_8px_24px_-8px_rgba(0,0,0,0.06)] overflow-hidden">
        {/* Thin gradient top bar — indicates "writing in progress" */}
        <div className="h-[2px] bg-stone-100 overflow-hidden">
          <motion.div
            className="h-full bg-gradient-to-r from-sky-400 via-blue-400 to-sky-400"
            animate={{ x: ["-100%", "100%"] }}
            transition={{ duration: 2, repeat: Infinity, ease: "linear" }}
            style={{ width: "50%" }}
          />
        </div>

        <div className="px-7 py-6 md:px-10 md:py-8">
          {/* Document title — first chapter or plan summary */}
          {chapterTitles.length > 0 && (
            <motion.h1
              initial={{ opacity: 0 }}
              animate={{ opacity: 1 }}
              transition={{ delay: 0.2 }}
              className="text-xl font-semibold text-stone-800 tracking-tight leading-tight"
              style={{ fontFamily: "var(--font-serif)" }}
            >
              {chapterTitles[0]}
            </motion.h1>
          )}

          {/* Plan summary as opening paragraph */}
          {planSummary && (
            <motion.p
              initial={{ opacity: 0 }}
              animate={{ opacity: 1 }}
              transition={{ delay: 0.35 }}
              className="mt-3 text-[13.5px] leading-[1.9] text-stone-600"
              style={{ fontFamily: "var(--font-serif)" }}
            >
              {planSummary}
            </motion.p>
          )}

          {/* Chapter outline as section headings */}
          {chapterTitles.length > 1 && (
            <div className="mt-5 space-y-1.5">
              {chapterTitles.slice(1).map((title, i) => {
                const chapter = (chapters ?? [])[i + 1];
                const isActive = chapter?.status === "drafting" || chapter?.status === "researching";
                const isDone = chapter?.status === "completed" || chapter?.status === "drafted";

                return (
                  <motion.div
                    key={title}
                    initial={{ opacity: 0, x: -6 }}
                    animate={{ opacity: 1, x: 0 }}
                    transition={{ delay: 0.3 + i * 0.08 }}
                    className="flex items-center gap-2.5 py-1"
                  >
                    <span className={cn(
                      "w-1.5 h-1.5 rounded-full shrink-0 transition-colors",
                      isDone ? "bg-emerald-400" : isActive ? "bg-sky-400 animate-pulse" : "bg-stone-300",
                    )} />
                    <span className={cn(
                      "text-[13px] font-medium",
                      isActive ? "text-sky-700" : isDone ? "text-stone-700" : "text-stone-400",
                    )}
                      style={{ fontFamily: "var(--font-serif)" }}
                    >
                      {title}
                    </span>
                    {isActive && (
                      <span className="text-[10px] text-sky-500 bg-sky-50 px-1.5 py-0.5 rounded">撰写中</span>
                    )}
                  </motion.div>
                );
              })}
            </div>
          )}

          {/* Live draft excerpt — the main canvas content */}
          {draftExcerpt && (
            <motion.div
              initial={{ opacity: 0 }}
              animate={{ opacity: 1 }}
              transition={{ delay: 0.4 }}
              className="mt-6 pt-5 border-t border-stone-100"
            >
              <pre
                className="whitespace-pre-wrap text-[13.5px] leading-[2] text-stone-600 max-h-[320px] overflow-y-auto"
                style={{ fontFamily: "var(--font-serif)" }}
              >
                {draftExcerpt}
                <motion.span
                  className="inline-block w-[2px] h-[15px] bg-sky-500 ml-0.5 align-middle rounded-sm animate-blink"
                />
              </pre>
            </motion.div>
          )}

          {/* Bottom fade — indicates more content coming */}
          {draftExcerpt && (
            <div className="h-12 -mt-12 relative z-10 bg-gradient-to-t from-white to-transparent pointer-events-none" />
          )}
        </div>
      </div>
    </motion.div>
  );
}

/* ------------------------------------------------------------------ */
/*  Main BuildView                                                     */
/* ------------------------------------------------------------------ */

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
  const [showDetails, setShowDetails] = useState(false);

  return (
    <motion.div
      initial={{ opacity: 0 }}
      animate={{ opacity: 1 }}
      transition={{ duration: 0.4 }}
      className={cn("mx-auto w-full max-w-[1100px] py-6", className)}
    >
      {/* Compact header row */}
      <motion.div
        initial={{ opacity: 0, y: -8 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ delay: 0.08, duration: 0.35 }}
        className="mb-5 flex items-center gap-3"
      >
        {/* Pulsing icon */}
        <div className="relative shrink-0">
          <div className="w-9 h-9 rounded-xl bg-gradient-to-br from-sky-500 to-blue-600 flex items-center justify-center shadow-md shadow-sky-500/15">
            <Sparkles className="w-4 h-4 text-white" />
          </div>
          <motion.div
            className="absolute -inset-1 rounded-xl border border-sky-400/25"
            animate={{ scale: [1, 1.2, 1], opacity: [0.5, 0, 0.5] }}
            transition={{ duration: 2, repeat: Infinity }}
          />
        </div>

        {/* Status + progress inline */}
        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-2">
            <p className="text-sm font-medium text-stone-800 truncate">{statusText}</p>
            {isFetching && <Loader2 className="w-3 h-3 animate-spin text-stone-300 shrink-0" />}
            <span className="text-[11px] font-semibold text-sky-600 ml-auto shrink-0">{Math.round(progress)}%</span>
          </div>
          {/* Slim progress bar */}
          <div className="mt-1.5 h-[3px] rounded-full bg-stone-100 overflow-hidden">
            <motion.div
              initial={{ width: 0 }}
              animate={{ width: `${progress}%` }}
              transition={{ duration: 0.8, ease: "easeOut" }}
              className="h-full rounded-full bg-gradient-to-r from-sky-500 to-blue-500"
            />
          </div>
          {/* Inline metrics */}
          <div className="mt-1.5">
            <InlineMetrics metrics={buildMetrics} preview={buildPreview} />
          </div>
        </div>
      </motion.div>

      {/* Two-column: Timeline sidebar + Document Canvas */}
      <div className="grid grid-cols-1 lg:grid-cols-[220px_1fr] gap-5">
        {/* Left — Compact timeline */}
        <motion.div
          initial={{ opacity: 0, x: -12 }}
          animate={{ opacity: 1, x: 0 }}
          transition={{ delay: 0.12, duration: 0.35 }}
          className="lg:sticky lg:top-6 lg:self-start"
        >
          <BuildProcessTimeline steps={timelineSteps} />

          {/* Material pipeline — compact below timeline */}
          <BuildMaterialPipeline
            files={sourceFiles}
            isFetching={sourceFilesFetching}
            className="mt-4"
          />
        </motion.div>

        {/* Right — Document canvas (main focus) */}
        <motion.div
          initial={{ opacity: 0, y: 12 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ delay: 0.18, duration: 0.4 }}
          className="space-y-4"
        >
          {/* The live document */}
          <DocumentCanvas
            draftExcerpt={draftExcerpt}
            chapterTitles={chapterTitles}
            planSummary={planSummary}
            chapters={chapters}
          />

          {/* Expandable details section */}
          {(chapters.length > 0 || events.length > 0) && (
            <div>
              <button
                onClick={() => setShowDetails(!showDetails)}
                className="inline-flex items-center gap-1.5 text-[11px] font-medium text-stone-400 hover:text-stone-600 transition-colors"
              >
                {showDetails ? <ChevronUp className="w-3 h-3" /> : <ChevronDown className="w-3 h-3" />}
                {showDetails ? "收起详情" : "查看研究详情"}
                {chapters.length > 0 && <span className="text-stone-300">· {chapters.length} 章</span>}
                {events.length > 0 && <span className="text-stone-300">· {events.length} 来源</span>}
              </button>

              <AnimatePresence>
                {showDetails && (
                  <motion.div
                    initial={{ height: 0, opacity: 0 }}
                    animate={{ height: "auto", opacity: 1 }}
                    exit={{ height: 0, opacity: 0 }}
                    transition={{ duration: 0.25, ease: "easeInOut" }}
                    className="overflow-hidden"
                  >
                    <div className="pt-3 space-y-4">
                      <BuildChapterProgress chapters={chapters} />
                      <BuildResearchSources events={events} />
                    </div>
                  </motion.div>
                )}
              </AnimatePresence>
            </div>
          )}
        </motion.div>
      </div>
    </motion.div>
  );
}
