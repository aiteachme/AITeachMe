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
        "mx-auto w-full max-w-[1300px] h-full min-h-[calc(100vh-80px)] flex flex-col lg:flex-row gap-5 pb-6",
        className
      )}
    >
      {/* -------------------------------------------------------- */}
      {/* LEFT COLUMN: Progress & Status Timeline                  */}
      {/* -------------------------------------------------------- */}
      <div className="flex-shrink-0 w-full lg:w-[300px] flex flex-col gap-5">
        {/* Status / Progress Card */}
        <div className="rounded-xl border border-zinc-200 bg-white p-6 shadow-sm flex flex-col items-center justify-center text-center">
          <div className="relative mb-5">
            <svg className="w-28 h-28 transform -rotate-90">
              <circle cx="56" cy="56" r="50" stroke="currentColor" strokeWidth="6" fill="transparent" className="text-zinc-100" />
              <motion.circle
                cx="56" cy="56" r="50" stroke="currentColor" strokeWidth="6" fill="transparent"
                strokeDasharray={50 * 2 * Math.PI}
                strokeDashoffset={50 * 2 * Math.PI * (1 - roundedProgress / 100)}
                className="text-sky-500" /* using standard primary color */
                initial={{ strokeDashoffset: 50 * 2 * Math.PI }}
                animate={{ strokeDashoffset: 50 * 2 * Math.PI * (1 - roundedProgress / 100) }}
                transition={{ duration: 0.8, ease: "easeOut" }}
              />
            </svg>
            <div className="absolute inset-0 flex items-center justify-center flex-col">
              <span className="text-2xl font-bold tracking-tight text-zinc-900">
                {roundedProgress}<span className="text-lg text-zinc-500 font-medium ml-0.5">%</span>
              </span>
            </div>
          </div>
          
          <h2 className="text-[15px] font-semibold text-zinc-900 flex items-center justify-center gap-2">
            {isFetching && <Loader2 className="h-4 w-4 animate-spin text-zinc-400" />}
            {statusText || "任务初始化"}
          </h2>
          {buildPreview?.mode_reason?.trim() ? (
             <p className="mt-2 text-[12px] text-zinc-500 font-medium bg-zinc-50 px-3 py-1.5 rounded-lg border border-zinc-200/60 inline-flex">
               {buildPreview.mode_reason.trim()}
             </p>
          ) : null}
        </div>

        {/* Timeline Timeline */}
        <div className="flex-1 rounded-xl border border-zinc-200 bg-white p-5 shadow-sm overflow-hidden flex flex-col">
          <h3 className="text-xs font-semibold text-zinc-400 uppercase mb-5 flex items-center gap-1.5">
            <CheckCircle2 className="w-4 h-4" /> 执行状态
          </h3>
          <div className="flex-1 overflow-y-auto pr-2 scrollbar-thin scrollbar-webkit">
            <BuildProcessTimeline steps={timelineSteps} />
          </div>
        </div>
      </div>

      {/* -------------------------------------------------------- */}
      {/* RIGHT COLUMN: Tabbed Content Area                        */}
      {/* -------------------------------------------------------- */}
      <div className="flex-1 min-w-0 rounded-xl border border-zinc-200 bg-white shadow-sm flex flex-col overflow-hidden relative">
        {/* Tabs Header */}
        <div className="flex items-center gap-6 px-6 pt-3 border-b border-zinc-100 bg-white">
          {TABS.map((tab) => {
            const Icon = tab.icon;
            const isActive = activeTab === tab.id;
            return (
              <button
                key={tab.id}
                onClick={() => setActiveTab(tab.id)}
                className={cn(
                  "relative pb-3 flex items-center gap-2 text-[14px] transition-colors outline-none",
                  isActive ? "text-zinc-900 font-medium" : "text-zinc-500 hover:text-zinc-800 min-w-max"
                )}
              >
                <Icon className={cn("w-4 h-4", isActive ? "text-sky-500" : "text-zinc-400")} />
                {tab.label}
                {isActive && (
                  <motion.div
                    layoutId="docgen-active-tab-flat"
                    className="absolute bottom-0 left-0 right-0 h-[2px] bg-zinc-900"
                    transition={{ type: "spring", stiffness: 300, damping: 30 }}
                  />
                )}
              </button>
            );
          })}
        </div>

        {/* Tab Body */}
        <div className="flex-1 overflow-hidden relative bg-white">
          <AnimatePresence mode="wait">
            {activeTab === "parsing" && (
              <motion.div
                key="parsing"
                initial={{ opacity: 0, y: 5 }}
                animate={{ opacity: 1, y: 0 }}
                exit={{ opacity: 0, y: -5 }}
                transition={{ duration: 0.15 }}
                className="absolute inset-0 overflow-y-auto p-6 md:p-8 flex flex-col gap-8 scrollbar-thin scrollbar-webkit"
              >
                <div>
                  <h3 className="text-[14px] font-semibold text-zinc-900 mb-4">
                    本地文献提取
                  </h3>
                  <div className="bg-white p-4 rounded-xl border border-zinc-200 shadow-sm">
                     <BuildMaterialPipeline files={sourceFiles} isFetching={sourceFilesFetching} />
                  </div>
                </div>
                
                <div>
                  <h3 className="text-[14px] font-semibold text-zinc-900 mb-4">
                    构建日志与网络源
                  </h3>
                  <div className="bg-white p-4 rounded-xl border border-zinc-200 shadow-sm space-y-5">
                     <BuildResearchSources events={events} />
                     <div className="space-y-3 pt-4 border-t border-zinc-100">
                       {events.map((event, index) => {
                         const stageLabel = EVENT_STAGE_LABELS[(event.stage ?? "").trim()] ?? (event.stage?.trim() || "事件");
                         return (
                           <div key={index} className="flex gap-4 p-3 rounded-lg hover:bg-zinc-50/50 group transition-colors">
                             <div className="flex flex-col gap-1 w-24 flex-shrink-0">
                               <span className="text-[13px] font-medium text-zinc-700">{stageLabel}</span>
                               <span className="text-[12px] text-zinc-400 group-hover:text-zinc-500 transition-colors">{event.created_at ? formatBuildEventTime(event.created_at) : ""}</span>
                             </div>
                             <p className="text-[13.5px] text-zinc-600 leading-[1.6] border-l border-zinc-200 pl-4">
                               {event.summary}
                             </p>
                           </div>
                         );
                       })}
                       {events.length === 0 && (
                          <div className="text-[13px] text-center text-zinc-400 py-6">无后台事件流记录。</div>
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
                className="absolute inset-0 overflow-y-auto p-6 md:p-8 scrollbar-thin scrollbar-webkit bg-zinc-50/20"
              >
                <div className="max-w-4xl mx-auto space-y-8">
                  {/* Summary Block */}
                  <div className="bg-white rounded-xl border border-zinc-200 p-6 shadow-sm">
                     <h3 className="text-[13px] font-medium text-zinc-500 mb-3">大纲与架构思路</h3>
                     <p className="text-[14px] leading-[1.8] text-zinc-800">
                       {planSummary || "系统正在先搭稳定骨架，理解资料范围与章节边界，请稍候。"}
                     </p>
                  </div>

                  {/* Chapter Tracking Details */}
                  <div>
                    <h3 className="text-[14px] font-semibold text-zinc-900 mb-4 flex items-center justify-between">
                       章节清单
                       <span className="bg-zinc-100 text-zinc-600 rounded px-2 py-0.5 text-[12px]">
                         共计 {chapters.length} 章节
                       </span>
                    </h3>
                    
                    {chapters.length > 0 ? (
                      <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
                        {chapters.map((chapter) => {
                          const isDone = ["generated", "completed", "enhanced", "reviewed"].includes(chapter.status);
                          const isActive = ["generating", "drafting", "enhancing"].includes(chapter.status);
                          
                          return (
                            <div key={chapter.chapter_index} className={cn(
                              "flex flex-col p-4 rounded-xl border transition-all duration-200",
                              isActive
                                ? "bg-white border-sky-500/50 ring-1 ring-sky-500/20 shadow-sm"
                                : isDone
                                ? "bg-white border-zinc-200"
                                : "bg-zinc-50 border-zinc-200 border-dashed opacity-80"
                            )}>
                               <div className="flex items-start gap-3">
                                  <span className="font-mono text-zinc-400 text-[12px] mt-0.5">
                                    {String(chapter.chapter_index).padStart(2, "0")}
                                  </span>
                                  <div className="flex-1">
                                    <h4 className={cn(
                                      "text-[14px] font-medium leading-relaxed mb-1",
                                      isActive ? "text-zinc-900" : isDone ? "text-zinc-800" : "text-zinc-600"
                                    )}>{chapter.title}</h4>
                                    <p className="text-[12px] text-zinc-500 flex items-center gap-1.5">
                                      {isActive && <Activity className="w-3.5 h-3.5 text-sky-500 animate-pulse" />}
                                      {buildChapterStatusLabel(chapter.status)}
                                    </p>
                                  </div>
                               </div>
                            </div>
                          );
                        })}
                      </div>
                    ) : (
                      <div className="text-[13px] text-zinc-400 text-center py-10 border border-zinc-200 rounded-xl bg-white shadow-sm">
                         章节暂未划分。
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
                className="absolute inset-0 flex flex-col h-full bg-zinc-50/30"
              >
                 <div className="flex-1 w-full flex flex-col bg-white overflow-hidden m-6 rounded-xl border border-zinc-200 shadow-sm shadow-zinc-200/50">
                    {/* Header Info */}
                    <div className="flex items-center justify-between p-4 border-b border-zinc-100 bg-white">
                       <span className="flex items-center gap-2 text-[13px] font-medium text-zinc-600">
                         <FileText className="w-4 h-4 text-zinc-400" /> 章节预览流
                       </span>
                       {spotlightChapter ? (
                         <div className="flex items-center gap-2">
                           <span className="relative flex h-2 w-2">
                             <span className="animate-ping absolute inline-flex h-full w-full rounded-full bg-sky-500 opacity-75"></span>
                             <span className="relative inline-flex rounded-full h-2 w-2 bg-sky-500"></span>
                           </span>
                           <span className="text-[13px] font-medium text-sky-600">
                             {String(spotlightChapter.chapter_index).padStart(2, "0")}：{spotlightChapter.title}
                           </span>
                         </div>
                       ) : (
                         <span className="text-[13px] text-zinc-400">正在等待输出...</span>
                       )}
                    </div>
                    {/* Draft Content View Wrapper */}
                    <div className="flex-1 overflow-y-auto p-6 md:p-8 scrollbar-thin scrollbar-webkit">
                       {draftExcerpt ? (
                          <pre
                            className="whitespace-pre-wrap text-[15px] leading-[2.2] text-zinc-800 min-h-full break-words"
                            style={{ fontFamily: 'var(--font-serif)' }}
                          >
                            {draftExcerpt}
                            <motion.span className="ml-1 inline-block h-[15px] w-[2px] animate-blink rounded-sm bg-zinc-900 align-middle" />
                          </pre>
                       ) : (
                          <div className="h-full flex flex-col items-center justify-center text-zinc-400 space-y-4">
                             <Activity className="w-8 h-8 text-zinc-200" />
                             <p className="text-[14px]">SSE 流正准备将章节推送到此处...</p>
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
        .scrollbar-webkit::-webkit-scrollbar { width: 6px; }
        .scrollbar-webkit::-webkit-scrollbar-track { background: transparent; }
        .scrollbar-webkit::-webkit-scrollbar-thumb { background-color: rgba(161, 161, 170, 0.4); border-radius: 6px; }
      `}</style>
    </motion.div>
  );
}
