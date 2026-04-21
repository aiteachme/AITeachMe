import { useEffect, useState } from "react";
import { motion, AnimatePresence } from "framer-motion";
import { CheckCircle2, FileText, History, LayoutTemplate, Loader2, Activity } from "lucide-react";

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
  const [activeTab, setActiveTab] = useState<string>("preview");

  const timelineSteps = useBuildTimelineSteps(buildStage);
  const chapters = buildPreview?.chapter_progress ?? [];
  const events = buildPreview?.recent_events ?? [];
  const roundedProgress = Math.max(0, Math.min(100, Math.round(progress)));

  const draftExcerpt = buildPreview?.draft_excerpt?.trim() ?? "";
  const planSummary = buildPreview?.plan_summary?.trim() ?? "";

  const spotlightChapter = chapters.find((c) =>
    ["generating", "enhancing", "reviewing", "drafting", "researching"].includes(c.status)
  ) ?? chapters.find(c => c.status !== "pending") ?? null;

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
        "mx-auto w-full max-w-[1300px] h-[calc(100vh-100px)] flex flex-col lg:flex-row bg-white rounded-xl border border-zinc-200 shadow-sm overflow-hidden",
        className
      )}
    >
      {/* -------------------------------------------------------- */}
      {/* LEFT COLUMN: Progress & Status Timeline                  */}
      {/* -------------------------------------------------------- */}
      <div className="flex-shrink-0 w-full lg:w-[260px] flex flex-col border-r border-zinc-100 bg-zinc-50/50">
        {/* Status / Progress Block */}
        <div className="p-6 flex flex-col items-center justify-center text-center border-b border-zinc-100/80">
          <div className="relative mb-4">
            <svg className="w-20 h-20 transform -rotate-90">
              <circle cx="40" cy="40" r="36" stroke="currentColor" strokeWidth="5" fill="transparent" className="text-zinc-200/60" />
              <motion.circle
                cx="40" cy="40" r="36" stroke="currentColor" strokeWidth="5" fill="transparent"
                strokeDasharray={36 * 2 * Math.PI}
                strokeDashoffset={36 * 2 * Math.PI * (1 - roundedProgress / 100)}
                className="text-sky-500"
                initial={{ strokeDashoffset: 36 * 2 * Math.PI }}
                animate={{ strokeDashoffset: 36 * 2 * Math.PI * (1 - roundedProgress / 100) }}
                transition={{ duration: 0.8, ease: "easeOut" }}
                strokeLinecap="round"
              />
            </svg>
            <div className="absolute inset-0 flex items-center justify-center flex-col">
              <span className="text-xl font-bold tracking-tight text-zinc-800">
                {roundedProgress}<span className="text-sm text-zinc-400 font-medium ml-0.5">%</span>
              </span>
            </div>
          </div>
          
          <h2 className="text-[14px] font-semibold text-zinc-800 flex items-center justify-center gap-2">
            {isFetching && <Loader2 className="h-3.5 w-3.5 animate-spin text-zinc-400" />}
            {statusText || "任务初始化"}
          </h2>
          {buildPreview?.mode_reason?.trim() ? (
             <p className="mt-2 text-[11px] text-zinc-500 font-medium bg-white px-2.5 py-1 rounded-md border border-zinc-200 inline-flex shadow-sm">
               {buildPreview.mode_reason.trim()}
             </p>
          ) : null}
        </div>

        {/* Timeline Timeline */}
        <div className="flex-1 flex flex-col p-5 overflow-hidden">
          <h3 className="text-[11px] font-semibold text-zinc-400 uppercase tracking-widest mb-4 ml-1 flex items-center gap-1.5">
            Phase Flow
          </h3>
          <div className="flex-1 overflow-y-auto pr-2 scrollbar-thin scrollbar-webkit">
            <BuildProcessTimeline steps={timelineSteps} />
          </div>
        </div>
      </div>

      {/* -------------------------------------------------------- */}
      {/* RIGHT COLUMN: Tabbed Content Area                        */}
      {/* -------------------------------------------------------- */}
      <div className="flex-1 min-w-0 flex flex-col relative bg-white">
        {/* Tabs Header */}
        <div className="flex items-center gap-7 px-8 pt-4 border-b border-zinc-100">
          {TABS.map((tab) => {
            const Icon = tab.icon;
            const isActive = activeTab === tab.id;
            return (
              <button
                key={tab.id}
                onClick={() => setActiveTab(tab.id)}
                className={cn(
                  "relative pb-3.5 flex items-center gap-2.5 text-[14px] transition-colors outline-none font-medium",
                  isActive ? "text-zinc-900" : "text-zinc-400 hover:text-zinc-700 min-w-max"
                )}
              >
                {isActive && (
                  <motion.div
                    layoutId="docgen-active-tab-flat"
                    className="absolute bottom-0 left-0 right-0 h-[2px] bg-zinc-900"
                    transition={{ type: "spring", stiffness: 300, damping: 30 }}
                  />
                )}
                {tab.label}
              </button>
            );
          })}
        </div>

        {/* Tab Body */}
        <div className="flex-1 overflow-hidden relative">
          <AnimatePresence mode="wait">
            {activeTab === "parsing" && (
              <motion.div
                key="parsing"
                initial={{ opacity: 0, y: 5 }}
                animate={{ opacity: 1, y: 0 }}
                exit={{ opacity: 0, y: -5 }}
                transition={{ duration: 0.15 }}
                className="absolute inset-0 overflow-y-auto p-8 flex flex-col gap-10 scrollbar-thin scrollbar-webkit"
              >
                <div>
                  <h3 className="text-[15px] font-semibold text-zinc-900 mb-4 tracking-tight">
                    本地文献提取
                  </h3>
                  <BuildMaterialPipeline files={sourceFiles} isFetching={sourceFilesFetching} />
                </div>
                
                <div>
                  <h3 className="text-[15px] font-semibold text-zinc-900 mb-4 tracking-tight">
                    构建日志与网络源
                  </h3>
                  <div className="space-y-6">
                     <BuildResearchSources events={events} />
                     <div className="space-y-2 pt-2">
                       {events.map((event, index) => {
                         const stageLabel = EVENT_STAGE_LABELS[(event.stage ?? "").trim()] ?? (event.stage?.trim() || "事件");
                         return (
                           <div key={index} className="flex gap-4 py-3 group transition-colors border-b border-zinc-100 last:border-0 hover:px-2 hover:-mx-2 hover:bg-zinc-50 rounded-lg">
                             <div className="flex flex-col gap-0.5 w-24 flex-shrink-0">
                               <span className="text-[12px] font-medium text-zinc-600">{stageLabel}</span>
                               <span className="text-[11px] text-zinc-400 group-hover:text-zinc-500 transition-colors">{event.created_at ? formatBuildEventTime(event.created_at) : ""}</span>
                             </div>
                             <p className="text-[13px] text-zinc-600 leading-relaxed border-l border-zinc-100 pl-4 w-full">
                               {event.summary}
                             </p>
                           </div>
                         );
                       })}
                       {events.length === 0 && (
                          <div className="text-[13px] text-center text-zinc-400 py-10">无后台事件流记录。</div>
                       )}
                     </div>
                  </div>
                </div>
              </motion.div>
            )}

            {activeTab === "outline" && (
              <motion.div
                key="outline"
                initial={{ opacity: 0, y: 5 }}
                animate={{ opacity: 1, y: 0 }}
                exit={{ opacity: 0, y: -5 }}
                transition={{ duration: 0.15 }}
                className="absolute inset-0 overflow-y-auto p-8 scrollbar-thin scrollbar-webkit"
              >
                <div className="max-w-4xl mx-auto space-y-10">
                  {/* Summary Block */}
                  <div>
                     <h3 className="text-[15px] font-semibold text-zinc-900 tracking-tight mb-3">摘要与框架思路</h3>
                     <p className="text-[14px] leading-relaxed text-zinc-600">
                       {planSummary || "系统正在理解资料范围与章节边界，等待分析..."}
                     </p>
                  </div>

                  {/* Chapter Tracking Details */}
                  <div>
                    <h3 className="text-[15px] font-semibold text-zinc-900 tracking-tight mb-5 flex items-center justify-between">
                       生成清单
                       <span className="text-zinc-400 font-normal text-[13px]">
                         共 {chapters.length} 节
                       </span>
                    </h3>
                    
                    {chapters.length > 0 ? (
                      <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                        {chapters.map((chapter) => {
                          const isDone = ["generated", "completed", "enhanced", "reviewed"].includes(chapter.status);
                          const isActive = ["generating", "drafting", "enhancing"].includes(chapter.status);
                          
                          return (
                            <div key={chapter.chapter_index} className={cn(
                              "flex flex-col p-4 rounded-xl border transition-all duration-200",
                              isActive
                                ? "bg-white border-sky-400 shadow-sm ring-1 ring-sky-100"
                                : isDone
                                ? "bg-zinc-50/50 border-zinc-200"
                                : "bg-white border-zinc-100 opacity-60"
                            )}>
                               <div className="flex items-start gap-3">
                                  <span className="font-mono text-zinc-400/80 text-[11px] mt-1">
                                    {String(chapter.chapter_index).padStart(2, "0")}
                                  </span>
                                  <div className="flex-1">
                                    <h4 className={cn(
                                      "text-[14px] font-medium leading-relaxed mb-1",
                                      isActive ? "text-sky-900" : isDone ? "text-zinc-800" : "text-zinc-600"
                                    )}>{chapter.title}</h4>
                                    <p className="text-[12px] text-zinc-500 flex items-center gap-1.5 mt-2">
                                      {isActive && <Activity className="w-3 h-3 text-sky-500 animate-pulse" />}
                                      {buildChapterStatusLabel(chapter.status)}
                                    </p>
                                  </div>
                               </div>
                            </div>
                          );
                        })}
                      </div>
                    ) : (
                      <div className="text-[13px] text-zinc-400 text-center py-12 border border-zinc-100 border-dashed rounded-xl bg-zinc-50/50">
                         骨架生成尚未就绪
                      </div>
                    )}
                  </div>
                </div>
              </motion.div>
            )}

            {activeTab === "preview" && (
              <motion.div
                key="preview"
                initial={{ opacity: 0, y: 5 }}
                animate={{ opacity: 1, y: 0 }}
                exit={{ opacity: 0, y: -5 }}
                transition={{ duration: 0.15 }}
                className="absolute inset-0 flex flex-col h-full bg-white"
              >
                  {/* Header Info */}
                  <div className="flex items-center justify-between px-8 py-4 border-b border-zinc-100">
                     <span className="flex items-center gap-2 text-[13px] font-medium text-zinc-400">
                       章节流输出口
                     </span>
                     {spotlightChapter ? (
                       <div className="flex items-center gap-2 relative">
                         <span className="relative flex h-2 w-2 mr-1">
                           <span className="animate-ping absolute inline-flex h-full w-full rounded-full bg-sky-400 opacity-75"></span>
                           <span className="relative inline-flex rounded-full h-2 w-2 bg-sky-500"></span>
                         </span>
                         <span className="text-[13px] font-medium text-zinc-800">
                           {spotlightChapter.title}
                         </span>
                       </div>
                     ) : null}
                  </div>
                  {/* Draft Content View Wrapper */}
                  <div className="flex-1 overflow-y-auto px-10 py-8 scrollbar-thin scrollbar-webkit">
                     {draftExcerpt ? (
                        <div className="max-w-3xl mx-auto">
                          <pre
                            className="whitespace-pre-wrap text-[15px] leading-relaxed text-zinc-800 break-words"
                            style={{ fontFamily: 'var(--font-serif)' }}
                          >
                            {draftExcerpt}
                            <motion.span className="ml-1 inline-block h-[15px] w-[2px] animate-blink rounded-sm bg-zinc-900 align-middle" />
                          </pre>
                        </div>
                     ) : (
                        <div className="h-full flex flex-col items-center justify-center text-zinc-400 space-y-4">
                           <Activity className="w-6 h-6 text-zinc-200" />
                           <p className="text-[13px]">实录草稿推流待命...</p>
                        </div>
                     )}
                  </div>
              </motion.div>
            )}
          </AnimatePresence>
        </div>
      </div>

      <style>{`
        .scrollbar-webkit::-webkit-scrollbar { width: 6px; }
        .scrollbar-webkit::-webkit-scrollbar-track { background: transparent; }
        .scrollbar-webkit::-webkit-scrollbar-thumb { background-color: rgba(161, 161, 170, 0.2); border-radius: 6px; }
        .scrollbar-webkit::-webkit-scrollbar-thumb:hover { background-color: rgba(161, 161, 170, 0.4); }
      `}</style>
    </motion.div>
  );
}
