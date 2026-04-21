import { useEffect, useState } from "react";
import { motion, AnimatePresence } from "framer-motion";
import { Check, CheckCircle2, FileText, History, LayoutTemplate, Loader2, Activity } from "lucide-react";

import { cn } from "../../lib/utils";
import type { FileRecord } from "../../api/generated/model";
import type {
  KnowledgeBuildMetrics,
  KnowledgeBuildPreview,
} from "./types";
import { BuildMaterialPipeline } from "./BuildMaterialPipeline";
import { useBuildTimelineSteps } from "./BuildProcessTimeline";
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
  { id: "parsing", label: "解析结果" },
  { id: "outline", label: "大纲内容" },
  { id: "preview", label: "动态生成预览" },
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
        "mx-auto w-full max-w-[1300px] h-[75vh] min-h-[600px] flex flex-col lg:flex-row bg-white rounded-xl border border-zinc-200 overflow-hidden shadow-sm",
        className
      )}
    >
      {/* -------------------------------------------------------- */}
      {/* LEFT COLUMN: Ultra Minimal Progress & Timeline             */}
      {/* -------------------------------------------------------- */}
      <div className="flex-shrink-0 w-full lg:w-[260px] flex flex-col border-r border-[#E5E7EB] bg-[#FAFAFA]">
        {/* Progress Header */}
        <div className="p-6 pb-5 border-b border-[#E5E7EB]">
          <div className="flex items-center justify-between mb-3">
            <h2 className="text-[13px] font-semibold text-zinc-900 tracking-wide flex items-center gap-1.5">
              {isFetching && <Loader2 className="w-3.5 h-3.5 animate-spin text-zinc-400" />}
              {statusText || "任务初始化..."}
            </h2>
            <span className={cn(
              "text-[12px] font-medium px-2 py-0.5 rounded-full border",
              roundedProgress === 100 
                ? "bg-emerald-50 text-emerald-600 border-emerald-100"
                : "bg-blue-50 text-blue-600 border-blue-100"
            )}>
              {roundedProgress}%
            </span>
          </div>
          <div className="h-[3px] w-full bg-zinc-200/60 rounded-full overflow-hidden">
             <motion.div 
                className="h-full bg-blue-500 rounded-full" 
                initial={{width:0}} 
                animate={{width:`${roundedProgress}%`}} 
                transition={{ duration: 0.5 }} 
             />
          </div>
          {buildPreview?.mode_reason?.trim() ? (
             <p className="mt-4 text-[11px] text-zinc-500 bg-white border border-zinc-200 rounded px-2 py-1 leading-snug">
               {buildPreview.mode_reason.trim()}
             </p>
          ) : null}
        </div>

        {/* Minimal Timeline Rail */}
        <div className="flex-1 overflow-y-auto px-6 py-6 scrollbar-thin scrollbar-webkit">
           <h3 className="text-[10px] font-semibold text-zinc-400 uppercase tracking-widest mb-6">Phase Flow</h3>
           <div className="relative border-l border-zinc-200 ml-[7px] space-y-7">
             {timelineSteps.map((step, idx) => {
                const isDone = step.state === "done";
                const isActive = step.state === "active";
                return (
                  <div key={step.key} className="relative pl-6">
                     {/* Node Dot */}
                     <div className={cn(
                       "absolute left-[-9px] top-[1px] w-4 h-4 rounded-full border-[2px] bg-white flex items-center justify-center transition-colors",
                       isDone ? "border-blue-500 bg-blue-500" : isActive ? "border-blue-500" : "border-zinc-200"
                     )}>
                       {isDone && <Check className="w-2.5 h-2.5 text-white" strokeWidth={3} />}
                       {isActive && <div className="w-1.5 h-1.5 rounded-full bg-blue-500" />}
                     </div>
                     {/* Content */}
                     <div>
                       <div className={cn("text-[13px] leading-none mb-1.5 flex items-center gap-1.5", 
                          isActive ? "text-blue-600 font-medium" : isDone ? "text-zinc-700" : "text-zinc-400"
                       )}>
                         <span className="text-[10px] font-mono opacity-60">0{idx + 1}</span>
                         {step.title}
                       </div>
                       {isActive && (
                         <div className="text-[11px] text-zinc-500 leading-snug">
                           {step.description}
                         </div>
                       )}
                     </div>
                  </div>
                )
             })}
           </div>
        </div>
      </div>

      {/* -------------------------------------------------------- */}
      {/* RIGHT COLUMN: Minimal Tosea Tab Canvas                   */}
      {/* -------------------------------------------------------- */}
      <div className="flex-1 min-w-0 flex flex-col relative bg-white">
        {/* Navigation Tabs (Top Edge) */}
        <div className="h-14 flex items-end px-8 gap-8 border-b border-[#E5E7EB]">
          {TABS.map((tab) => {
            const isActive = activeTab === tab.id;
            return (
              <button
                key={tab.id}
                onClick={() => setActiveTab(tab.id)}
                className={cn(
                  "relative pb-3.5 text-[14px] transition-colors outline-none",
                  isActive ? "text-black font-semibold" : "text-zinc-500 hover:text-zinc-800 font-medium min-w-max"
                )}
              >
                {isActive && (
                  <motion.div
                    layoutId="tosea-tab-indicator"
                    className="absolute bottom-0 left-0 right-0 h-[2px] bg-black"
                  />
                )}
                {tab.label}
              </button>
            );
          })}
        </div>

        {/* Dynamic Canvas Panel */}
        <div className="flex-1 overflow-hidden relative">
          <AnimatePresence mode="wait">
            {activeTab === "parsing" && (
              <motion.div
                key="parsing"
                initial={{ opacity: 0 }}
                animate={{ opacity: 1 }}
                exit={{ opacity: 0 }}
                transition={{ duration: 0.15 }}
                className="absolute inset-0 overflow-y-auto px-10 py-8 flex flex-col gap-10 scrollbar-thin scrollbar-webkit"
              >
                {/* File intake flat list */}
                <div>
                  <h3 className="text-[14px] font-semibold text-black mb-5 tracking-tight flex items-center gap-2">
                    本地文献提取
                    <span className="font-normal text-[12px] text-zinc-500 bg-zinc-100 px-2 py-0.5 rounded">{sourceFiles.length} 份</span>
                  </h3>
                  <div className="border border-[#E5E7EB] rounded-lg bg-[#FAFAFA] p-5">
                    <BuildMaterialPipeline files={sourceFiles} isFetching={sourceFilesFetching} className="!border-0 !p-0 !bg-transparent !shadow-none !rounded-none" />
                  </div>
                </div>
                
                {/* Event stream flat style */}
                <div>
                  <h3 className="text-[14px] font-semibold text-black mb-5 tracking-tight flex items-center gap-2">
                    构建日志与网络源
                    <span className="font-normal text-[12px] text-zinc-500 bg-zinc-100 px-2 py-0.5 rounded">{events.length} 条</span>
                  </h3>
                  <div className="border border-[#E5E7EB] rounded-lg p-5">
                     <BuildResearchSources events={events} className="!border-0 !p-0 !bg-transparent !shadow-none !rounded-none" />
                     <div className="space-y-0 pt-4 mt-4 border-t border-[#E5E7EB]">
                       {events.map((event, index) => {
                         const stageLabel = EVENT_STAGE_LABELS[(event.stage ?? "").trim()] ?? (event.stage?.trim() || "事件");
                         return (
                           <div key={index} className="flex gap-6 py-3 border-b border-[#F3F4F6] last:border-0 hover:bg-zinc-50 transition-colors -mx-5 px-5">
                             <div className="flex flex-col gap-0.5 w-[110px] flex-shrink-0">
                               <span className="text-[12px] font-medium text-zinc-700">{stageLabel}</span>
                               <span className="text-[11px] text-zinc-400">{event.created_at ? formatBuildEventTime(event.created_at) : ""}</span>
                             </div>
                             <p className="text-[12px] text-zinc-600 leading-relaxed max-w-[500px]">
                               {event.summary}
                             </p>
                           </div>
                         );
                       })}
                       {events.length === 0 && (
                          <div className="text-[12px] text-center text-zinc-400 py-6">无后台事件流记录。</div>
                       )}
                     </div>
                  </div>
                </div>
              </motion.div>
            )}

            {activeTab === "outline" && (
              <motion.div
                key="outline"
                initial={{ opacity: 0 }}
                animate={{ opacity: 1 }}
                exit={{ opacity: 0 }}
                transition={{ duration: 0.15 }}
                className="absolute inset-0 overflow-y-auto px-10 py-10 scrollbar-thin scrollbar-webkit"
              >
                <div className="max-w-3xl space-y-12">
                  <div>
                     <h3 className="text-[14px] font-semibold text-zinc-900 tracking-tight mb-4">摘要与框架思路</h3>
                     <p className="text-[13px] leading-relaxed text-zinc-600 border-l-2 border-blue-500 pl-4">
                       {planSummary || "系统正在理解资料范围与章节边界..."}
                     </p>
                  </div>

                  <div>
                    <h3 className="text-[14px] font-semibold text-zinc-900 tracking-tight mb-5 flex items-center justify-between">
                       生成的章节大纲
                       <span className="text-zinc-500 font-normal text-[12px] bg-zinc-100 px-2 py-0.5 rounded">总体 {chapters.length} 节</span>
                    </h3>
                    
                    {chapters.length > 0 ? (
                      <div className="grid grid-cols-1 md:grid-cols-2 gap-x-6 gap-y-4">
                        {chapters.map((chapter) => {
                          const isDone = ["generated", "completed", "enhanced", "reviewed"].includes(chapter.status);
                          const isActive = ["generating", "drafting", "enhancing"].includes(chapter.status);
                          
                          return (
                            <div key={chapter.chapter_index} className={cn(
                              "flex flex-col py-3 px-1 border-b transition-all duration-200",
                              isActive
                                ? "border-black"
                                : "border-[#E5E7EB]"
                            )}>
                               <div className="flex items-start gap-4">
                                  <span className="font-mono text-zinc-300 text-[11px] mt-[3px]">
                                    {String(chapter.chapter_index).padStart(2, "0")}
                                  </span>
                                  <div className="flex-1">
                                    <h4 className={cn(
                                      "text-[13px] font-medium leading-relaxed",
                                      isActive ? "text-black" : isDone ? "text-zinc-800" : "text-zinc-400"
                                    )}>{chapter.title}</h4>
                                    <p className="text-[11px] text-zinc-400 flex items-center gap-1.5 mt-1.5">
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
                      <div className="text-[12px] text-zinc-400 text-center py-16 bg-[#FAFAFA] rounded-xl border border-zinc-100">
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
                initial={{ opacity: 0 }}
                animate={{ opacity: 1 }}
                exit={{ opacity: 0 }}
                transition={{ duration: 0.15 }}
                className="absolute inset-0 flex flex-col h-full bg-white"
              >
                  {/* Subtle Top Info Bar */}
                  <div className="flex items-center justify-between px-10 py-3 bg-[#FAFAFA] border-b border-[#E5E7EB]">
                     <span className="text-[12px] font-medium text-zinc-500">
                       正在串流的推断章节
                     </span>
                     {spotlightChapter ? (
                       <div className="flex items-center gap-2">
                         <span className="relative flex h-1.5 w-1.5 mr-1">
                           <span className="animate-ping absolute inline-flex h-full w-full rounded-full bg-sky-400 opacity-75"></span>
                           <span className="relative inline-flex rounded-full h-1.5 w-1.5 bg-sky-500"></span>
                         </span>
                         <span className="text-[12px] font-medium text-zinc-900">
                           {spotlightChapter.title}
                         </span>
                       </div>
                     ) : (
                       <span className="text-[12px] text-zinc-400">-</span>
                     )}
                  </div>
                  
                  {/* Markdown/Raw Push View */}
                  <div className="flex-1 overflow-y-auto px-10 py-10 scrollbar-thin scrollbar-webkit">
                     {draftExcerpt ? (
                        <div className="max-w-[700px] mx-auto pb-10">
                          <pre
                            className="whitespace-pre-wrap text-[14px] leading-[1.8] text-zinc-800 break-words"
                            style={{ fontFamily: 'var(--font-serif)' }}
                          >
                            {draftExcerpt}
                            <motion.span className="ml-[2px] inline-block h-[15px] w-[2px] animate-blink bg-blue-500 align-middle" />
                          </pre>
                        </div>
                     ) : (
                        <div className="h-full flex flex-col items-center justify-center text-zinc-400/80 space-y-5">
                           <Activity className="w-8 h-8 text-zinc-200" strokeWidth={1.5} />
                           <p className="text-[12px]">静静等待系统推流...</p>
                        </div>
                     )}
                  </div>
              </motion.div>
            )}
          </AnimatePresence>
        </div>
      </div>

      <style>{`
        .scrollbar-webkit::-webkit-scrollbar { width: 5px; }
        .scrollbar-webkit::-webkit-scrollbar-track { background: transparent; }
        .scrollbar-webkit::-webkit-scrollbar-thumb { background-color: rgba(161, 161, 170, 0.3); border-radius: 4px; }
        .scrollbar-webkit::-webkit-scrollbar-thumb:hover { background-color: rgba(161, 161, 170, 0.5); }
      `}</style>
    </motion.div>
  );
}
