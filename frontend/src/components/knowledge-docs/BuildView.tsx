import { useEffect, useState } from "react";
import { motion, AnimatePresence } from "framer-motion";
import { Check, CheckCircle2, FileText, Loader2, Activity, PlayCircle, FileSearch, Code2 } from "lucide-react";

import { cn } from "../../lib/utils";
import type { FileRecord } from "../../api/generated/model";
import type {
  KnowledgeBuildMetrics,
  KnowledgeBuildPreview,
} from "./types";
import { BuildMaterialPipeline } from "./BuildMaterialPipeline";
import { useBuildTimelineSteps } from "./BuildProcessTimeline";
import { BuildResearchSources } from "./BuildResearchSources";
import { buildChapterStatusLabel, formatBuildEventTime, resolveFileProcessingLabel } from "./utils";

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
  { id: "logs", label: "构建日志" },
  { id: "files", label: "文件解析" },
  { id: "outline", label: "大纲内容" },
  { id: "preview", label: "动态生成" },
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
  const [selectedPreviewChapter, setSelectedPreviewChapter] = useState<number | null>(null);

  const timelineSteps = useBuildTimelineSteps(buildStage);
  const chapters = buildPreview?.chapter_progress ?? [];
  const events = buildPreview?.recent_events ?? [];
  const roundedProgress = Math.max(0, Math.min(100, Math.round(progress)));

  const draftExcerpt = buildPreview?.draft_excerpt?.trim() ?? "";
  const planSummary = buildPreview?.plan_summary?.trim() ?? "";

  const spotlightChapter = chapters.find((c) =>
    ["generating", "enhancing", "reviewing", "drafting", "researching"].includes(c.status)
  ) ?? chapters.find(c => c.status !== "pending") ?? null;

  // Auto-switch to preview and select active chapter when streaming starts
  useEffect(() => {
    if (draftExcerpt) {
      if (activeTab === "outline" || activeTab === "logs" || activeTab === "files") {
        setActiveTab("preview");
      }
      if (spotlightChapter && selectedPreviewChapter !== spotlightChapter.chapter_index) {
        setSelectedPreviewChapter(spotlightChapter.chapter_index);
      }
    }
  }, [draftExcerpt, spotlightChapter]);

  // Ensure selected chapter in preview defaults to spotlight or first chapter
  useEffect(() => {
    if (activeTab === "preview" && selectedPreviewChapter === null && chapters.length > 0) {
      setSelectedPreviewChapter(spotlightChapter?.chapter_index ?? chapters[0].chapter_index);
    }
  }, [activeTab, chapters, spotlightChapter]);

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
             <div className="mt-4">
               <span className="inline-block text-[10.5px] font-mono text-zinc-500 bg-zinc-200/40 rounded px-2 py-1 leading-none">
                 {buildPreview.mode_reason.trim()}
               </span>
             </div>
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
                       "absolute left-[-9px] top-[1px] w-4 h-4 rounded-full border bg-[#FAFAFA] flex items-center justify-center transition-colors",
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
            {activeTab === "files" && (
              <motion.div
                key="files"
                initial={{ opacity: 0 }}
                animate={{ opacity: 1 }}
                exit={{ opacity: 0 }}
                transition={{ duration: 0.15 }}
                className="absolute inset-0 overflow-y-auto px-10 py-8 scrollbar-thin scrollbar-webkit"
              >
                <div className="max-w-4xl">
                  <h3 className="text-[14px] font-semibold text-black mb-5 tracking-tight flex items-center gap-2">
                    本地文献提取结果
                    <span className="font-normal text-[12px] text-zinc-500 bg-zinc-100 px-2 py-0.5 rounded">{sourceFiles.length} 份</span>
                  </h3>
                  
                  {sourceFiles.length === 0 ? (
                    <div className="text-[13px] text-zinc-400 py-10 flex flex-col items-center gap-2">
                      <FileSearch className="w-8 h-8 text-zinc-200" />
                      当前没有引入本地文件。
                    </div>
                  ) : (
                    <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                      {sourceFiles.map((file) => {
                         const hasError = Boolean(file.error_message?.trim());
                         const isDone = Boolean(file.markdown_ready);
                         const label = resolveFileProcessingLabel(file);
                         
                         return (
                           <div key={file.uid} className="group relative border border-[#E5E7EB] rounded-lg p-4 hover:border-zinc-300 hover:shadow-sm transition-all bg-white cursor-pointer overflow-hidden">
                             <div className="flex items-start gap-4">
                               <div className={cn(
                                 "w-10 h-10 rounded-md border flex items-center justify-center shrink-0",
                                 hasError ? "bg-red-50 border-red-100 text-red-500" : isDone ? "bg-emerald-50 border-emerald-100 text-emerald-500" : "bg-zinc-50 border-zinc-100 text-zinc-400"
                               )}>
                                  {isDone ? <CheckCircle2 className="w-5 h-5" /> : <FileText className="w-5 h-5" />}
                               </div>
                               <div className="flex-1 min-w-0">
                                 <h4 className="text-[13px] font-medium text-zinc-900 truncate mb-1 pr-6" title={file.filename}>{file.filename}</h4>
                                 <p className={cn("text-[11px]", hasError ? "text-red-500" : "text-zinc-500")}>
                                   {hasError ? file.error_message : label}
                                 </p>
                               </div>
                               
                               <div className="absolute right-4 top-4 opacity-0 group-hover:opacity-100 transition-opacity">
                                  <div className="text-[11px] text-blue-600 bg-blue-50 px-2 py-0.5 rounded border border-blue-100 font-medium">查看解析</div>
                               </div>
                             </div>
                           </div>
                         );
                      })}
                    </div>
                  )}
                </div>
              </motion.div>
            )}

            {activeTab === "logs" && (
              <motion.div
                key="logs"
                initial={{ opacity: 0 }}
                animate={{ opacity: 1 }}
                exit={{ opacity: 0 }}
                transition={{ duration: 0.15 }}
                className="absolute inset-0 overflow-y-auto px-10 py-8 scrollbar-thin scrollbar-webkit"
              >
                <div className="max-w-4xl">
                  {/* Event stream flat style */}
                  <div className="flex items-center justify-between mb-5">
                    <h3 className="text-[14px] font-semibold text-black tracking-tight flex items-center gap-2">
                       构建网络源与系统事件
                       <span className="font-normal text-[12px] text-zinc-500 bg-zinc-100 px-2 py-0.5 rounded">{events.length} 条</span>
                    </h3>
                  </div>
                  
                  <div className="border border-[#E5E7EB] rounded-lg bg-[#FAFAFA] p-5 mb-8">
                     <BuildResearchSources events={events} className="!border-0 !p-0 !bg-transparent !shadow-none !rounded-none" />
                  </div>

                  <div className="space-y-0">
                     {events.map((event, index) => {
                       const stageLabel = EVENT_STAGE_LABELS[(event.stage ?? "").trim()] ?? (event.stage?.trim() || "事件");
                       return (
                         <div key={index} className="flex gap-6 py-4 border-b border-[#F3F4F6] last:border-0 hover:bg-[#FAFAFA] transition-colors -mx-4 px-4 rounded-lg">
                           <div className="flex flex-col gap-0.5 w-[110px] flex-shrink-0">
                             <span className="text-[12px] font-medium text-zinc-700">{stageLabel}</span>
                             <span className="text-[11px] text-zinc-400">{event.created_at ? formatBuildEventTime(event.created_at) : ""}</span>
                           </div>
                           <p className="text-[12.5px] text-zinc-600 leading-relaxed">
                             {event.summary}
                           </p>
                         </div>
                       );
                     })}
                     {events.length === 0 && (
                        <div className="text-[12px] text-center text-zinc-400 py-10 bg-[#FAFAFA] border border-[#E5E7EB] rounded-lg">系统尚未产生构建日志...</div>
                     )}
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
                <div className="max-w-4xl space-y-12">
                  <div>
                     <h3 className="text-[14px] font-semibold text-zinc-900 tracking-tight mb-4">摘要与框架思路</h3>
                     <p className="text-[13px] leading-relaxed text-zinc-600 border-l-[3px] border-blue-500 pl-4 bg-blue-50/30 py-2">
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
                              "flex flex-col py-3 px-2 border-b transition-all duration-200",
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
                className="absolute inset-0 flex h-full"
              >
                {/* Left Sub-Tab: Chapter List */}
                <div className="w-[280px] flex-shrink-0 border-r border-[#E5E7EB] bg-white flex flex-col h-full">
                  <div className="p-4 border-b border-[#E5E7EB]">
                     <h3 className="text-[13px] font-medium text-zinc-800 flex items-center gap-2">
                       <Code2 className="w-4 h-4 text-zinc-400" /> 在线生成流 ({chapters.length})
                     </h3>
                  </div>
                  <div className="flex-1 overflow-y-auto p-3 space-y-1 scrollbar-thin scrollbar-webkit">
                     {chapters.map(chapter => {
                        const isSelected = selectedPreviewChapter === chapter.chapter_index;
                        const isStreaming = spotlightChapter?.chapter_index === chapter.chapter_index;
                        const isDone = ["generated", "completed", "enhanced", "reviewed"].includes(chapter.status);
                        
                        return (
                          <button
                            key={chapter.chapter_index}
                            onClick={() => setSelectedPreviewChapter(chapter.chapter_index)}
                            className={cn(
                              "w-full text-left px-3 py-2.5 rounded-lg text-[12px] transition-colors flex items-start gap-3",
                              isSelected ? "bg-zinc-50/80 font-medium" : "hover:bg-zinc-50 border border-transparent text-zinc-600"
                            )}
                          >
                             <div className="mt-0.5 relative flex items-center justify-center shrink-0 w-3 h-3">
                                {isStreaming ? (
                                   <>
                                     <span className="animate-ping absolute inline-flex h-full w-full rounded-full bg-blue-400 opacity-75"></span>
                                     <span className="relative inline-flex rounded-full h-1.5 w-1.5 bg-blue-500"></span>
                                   </>
                                ) : isDone ? (
                                   <div className="w-1.5 h-1.5 rounded-full bg-emerald-400" />
                                ) : (
                                   <div className="w-1.5 h-1.5 rounded-full bg-zinc-300" />
                                )}
                             </div>
                             <div className="flex-1 pr-2">
                               <div className="line-clamp-2">
                                 {String(chapter.chapter_index).padStart(2, '0')}. {chapter.title}
                               </div>
                             </div>
                          </button>
                        );
                     })}
                     {chapters.length === 0 && (
                        <div className="text-[12px] text-zinc-400 text-center py-10">大纲未就绪</div>
                     )}
                  </div>
                </div>

                {/* Right Area: SSE Preview */}
                <div className="flex-1 min-w-0 flex flex-col h-full bg-white relative">
                   {selectedPreviewChapter ? (() => {
                      const selChapter = chapters.find(c => c.chapter_index === selectedPreviewChapter);
                      const isStreaming = spotlightChapter?.chapter_index === selectedPreviewChapter;
                      const isDone = selChapter ? ["generated", "completed", "enhanced", "reviewed"].includes(selChapter.status) : false;

                      return (
                         <>
                           <div className="flex items-center justify-between px-8 py-3 border-b border-[#E5E7EB]">
                              <span className="text-[12px] font-medium text-zinc-600">
                                {isStreaming ? "正在实时推流..." : isDone ? "生成已完成" : "等待生成..."}
                              </span>
                           </div>
                           <div className="flex-1 overflow-y-auto px-10 py-10 scrollbar-thin scrollbar-webkit bg-white">
                              {isStreaming && draftExcerpt ? (
                                 <div className="max-w-[700px] mx-auto pb-10">
                                   <pre
                                     className="whitespace-pre-wrap text-[14px] leading-[1.8] text-zinc-800 break-words"
                                     style={{ fontFamily: 'var(--font-serif)' }}
                                   >
                                     {draftExcerpt}
                                     <motion.span className="ml-[2px] inline-block h-[15px] w-[2px] animate-blink bg-blue-500 align-middle" />
                                   </pre>
                                 </div>
                              ) : isDone ? (
                                 <div className="h-full flex flex-col items-center justify-center text-zinc-400 space-y-4">
                                    <CheckCircle2 className="w-8 h-8 text-emerald-300" strokeWidth={1.5} />
                                    <p className="text-[13px] text-zinc-500">此章已生成，等待最终合并...</p>
                                 </div>
                              ) : (
                                 <div className="h-full flex flex-col items-center justify-center text-zinc-400 space-y-4">
                                    <Loader2 className="w-8 h-8 text-zinc-200 animate-spin" strokeWidth={1.5} />
                                    <p className="text-[13px] text-zinc-500">排列中，等待系统推进到此章...</p>
                                 </div>
                              )}
                           </div>
                         </>
                      )
                   })() : (
                      <div className="h-full flex flex-col items-center justify-center text-zinc-300 gap-3">
                         <PlayCircle className="w-8 h-8 text-zinc-200" strokeWidth={1.5} />
                         <span className="text-[12px]">选择左侧章节查看流</span>
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
