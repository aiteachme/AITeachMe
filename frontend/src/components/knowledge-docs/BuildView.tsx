import { useEffect, useState } from "react";
import { motion, AnimatePresence } from "framer-motion";
import { ChevronDown, ChevronUp, Loader2, Sparkles, LayoutTemplate, Activity, History } from "lucide-react";

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

// -------------------------------------------------------------------------- //
// Build Artifact Canvas (Center Column)                                      //
// -------------------------------------------------------------------------- //

function BuildArtifactCanvas({
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
        className="flex flex-col items-center justify-center py-24 text-center rounded-2xl bg-white/60 backdrop-blur-xl border border-white/40 shadow-xl shadow-sky-900/5 h-[600px]"
      >
        <div className="relative">
          <div className="flex h-16 w-16 items-center justify-center rounded-3xl bg-zinc-50 border border-zinc-100 shadow-sm">
            <Loader2 className="h-6 w-6 animate-spin text-zinc-400" />
          </div>
          <motion.div
            className="absolute -inset-3 rounded-full border border-sky-300/30"
            animate={{ scale: [1, 1.15, 1], opacity: [0.6, 0, 0.6] }}
            transition={{ duration: 2.5, repeat: Infinity, ease: "easeInOut" }}
          />
        </div>
        <p className="mt-8 text-sm font-medium text-zinc-600 tracking-wide">正在萃取知识结晶...</p>
        <p className="mt-2 text-xs text-zinc-400">AI 正在扫描资料边界，即将构筑骨架大纲</p>
      </motion.div>
    );
  }

  return (
    <motion.div
      initial={{ opacity: 0, y: 12 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.5, ease: "easeOut" }}
      className="relative flex flex-col h-full min-h-[600px] overflow-hidden rounded-2xl border border-white/50 bg-white/70 backdrop-blur-lg shadow-xl shadow-sky-900-[0.03]"
    >
      <div className="h-[2px] overflow-hidden bg-zinc-100/50">
        <motion.div
          className="h-full bg-gradient-to-r from-sky-300 via-blue-400 to-indigo-400"
          animate={{ x: ["-100%", "100%"] }}
          transition={{ duration: 2.5, repeat: Infinity, ease: "linear" }}
          style={{ width: "50%" }}
        />
      </div>

      <div className="flex-1 px-8 py-8 md:px-12 md:py-10 flex flex-col">
        {chapterTitles.length > 0 ? (
          <motion.h1
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            transition={{ delay: 0.2 }}
            className="text-2xl font-semibold leading-tight tracking-tight text-zinc-800"
            style={{ fontFamily: "var(--font-serif)" }}
          >
            {chapterTitles[0] || "未命名知识文档"}
          </motion.h1>
        ) : null}

        {planSummary ? (
          <motion.p
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            transition={{ delay: 0.35 }}
            className="mt-4 text-[14px] leading-[1.9] text-zinc-600 bg-zinc-50/50 p-4 rounded-xl border border-zinc-100/50"
            style={{ fontFamily: "var(--font-serif)" }}
          >
            {planSummary}
          </motion.p>
        ) : null}

        {chapterTitles.length > 1 ? (
          <div className="mt-8 relative space-y-4">
            <h3 className="text-xs font-semibold text-zinc-400 uppercase tracking-widest pl-1 mb-4 flex items-center gap-2">
              <LayoutTemplate className="w-3.5 h-3.5" /> 骨架大纲
            </h3>
            <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
              {chapterTitles.slice(1).map((title, index) => {
                const chapter = (chapters ?? [])[index + 1];
                const isActive = chapter?.status === "drafting" || chapter?.status === "researching";
                const isDone = chapter?.status === "completed" || chapter?.status === "drafted";

                return (
                  <motion.div
                    key={title}
                    initial={{ opacity: 0, scale: 0.95 }}
                    animate={{ opacity: 1, scale: 1 }}
                    transition={{ delay: 0.3 + index * 0.08 }}
                    className={cn(
                      "flex flex-col gap-2 p-4 rounded-xl border transition-all duration-300",
                      isActive
                        ? "bg-sky-50/60 border-sky-200/60 shadow-sm shadow-sky-100"
                        : isDone
                        ? "bg-emerald-50/30 border-emerald-100/50"
                        : "bg-white/50 border-zinc-200/50"
                    )}
                  >
                    <div className="flex items-center gap-2.5">
                      <span
                        className={cn(
                          "h-2 w-2 shrink-0 rounded-full transition-colors duration-500",
                          isDone ? "bg-emerald-400" : isActive ? "animate-pulse bg-sky-400" : "bg-zinc-300"
                        )}
                      />
                      <span
                        className={cn(
                          "text-[13px] font-medium truncate",
                          isActive ? "text-sky-800" : isDone ? "text-emerald-800" : "text-zinc-500"
                        )}
                        style={{ fontFamily: "var(--font-sans)" }}
                      >
                        {title}
                      </span>
                    </div>
                    {isActive && (
                      <div className="pl-4">
                        <div className="h-[2px] w-full bg-sky-100 rounded-full overflow-hidden">
                          <motion.div
                            className="h-full bg-sky-400"
                            animate={{ width: ["0%", "100%", "0%"] }}
                            transition={{ duration: 2, repeat: Infinity, ease: "easeInOut" }}
                          />
                        </div>
                      </div>
                    )}
                  </motion.div>
                );
              })}
            </div>
          </div>
        ) : null}

        {draftExcerpt ? (
          <motion.div
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            transition={{ delay: 0.4 }}
            className="mt-8 flex-1 flex flex-col pt-6 border-t border-zinc-100/60 relative"
          >
             <h3 className="text-xs font-semibold text-zinc-400 uppercase tracking-widest pl-1 mb-4 flex items-center gap-2">
              <Activity className="w-3.5 h-3.5" /> 实时草稿片断
            </h3>
            <div className="flex-1 bg-white/40 rounded-xl p-5 border border-white/60 shadow-[inset_0_2px_10px_rgba(0,0,0,0.02)]">
              <pre
                className="whitespace-pre-wrap text-[13.5px] leading-[2] text-zinc-600 line-clamp-[12]"
                style={{ fontFamily: "var(--font-serif)" }}
              >
                {draftExcerpt}
                <motion.span className="ml-0.5 inline-block h-[15px] w-[2px] animate-blink rounded-sm bg-sky-500 align-middle" />
              </pre>
            </div>
          </motion.div>
        ) : null}
      </div>
    </motion.div>
  );
}

// -------------------------------------------------------------------------- //
// Live Feed List (Right Column - Top)                                        //
// -------------------------------------------------------------------------- //

function BuildLiveFeed({ events }: { events: KnowledgeBuildPreview["recent_events"] }) {
  if (!events || events.length === 0) {
    return (
      <div className="flex flex-col items-center justify-center py-8 text-zinc-400">
        <Loader2 className="w-4 h-4 animate-spin mb-2 opacity-50" />
        <span className="text-[11px]">等待系统产生事件...</span>
      </div>
    );
  }

  return (
    <div className="space-y-3 px-1">
      <AnimatePresence initial={false}>
        {events.slice().reverse().slice(0, 10).map((event, i) => (
          <motion.div
            key={`${event.created_at || i}-${i}`}
            initial={{ opacity: 0, height: 0, scale: 0.95 }}
            animate={{ opacity: Math.max(0.3, 1 - i * 0.15), height: "auto", scale: 1 }}
            exit={{ opacity: 0, height: 0 }}
            transition={{ duration: 0.3 }}
            className="flex flex-col rounded-lg border border-zinc-100/80 bg-white/60 backdrop-blur-sm p-3 text-xs shadow-sm overflow-hidden"
          >
            <div className="flex items-center gap-2 mb-1">
              <span className="w-1.5 h-1.5 rounded-full bg-sky-400 animate-pulse" />
              <span className="font-semibold text-zinc-700">{event.title || event.stage}</span>
            </div>
            <p className="text-zinc-500 line-clamp-2 leading-relaxed ml-3.5">
              {event.summary || "进行了一次知识萃取分析..."}
            </p>
          </motion.div>
        ))}
      </AnimatePresence>
    </div>
  );
}

// -------------------------------------------------------------------------- //
// Main Build Workspace (Theater Layout)                                      //
// -------------------------------------------------------------------------- //

export function BuildView({
  isFetching,
  progress,
  statusText,
  buildPreview,
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
    () => typeof window === "undefined" || window.innerWidth >= 1024
  );
  const [showDetailsMobile, setShowDetailsMobile] = useState(false);

  useEffect(() => {
    if (typeof window === "undefined") return undefined;
    const handleResize = () => {
      setIsDesktop(window.innerWidth >= 1024);
    };
    window.addEventListener("resize", handleResize);
    return () => window.removeEventListener("resize", handleResize);
  }, []);

  return (
    <motion.div
      initial={{ opacity: 0 }}
      animate={{ opacity: 1 }}
      transition={{ duration: 0.4 }}
      className={cn("mx-auto w-full max-w-[1400px] py-4", className)}
    >
      {/* 顶部标题栏：融合了进度和状态 */}
      <motion.div
        initial={{ opacity: 0, y: -8 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ delay: 0.08, duration: 0.35 }}
        className="mb-6 rounded-2xl border border-white/60 bg-white/70 backdrop-blur-xl px-5 py-4 shadow-sm shadow-sky-900/5 flex items-center justify-between gap-4"
      >
        <div className="flex items-center gap-3">
          <div className="relative shrink-0">
            <div className="flex h-10 w-10 items-center justify-center rounded-xl bg-zinc-900 shadow-sm">
              <Sparkles className="h-4 w-4 text-white" />
            </div>
            <motion.div
              className="absolute -inset-1 rounded-xl border border-zinc-300/40"
              animate={{ scale: [1, 1.18, 1], opacity: [0.45, 0, 0.45] }}
              transition={{ duration: 2, repeat: Infinity }}
            />
          </div>
          <div>
            <h2 className="text-sm font-bold text-zinc-900 flex items-center gap-2">
              知识文档工作台
              <span className="rounded-full bg-sky-100 px-2 py-0.5 text-[10px] text-sky-700 font-semibold border border-sky-200/50">
                Building
              </span>
            </h2>
            <p className="text-[12px] text-zinc-500 mt-0.5 flex items-center gap-1.5">
              {isFetching && <Loader2 className="h-3 w-3 animate-spin text-zinc-400" />}
              {statusText}
            </p>
          </div>
        </div>
        <div className="flex flex-col items-end hidden sm:flex min-w-[200px]">
          <span className="text-xs font-bold text-zinc-700 mb-1.5">{Math.round(progress)}% 已完成</span>
          <div className="w-full h-1.5 overflow-hidden rounded-full bg-zinc-100/80 shadow-inner">
            <motion.div
              initial={{ width: 0 }}
              animate={{ width: `${progress}%` }}
              transition={{ duration: 0.8, ease: "easeOut" }}
              className="h-full rounded-full bg-gradient-to-r from-sky-400 to-indigo-500"
            />
          </div>
        </div>
      </motion.div>

      {/* 剧场主体三栏布局 (Desktop) 或 Tab状 (Mobile) */}
      <div className="grid grid-cols-1 lg:grid-cols-[260px_1fr_320px] gap-6 items-start">
        {/* 左栏：生命周期 */}
        <motion.div
          initial={{ opacity: 0, x: -12 }}
          animate={{ opacity: 1, x: 0 }}
          transition={{ delay: 0.12, duration: 0.35 }}
          className="lg:sticky lg:top-6 flex flex-col gap-5"
        >
          <div className="rounded-2xl border border-white/60 bg-white/70 backdrop-blur-md p-5 shadow-sm">
            <h3 className="text-xs font-bold text-zinc-900 uppercase tracking-widest mb-4">执行生命线</h3>
            <BuildProcessTimeline steps={timelineSteps} />
          </div>
          
          <div className="rounded-2xl border border-white/60 bg-white/70 backdrop-blur-md p-5 shadow-sm">
            <h3 className="text-xs font-bold text-zinc-900 uppercase tracking-widest mb-4">文献吸收站</h3>
            <BuildMaterialPipeline files={sourceFiles} isFetching={sourceFilesFetching} />
          </div>
        </motion.div>

        {/* 中栏：产物画布 */}
        <motion.div
          initial={{ opacity: 0, y: 12 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ delay: 0.18, duration: 0.4 }}
          className="flex flex-col w-full min-w-0"
        >
          <BuildArtifactCanvas
            draftExcerpt={draftExcerpt}
            chapterTitles={chapterTitles}
            planSummary={planSummary}
            chapters={chapters}
          />
        </motion.div>

        {/* 右栏：实时动态与溯源 */}
        <motion.div
          initial={{ opacity: 0, x: 12 }}
          animate={{ opacity: 1, x: 0 }}
          transition={{ delay: 0.24, duration: 0.35 }}
          className={cn(
            "lg:sticky lg:top-6 flex flex-col gap-6",
            !isDesktop && !showDetailsMobile && "hidden"
          )}
        >
          {/* 事件流面板 */}
          <div className="rounded-2xl border border-white/60 bg-white/70 backdrop-blur-md p-5 shadow-sm max-h-[400px] flex flex-col">
            <h3 className="text-xs font-bold text-zinc-900 uppercase tracking-widest mb-4 flex items-center justify-between">
              <span className="flex items-center gap-1.5"><History className="w-3.5 h-3.5" /> 实时终端</span>
              <span className="flex h-2 w-2 rounded-full bg-emerald-400 animate-pulse" />
            </h3>
            <div className="flex-1 overflow-y-auto pr-2 -mr-2 scrollbar-thin scrollbar-webkit">
              <BuildLiveFeed events={events} />
            </div>
          </div>

          {/* 溯源与状态检查面板 */}
          {(chapters.length > 0 || events.length > 0) && (
            <div className="rounded-2xl border border-white/60 bg-white/70 backdrop-blur-md p-5 shadow-sm flex flex-col max-h-[400px]">
              <h3 className="text-xs font-bold text-zinc-900 uppercase tracking-widest mb-4 flex items-center gap-1.5">
                <LayoutTemplate className="w-3.5 h-3.5" /> 引用与状态溯源
              </h3>
              <div className="flex-1 overflow-y-auto pr-2 -mr-2 scrollbar-thin scrollbar-webkit space-y-4">
                 <BuildResearchSources events={events} />
                 <BuildChapterProgress chapters={chapters} />
              </div>
            </div>
          )}
        </motion.div>

        {/* 移动端切换详情的入口 */}
        {!isDesktop && (
          <div className="fixed bottom-4 left-4 right-4 z-50">
           <button
             type="button"
             onClick={() => setShowDetailsMobile(!showDetailsMobile)}
             className="w-full flex items-center justify-center gap-2 rounded-xl bg-zinc-900 text-white shadow-xl shadow-zinc-900/20 py-3.5 text-sm font-semibold transition-transform active:scale-[0.98]"
           >
             {showDetailsMobile ? <ChevronUp className="h-4 w-4" /> : <ChevronDown className="h-4 w-4" />}
             {showDetailsMobile ? "返回主视图" : "查看执行详情日志"}
           </button>
          </div>
        )}
      </div>

      <style>{`
        /* 避免因为右侧滚动条影响高度的自定义简单滚动条 */
        .scrollbar-webkit::-webkit-scrollbar {
          width: 4px;
        }
        .scrollbar-webkit::-webkit-scrollbar-track {
          background: transparent;
        }
        .scrollbar-webkit::-webkit-scrollbar-thumb {
          background-color: rgba(161, 161, 170, 0.4);
          border-radius: 4px;
        }
      `}</style>
    </motion.div>
  );
}
