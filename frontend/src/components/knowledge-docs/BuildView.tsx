import { useEffect, useState } from "react";
import { motion, AnimatePresence } from "framer-motion";
import { BookOpen, CheckCircle2, FileText, History, LayoutTemplate, Loader2, Activity } from "lucide-react";

import { cn } from "../../lib/utils";
import type { FileRecord } from "../../api/generated/model";
import type {
  KnowledgeBuildMetrics,
  KnowledgeBuildPreview,
} from "./types";
import { BuildMaterialPipeline } from "./BuildMaterialPipeline";
import { BuildProcessTimeline, useBuildTimelineSteps } from "./BuildProcessTimeline";
import { BuildResearchSources } from "./BuildResearchSources";
import { buildChapterStatusLabel, formatBuildEventTime } from "./utils";

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

const EVENT_STAGE_LABELS: Record<string, string> = {
  build_accepted: "已受理",
  search_only_mode: "联网模式",
  planner_confirmed: "方案确认",
  preparing_docgen_context: "理解资料",
  dispatch_ready: "执行合同",
  building_document_backbone: "文档骨架",
  generating_chapters: "章节写作",
  enhancing_chapters: "章节增强",
  chapters_enhanced: "增强完成",
  reviewing_content: "复核中",
  content_reviewed: "复核完成",
  repairing_or_routing: "回流处理",
  repair_routed: "回流记录",
  merge_reviewed: "整本检查",
  titles_finalized: "标题收口",
  publishing: "发布中",
  completed: "已发布",
};

function uniqueCompact(items: string[]): string[] {
  const seen = new Set<string>();
  const values: string[] = [];
  for (const item of items) {
    const value = String(item ?? "").trim();
    if (!value) continue;
    const key = value.toLowerCase();
    if (seen.has(key)) continue;
    seen.add(key);
    values.push(value);
  }
  return values;
}

const TABS = [
  { id: "parsing", label: "解析结果", icon: History },
  { id: "outline", label: "大纲内容", icon: LayoutTemplate },
  { id: "preview", label: "动态生成预览", icon: Activity },
];

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
  const [activeTab, setActiveTab] = useState<string>("outline");

  const timelineSteps = useBuildTimelineSteps(buildStage);
  const chapters = buildPreview?.chapter_progress ?? [];
  const events = buildPreview?.recent_events ?? [];
  const roundedProgress = Math.max(0, Math.min(100, Math.round(progress)));


  const draftExcerpt = buildPreview?.draft_excerpt?.trim() ?? "";
  const planSummary = buildPreview?.plan_summary?.trim() ?? "";

  // Helper to find the chapter currently being drafted
  const spotlightChapter = chapters.find((c) =>
    ["generating", "enhancing", "reviewing", "drafting", "researching"].includes(c.status)
  ) ?? chapters.find(c => c.status !== "pending") ?? null;

  // Auto-switch to Preview tab if chapters start generating
  useEffect(() => {
    if (draftExcerpt && activeTab === "outline") {
      setActiveTab("preview");
    }
  }, [draftExcerpt]);



  return (
    <motion.div
      initial={{ opacity: 0 }}
      animate={{ opacity: 1 }}
      transition={{ duration: 0.35 }}
      className={cn(
        "mx-auto w-full max-w-[1280px] h-[calc(100vh-80px)] flex flex-col lg:flex-row gap-6",
        className
      )}
    >
      {/* -------------------------------------------------------- */}
      {/* LEFT COLUMN: Progress & Status Timeline                  */}
      {/* -------------------------------------------------------- */}
      <div className="flex-shrink-0 w-full lg:w-[320px] flex flex-col gap-6 h-full">
        {/* Progress Card */}
        <div className="rounded-[28px] border border-white/60 bg-white/70 backdrop-blur-md p-6 shadow-sm flex flex-col items-center justify-center text-center">
          <div className="relative mb-6">
            <svg className="w-32 h-32 transform -rotate-90">
              <circle
                cx="64"
                cy="64"
                r="60"
                stroke="currentColor"
                strokeWidth="6"
                fill="transparent"
                className="text-zinc-100"
              />
              <motion.circle
                cx="64"
                cy="64"
                r="60"
                stroke="currentColor"
                strokeWidth="6"
                fill="transparent"
                strokeDasharray={60 * 2 * Math.PI}
                strokeDashoffset={60 * 2 * Math.PI * (1 - roundedProgress / 100)}
                className="text-sky-500"
                initial={{ strokeDashoffset: 60 * 2 * Math.PI }}
                animate={{ strokeDashoffset: 60 * 2 * Math.PI * (1 - roundedProgress / 100) }}
                transition={{ duration: 0.8, ease: "easeOut" }}
              />
            </svg>
            <div className="absolute inset-0 flex items-center justify-center flex-col">
              <span className="text-3xl font-bold tracking-tighter text-zinc-800">{roundedProgress}<span className="text-xl">%</span></span>
            </div>
            <motion.div
              className="absolute -inset-2 rounded-full border border-sky-300/30"
              animate={{ scale: [1, 1.1, 1], opacity: [0.6, 0, 0.6] }}
              transition={{ duration: 2.5, repeat: Infinity, ease: "easeInOut" }}
            />
          </div>
          
          <h2 className="text-lg font-semibold tracking-tight text-zinc-900 flex items-center gap-2">
            {isFetching && <Loader2 className="h-4 w-4 animate-spin text-zinc-400" />}
            {statusText || "任务初始化..."}
          </h2>
          {buildPreview?.mode_reason?.trim() ? (
             <p className="mt-2 text-xs leading-5 text-sky-600 font-medium bg-sky-50 px-3 py-1 rounded-full border border-sky-100">{buildPreview.mode_reason.trim()}</p>
          ) : null}
        </div>

        {/* Timeline Timeline */}
        <div className="flex-1 rounded-[28px] border border-white/60 bg-white/70 backdrop-blur-md p-6 shadow-sm overflow-hidden flex flex-col">
          <h3 className="text-xs font-bold text-zinc-400 uppercase tracking-[0.2em] mb-6 flex items-center gap-2">
            <CheckCircle2 className="w-4 h-4 text-zinc-400" />
            执行流状态
          </h3>
          <div className="flex-1 overflow-y-auto pr-2 scrollbar-thin scrollbar-webkit">
            <BuildProcessTimeline steps={timelineSteps} />
          </div>
        </div>
      </div>

      {/* -------------------------------------------------------- */}
      {/* RIGHT COLUMN: Tabbed Content Area                        */}
      {/* -------------------------------------------------------- */}
      <div className="flex-1 min-w-0 rounded-[28px] border border-white/60 bg-white/50 backdrop-blur-xl shadow-sm flex flex-col overflow-hidden h-full">
        {/* Tabs Header */}
        <div className="flex items-center gap-4 px-6 pt-5 border-b border-zinc-200/50">
          {TABS.map((tab) => {
            const Icon = tab.icon;
            const isActive = activeTab === tab.id;
            return (
              <button
                key={tab.id}
                onClick={() => setActiveTab(tab.id)}
                className={cn(
                  "relative px-4 py-3 flex items-center gap-2 text-sm font-medium transition-colors outline-none",
                  isActive ? "text-sky-600" : "text-zinc-500 hover:text-zinc-800"
                )}
              >
                <Icon className={cn("w-4 h-4", isActive ? "text-sky-500" : "text-zinc-400")} />
                {tab.label}
                {isActive && (
                  <motion.div
                    layoutId="docgen-active-tab"
                    className="absolute bottom-0 left-0 right-0 h-[3px] bg-sky-500 rounded-t-sm"
                    transition={{ type: "spring", stiffness: 300, damping: 30 }}
                  />
                )}
              </button>
            );
          })}
        </div>

        {/* Tab Body */}
        <div className="flex-1 overflow-hidden relative bg-white/30">
          <AnimatePresence mode="wait">
            {activeTab === "parsing" && (
              <motion.div
                key="parsing"
                initial={{ opacity: 0, y: 10 }}
                animate={{ opacity: 1, y: 0 }}
                exit={{ opacity: 0, y: -10 }}
                transition={{ duration: 0.2 }}
                className="absolute inset-0 overflow-y-auto p-6 md:p-8 flex flex-col gap-8 scrollbar-thin scrollbar-webkit"
              >
                <div>
                  <h3 className="text-sm font-bold text-zinc-900 flex items-center gap-2 mb-4">
                    <BookOpen className="w-4 h-4 text-zinc-500" /> 本地文献吸收站
                  </h3>
                  <div className="bg-white/60 p-4 rounded-2xl border border-white/80 shadow-[inset_0_2px_10px_rgba(0,0,0,0.02)]">
                     <BuildMaterialPipeline files={sourceFiles} isFetching={sourceFilesFetching} />
                  </div>
                </div>
                
                <div>
                  <h3 className="text-sm font-bold text-zinc-900 flex items-center gap-2 mb-4">
                    <History className="w-4 h-4 text-zinc-500" /> 实时终端与引源
                  </h3>
                  <div className="bg-white/60 p-4 rounded-2xl border border-white/80 shadow-[inset_0_2px_10px_rgba(0,0,0,0.02)] space-y-6">
                     <BuildResearchSources events={events} />
                     <div className="space-y-2.5">
                       {events.map((event, index) => {
                         const stageLabel = EVENT_STAGE_LABELS[(event.stage ?? "").trim()] ?? (event.stage?.trim() || "事件");
                         return (
                           <div key={index} className="flex flex-col gap-1 p-3 rounded-xl bg-white/70 border border-zinc-100">
                             <div className="flex items-center gap-2 text-[11px] text-zinc-400 font-medium uppercase">
                               <span className="w-1.5 h-1.5 rounded-full bg-sky-400" />
                               {stageLabel}
                               <span className="ml-auto">{event.created_at ? formatBuildEventTime(event.created_at) : ""}</span>
                             </div>
                             <p className="text-[13px] text-zinc-600 leading-relaxed pl-3.5">
                               {event.summary}
                             </p>
                           </div>
                         );
                       })}
                       {events.length === 0 && (
                          <div className="text-[12px] text-center text-zinc-400 py-6">等待终端响应...</div>
                       )}
                     </div>
                  </div>
                </div>
              </motion.div>
            )}

            {activeTab === "outline" && (
              <motion.div
                key="outline"
                initial={{ opacity: 0, y: 10 }}
                animate={{ opacity: 1, y: 0 }}
                exit={{ opacity: 0, y: -10 }}
                transition={{ duration: 0.2 }}
                className="absolute inset-0 overflow-y-auto p-6 md:p-8 scrollbar-thin scrollbar-webkit"
              >
                <div className="max-w-4xl mx-auto space-y-8">
                  {/* Summary Block */}
                  <div className="bg-zinc-50/60 rounded-2xl border border-zinc-200/50 p-6 shadow-sm">
                     <h3 className="text-xs font-semibold uppercase tracking-[0.2em] text-zinc-400 mb-4">学习构架总结</h3>
                     <p className="text-[14px] leading-[1.8] text-zinc-700 font-serif">
                       {planSummary || "系统正在先搭稳定骨架，理解资料范围与章节边界，请稍候。"}
                     </p>
                  </div>

                  {/* Chapter Tracking Details */}
                  <div>
                    <h3 className="text-xs font-semibold uppercase tracking-[0.2em] text-zinc-400 mb-4 flex items-center justify-between">
                       章节追踪状态
                       <span className="bg-zinc-200/50 text-zinc-500 rounded-full px-2 py-0.5 text-[10px]">
                         共计 {chapters.length} 章节
                       </span>
                    </h3>
                    
                    {chapters.length > 0 ? (
                      <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                        {chapters.map((chapter) => {
                          const isDone = ["generated", "completed", "enhanced", "reviewed"].includes(chapter.status);
                          const isActive = ["generating", "drafting", "enhancing"].includes(chapter.status);
                          
                          return (
                            <div key={chapter.chapter_index} className={cn(
                              "relative group overflow-hidden flex flex-col p-4 rounded-2xl border transition-all duration-300",
                              isActive
                                ? "bg-sky-50/80 border-sky-200/60 shadow-sm"
                                : isDone
                                ? "bg-white/80 border-zinc-200/50"
                                : "bg-zinc-50/50 border-zinc-200/30 opacity-70"
                            )}>
                               <div className="flex items-start gap-3">
                                  <span className="font-mono text-zinc-400 text-xs mt-1">
                                    {String(chapter.chapter_index).padStart(2, "0")}
                                  </span>
                                  <div className="flex-1">
                                    <h4 className={cn(
                                      "text-[14px] font-medium leading-relaxed mb-1",
                                      isActive ? "text-sky-800" : isDone ? "text-zinc-800" : "text-zinc-600"
                                    )}>{chapter.title}</h4>
                                    <p className="text-[12px] text-zinc-500">
                                      {buildChapterStatusLabel(chapter.status)}
                                    </p>
                                  </div>
                                  {isActive && <Activity className="w-4 h-4 text-sky-400 animate-pulse" />}
                                  {isDone && <CheckCircle2 className="w-4 h-4 text-emerald-400" />}
                               </div>
                               {isActive && (
                                <div className="absolute bottom-0 left-0 w-full h-[2px] bg-sky-100 overflow-hidden">
                                  <motion.div
                                    className="h-full bg-sky-400"
                                    animate={{ x: ["-100%", "100%"] }}
                                    transition={{ duration: 1.5, repeat: Infinity, ease: "linear" }}
                                    style={{ width: "20%" }}
                                  />
                                </div>
                              )}
                            </div>
                          );
                        })}
                      </div>
                    ) : (
                      <div className="text-[13px] text-zinc-400 text-center py-10 border border-dashed border-zinc-300/60 rounded-2xl">
                         大纲正在构筑中，暂未就绪。
                      </div>
                    )}
                  </div>
                </div>
              </motion.div>
            )}

            {activeTab === "preview" && (
              <motion.div
                key="preview"
                initial={{ opacity: 0, y: 10 }}
                animate={{ opacity: 1, y: 0 }}
                exit={{ opacity: 0, y: -10 }}
                transition={{ duration: 0.2 }}
                className="absolute inset-0 flex flex-col p-6 md:p-8"
              >
                 <div className="flex-1 w-full max-w-4xl mx-auto flex flex-col bg-white rounded-[24px] border border-zinc-200/60 shadow-[0_4px_24px_-12px_rgba(0,0,0,0.05)] overflow-hidden">
                    {/* Header Info */}
                    <div className="flex items-center justify-between p-4 border-b border-zinc-100/80 bg-zinc-50/50">
                       <span className="flex items-center gap-2 text-xs font-semibold text-zinc-500 uppercase tracking-widest">
                         <FileText className="w-4 h-4" /> 章节预览流
                       </span>
                       {spotlightChapter ? (
                         <div className="flex items-center gap-2">
                           <span className="relative flex h-2 w-2">
                             <span className="animate-ping absolute inline-flex h-full w-full rounded-full bg-sky-400 opacity-75"></span>
                             <span className="relative inline-flex rounded-full h-2 w-2 bg-sky-500"></span>
                           </span>
                           <span className="text-[12px] font-medium text-sky-700">
                             {String(spotlightChapter.chapter_index).padStart(2, "0")}：{spotlightChapter.title}
                           </span>
                         </div>
                       ) : (
                         <span className="text-[11px] bg-zinc-200/50 text-zinc-500 px-2 py-0.5 rounded-full">等待接入</span>
                       )}
                    </div>
                    {/* Draft Content View Wrapper */}
                    <div className="flex-1 overflow-y-auto p-6 md:p-10 scrollbar-thin scrollbar-webkit">
                       {draftExcerpt ? (
                          <pre
                            className="whitespace-pre-wrap text-[14.5px] leading-[2.1] text-zinc-700"
                            style={{ fontFamily: 'var(--font-serif)' }}
                          >
                            {draftExcerpt}
                            <motion.span className="ml-1 inline-block h-[15px] w-[2px] animate-blink rounded-sm bg-sky-500 align-middle" />
                          </pre>
                       ) : (
                          <div className="h-full flex flex-col items-center justify-center text-zinc-400 space-y-4">
                             <Activity className="w-8 h-8 opacity-20" />
                             <p className="text-sm">SSE 流正准备将章节推送到此处...</p>
                          </div>
                       )}
                    </div>
                 </div>
              </motion.div>
            )}
          </AnimatePresence>
        </div>
      </div>

      <style>{`
        .scrollbar-webkit::-webkit-scrollbar { width: 4px; }
        .scrollbar-webkit::-webkit-scrollbar-track { background: transparent; }
        .scrollbar-webkit::-webkit-scrollbar-thumb { background-color: rgba(161, 161, 170, 0.4); border-radius: 4px; }
      `}</style>
    </motion.div>
  );
}
