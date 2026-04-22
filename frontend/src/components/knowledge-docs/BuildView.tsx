import { useEffect, useRef, useState } from "react";
import { motion, AnimatePresence } from "framer-motion";
import { Check, CheckCircle2, FileText, Loader2, Activity, PlayCircle, FileSearch, Code2 } from "lucide-react";

import { cn } from "../../lib/utils";
import type { FileRecord } from "../../api/generated/model";
import type {
  KnowledgeBuildMetrics,
  KnowledgeBuildPreview,
} from "./types";
import { useBuildTimelineSteps } from "./BuildProcessTimeline";
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
  buildStage,
  className,
}: Props) {
  const [activeTab, setActiveTab] = useState<string>("preview");
  const [selectedPreviewChapter, setSelectedPreviewChapter] = useState<number | null>(null);
  const previewFallbackAppliedRef = useRef(false);

  const timelineSteps = useBuildTimelineSteps(buildStage);
  const chapters = buildPreview?.chapter_progress ?? [];
  const events = buildPreview?.recent_events ?? [];
  const roundedProgress = Math.max(0, Math.min(100, Math.round(progress)));

  const draftExcerpt = buildPreview?.draft_excerpt?.trim() ?? "";
  const planSummary = buildPreview?.plan_summary?.trim() ?? "";
  const hasDraftExcerpt = draftExcerpt.length > 0;

  const spotlightChapter = chapters.find((c) =>
    ["generating", "enhancing", "reviewing", "drafting", "researching"].includes(c.status)
  ) ?? chapters.find(c => c.status !== "pending") ?? null;

  // Auto-switch to preview and select active chapter when streaming starts
  useEffect(() => {
    if (hasDraftExcerpt) {
      if (activeTab === "outline" || activeTab === "logs" || activeTab === "files") {
        setActiveTab("preview");
      }
      if (spotlightChapter && selectedPreviewChapter !== spotlightChapter.chapter_index) {
        setSelectedPreviewChapter(spotlightChapter.chapter_index);
      }
    }
  }, [activeTab, hasDraftExcerpt, selectedPreviewChapter, spotlightChapter]);

  useEffect(() => {
    if (hasDraftExcerpt) {
      previewFallbackAppliedRef.current = false;
      return;
    }
    if (activeTab !== "preview" || previewFallbackAppliedRef.current) {
      return;
    }
    if (events.length > 0) {
      previewFallbackAppliedRef.current = true;
      setActiveTab("logs");
      return;
    }
    if (chapters.length > 0) {
      previewFallbackAppliedRef.current = true;
      setActiveTab("outline");
      return;
    }
    if (sourceFiles.length > 0) {
      previewFallbackAppliedRef.current = true;
      setActiveTab("files");
    }
  }, [activeTab, chapters.length, events.length, hasDraftExcerpt, sourceFiles.length]);

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
        "w-full h-full flex flex-col lg:flex-row bg-white overflow-hidden",
        className
      )}
    >
      {/* -------------------------------------------------------- */}
      {/* LEFT COLUMN: Progress & Timeline                         */}
      {/* -------------------------------------------------------- */}
      <div className="flex-shrink-0 w-full lg:w-[260px] flex flex-col border-r border-zinc-100 bg-white">
        {/* Progress Header */}
        <div className="px-6 pt-7 pb-5">
          <div className="flex items-start justify-between mb-4">
            <div className="flex-1 min-w-0 pr-3">
              <h2 className="text-[13px] font-semibold text-zinc-900 leading-snug flex items-center gap-1.5">
                {isFetching && <Loader2 className="w-3.5 h-3.5 animate-spin text-zinc-400 shrink-0" />}
                <span className="line-clamp-2">{statusText || "任务初始化..."}</span>
              </h2>
            </div>
            <span className={cn(
              "text-[12px] font-semibold tabular-nums px-2.5 py-1 rounded-md shrink-0",
              roundedProgress === 100
                ? "bg-emerald-50 text-emerald-600"
                : "bg-blue-50 text-blue-600"
            )}>
              {roundedProgress}%
            </span>
          </div>
          <div className="h-1 w-full bg-zinc-100 rounded-full overflow-hidden">
             <motion.div
                className={cn(
                  "h-full rounded-full",
                  roundedProgress === 100 ? "bg-emerald-500" : "bg-blue-500"
                )}
                initial={{width:0}}
                animate={{width:`${roundedProgress}%`}}
                transition={{ duration: 0.5 }}
             />
          </div>
          {buildPreview?.mode_reason?.trim() ? (
             <div className="mt-3">
               <span className="inline-block text-[10.5px] font-mono text-zinc-400 leading-none">
                 {buildPreview.mode_reason.trim()}
               </span>
             </div>
          ) : null}
        </div>

        {/* Divider */}
        <div className="mx-6 border-t border-zinc-100" />

        {/* Minimal Timeline Rail */}
        <div className="flex-1 overflow-y-auto px-6 py-5 build-scroll">
           <h3 className="text-[10px] font-semibold text-zinc-300 uppercase tracking-widest mb-5">Phase Flow</h3>
           <div className="relative border-l border-zinc-200/60 ml-[7px] space-y-6">
             {timelineSteps.map((step, idx) => {
                const isDone = step.state === "done";
                const isActive = step.state === "active";
                return (
                  <div key={step.key} className="relative pl-6">
                     {/* Node Dot */}
                     <div className={cn(
                       "absolute left-[-9px] top-[1px] w-4 h-4 rounded-full border bg-white flex items-center justify-center transition-colors",
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
                         <span className="text-[10px] font-mono opacity-50">0{idx + 1}</span>
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
      {/* RIGHT COLUMN: Tab Canvas                                 */}
      {/* -------------------------------------------------------- */}
      <div className="flex-1 min-w-0 flex flex-col relative bg-white">
        {/* Navigation Tabs */}
        <div className="h-12 flex items-end px-8 gap-8 border-b border-zinc-100">
          {TABS.map((tab) => {
            const isActive = activeTab === tab.id;
            return (
              <button
                key={tab.id}
                onClick={() => setActiveTab(tab.id)}
                className={cn(
                  "relative pb-3 text-[13.5px] transition-colors outline-none",
                  isActive ? "text-zinc-900 font-semibold" : "text-zinc-400 hover:text-zinc-700 font-medium"
                )}
              >
                {isActive && (
                  <motion.div
                    layoutId="build-tab-indicator"
                    className="absolute bottom-0 left-0 right-0 h-[2px] bg-zinc-900 rounded-full"
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
                className="absolute inset-0 overflow-y-auto px-10 py-8 build-scroll"
              >
                <div className="w-full max-w-[860px]">
                  <h3 className="text-[14px] font-semibold text-zinc-900 mb-5 tracking-tight flex items-center gap-2">
                    本地文献提取结果
                    <span className="font-normal text-[12px] text-zinc-400 bg-zinc-50 px-2 py-0.5 rounded">{sourceFiles.length} 份</span>
                  </h3>

                  {sourceFiles.length === 0 ? (
                    <div className="text-[13px] text-zinc-400 py-16 flex flex-col items-center gap-3">
                      <FileSearch className="w-10 h-10 text-zinc-200" />
                      当前没有引入本地文件。
                    </div>
                  ) : (
                    <div className="flex flex-col">
                      {sourceFiles.map((file) => {
                         const hasError = Boolean(file.error_message?.trim());
                         const isDone = Boolean(file.markdown_ready);
                         const label = resolveFileProcessingLabel(file);

                         return (
                           <div key={file.uid} className="group relative border-b border-zinc-50 py-4 hover:bg-zinc-50/50 transition-colors cursor-pointer -mx-3 px-3 rounded-lg">
                             <div className="flex items-start gap-4">
                               <div className={cn(
                                 "w-9 h-9 rounded-lg flex items-center justify-center shrink-0",
                                 hasError ? "bg-red-50 text-red-500" : isDone ? "bg-emerald-50 text-emerald-500" : "bg-zinc-50 text-zinc-400"
                               )}>
                                  {isDone ? <CheckCircle2 className="w-5 h-5" /> : <FileText className="w-5 h-5" />}
                               </div>
                               <div className="flex-1 min-w-0">
                                 <h4 className="text-[13px] font-medium text-zinc-900 truncate mb-1 pr-6" title={file.filename}>{file.filename}</h4>
                                 <p className={cn("text-[11px]", hasError ? "text-red-500" : "text-zinc-400")}>
                                   {hasError ? file.error_message : label}
                                 </p>
                               </div>

                               <div className="absolute right-3 top-4 opacity-0 group-hover:opacity-100 transition-opacity">
                                  <div className="text-[11px] text-blue-600 bg-blue-50 px-2 py-0.5 rounded-md font-medium">查看解析</div>
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
                className="absolute inset-0 overflow-y-auto px-10 py-8 build-scroll"
              >
                <div className="w-full max-w-[960px]">
                  <div className="flex items-center justify-between mb-5">
                    <h3 className="text-[14px] font-semibold text-zinc-900 tracking-tight flex items-center gap-2">
                       系统构建日志
                       <span className="font-mono font-normal text-[11px] text-zinc-400 bg-zinc-50 px-2 py-0.5 rounded">{events.length}</span>
                    </h3>
                  </div>

                  {/* Log entries — direct on white, no extra card wrapper */}
                  <div className="font-mono text-[12px] space-y-0.5">
                     {events.map((event, index) => {
                       const stageLabel = EVENT_STAGE_LABELS[(event.stage ?? "").trim()] ?? (event.stage?.trim() || "EVENT");
                       return (
                         <div key={`${event.stage}-${index}`} className="flex gap-3 hover:bg-zinc-50/80 px-3 py-2 rounded-lg transition-colors group">
                           <span className="text-zinc-300 shrink-0 select-none w-12 tabular-nums">{event.created_at ? formatBuildEventTime(event.created_at) : ""}</span>
                           <span className="text-blue-500 font-medium shrink-0 w-[90px] truncate select-none">[{stageLabel}]</span>
                           <span className="text-zinc-700 whitespace-pre-wrap flex-1 leading-relaxed">{event.summary}</span>
                         </div>
                       );
                     })}
                     {events.length === 0 && (
                        <div className="text-zinc-300 italic py-8 px-3 text-center animate-pulse text-[13px]">Waiting for system events...</div>
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
                className="absolute inset-0 overflow-y-auto px-10 py-8 build-scroll"
              >
                <div className="w-full max-w-[960px] space-y-10">
                  <div>
                     <h3 className="text-[14px] font-semibold text-zinc-900 tracking-tight mb-4">摘要与框架思路</h3>
                     <p className="text-[13px] leading-[1.8] text-zinc-600 border-l-2 border-zinc-200 pl-4 py-1">
                       {planSummary || "系统正在理解资料范围与章节边界..."}
                     </p>
                  </div>

                  <div>
                    <h3 className="text-[14px] font-semibold text-zinc-900 tracking-tight mb-5 flex items-center justify-between">
                       生成的章节大纲
                       <span className="text-zinc-400 font-normal text-[12px] bg-zinc-50 px-2 py-0.5 rounded">总体 {chapters.length} 节</span>
                    </h3>

                    {chapters.length > 0 ? (
                      <div className="grid grid-cols-1 md:grid-cols-2 gap-x-8 gap-y-1">
                        {chapters.map((chapter) => {
                          const isDone = ["generated", "completed", "enhanced", "reviewed"].includes(chapter.status);
                          const isActive = ["generating", "drafting", "enhancing"].includes(chapter.status);

                          return (
                            <div key={chapter.chapter_index} className={cn(
                              "flex flex-col py-3.5 px-3 border-b transition-all duration-200 rounded-md",
                              isActive
                                ? "border-blue-200 bg-blue-50/30"
                                : "border-zinc-50 hover:bg-zinc-50/50"
                            )}>
                               <div className="flex items-start gap-3">
                                  <span className="font-mono text-zinc-300 text-[11px] mt-[3px]">
                                    {String(chapter.chapter_index).padStart(2, "0")}
                                  </span>
                                  <div className="flex-1">
                                    <h4 className={cn(
                                      "text-[13px] font-medium leading-relaxed",
                                      isActive ? "text-zinc-900" : isDone ? "text-zinc-800" : "text-zinc-400"
                                    )}>{chapter.title}</h4>
                                    <p className="text-[11px] text-zinc-400 flex items-center gap-1.5 mt-1">
                                      {isActive && <Activity className="w-3 h-3 text-blue-500 animate-pulse" />}
                                      {buildChapterStatusLabel(chapter.status)}
                                    </p>
                                  </div>
                               </div>
                            </div>
                          );
                        })}
                      </div>
                    ) : (
                      <div className="text-[13px] text-zinc-300 text-center py-16">
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
                <div className="w-[240px] flex-shrink-0 border-r border-zinc-100 bg-white flex flex-col h-full">
                  <div className="px-4 py-3.5 border-b border-zinc-50">
                     <h3 className="text-[12px] font-medium text-zinc-500 flex items-center gap-2">
                       <Code2 className="w-3.5 h-3.5 text-zinc-300" /> 在线生成流 ({chapters.length})
                     </h3>
                  </div>
                  <div className="flex-1 overflow-y-auto p-2.5 space-y-0.5 build-scroll">
                     {chapters.map(chapter => {
                        const isSelected = selectedPreviewChapter === chapter.chapter_index;
                        const isStreaming = spotlightChapter?.chapter_index === chapter.chapter_index;
                        const isDone = ["generated", "completed", "enhanced", "reviewed"].includes(chapter.status);

                        return (
                          <button
                            key={chapter.chapter_index}
                            onClick={() => setSelectedPreviewChapter(chapter.chapter_index)}
                            className={cn(
                              "w-full text-left px-3 py-2.5 rounded-lg text-[12px] transition-all flex items-start gap-2.5",
                              isSelected
                                ? "bg-zinc-900 text-white font-medium shadow-sm"
                                : "text-zinc-600 hover:bg-zinc-50"
                            )}
                          >
                             <div className="mt-1 relative flex items-center justify-center shrink-0 w-3 h-3">
                                {isStreaming ? (
                                   <>
                                     <span className={cn("animate-ping absolute inline-flex h-full w-full rounded-full opacity-75", isSelected ? "bg-blue-300" : "bg-blue-400")}></span>
                                     <span className={cn("relative inline-flex rounded-full h-1.5 w-1.5", isSelected ? "bg-blue-300" : "bg-blue-500")}></span>
                                   </>
                                ) : isDone ? (
                                   <div className={cn("w-1.5 h-1.5 rounded-full", isSelected ? "bg-emerald-300" : "bg-emerald-400")} />
                                ) : (
                                   <div className={cn("w-1.5 h-1.5 rounded-full", isSelected ? "bg-zinc-400" : "bg-zinc-300")} />
                                )}
                             </div>
                             <div className="flex-1 pr-1">
                               <div className="line-clamp-2 leading-snug">
                                 {String(chapter.chapter_index).padStart(2, '0')}. {chapter.title}
                               </div>
                             </div>
                          </button>
                        );
                     })}
                     {chapters.length === 0 && (
                        <div className="text-[12px] text-zinc-300 text-center py-12">大纲未就绪</div>
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
                           <div className="flex items-center justify-between px-8 py-3 border-b border-zinc-50">
                              <span className="text-[12px] font-medium text-zinc-400">
                                {isStreaming ? "正在实时推流..." : isDone ? "生成已完成" : "等待生成..."}
                              </span>
                              {isStreaming && (
                                <div className="flex items-center gap-2">
                                  <span className="relative flex h-2 w-2">
                                    <span className="animate-ping absolute inline-flex h-full w-full rounded-full bg-blue-400 opacity-75"></span>
                                    <span className="relative inline-flex rounded-full h-2 w-2 bg-blue-500"></span>
                                  </span>
                                  <span className="text-[11px] text-blue-500 font-medium">LIVE</span>
                                </div>
                              )}
                           </div>
                           <div className="flex-1 overflow-y-auto px-10 py-10 build-scroll bg-white">
                              {isStreaming && hasDraftExcerpt ? (
                                 <div className="max-w-[700px] mx-auto pb-10">
                                   <pre
                                     className="whitespace-pre-wrap text-[14px] leading-[1.85] text-zinc-800 break-words"
                                     style={{ fontFamily: 'var(--font-serif)' }}
                                   >
                                     {draftExcerpt}
                                     <motion.span className="ml-[2px] inline-block h-[15px] w-[2px] animate-blink bg-blue-500 align-middle" />
                                   </pre>
                                 </div>
                              ) : isDone ? (
                                 <div className="h-full flex flex-col items-center justify-center text-zinc-400 space-y-3">
                                    <CheckCircle2 className="w-10 h-10 text-emerald-200" strokeWidth={1.5} />
                                    <p className="text-[13px] text-zinc-400">此章已生成，等待最终合并...</p>
                                 </div>
                              ) : (
                                 <div className="h-full flex flex-col items-center justify-center text-zinc-400 space-y-3">
                                    <Loader2 className="w-10 h-10 text-zinc-200 animate-spin" strokeWidth={1.5} />
                                    <p className="text-[13px] text-zinc-400">排列中，等待系统推进到此章...</p>
                                 </div>
                              )}
                           </div>
                         </>
                      )
                   })() : (
                      <div className="h-full flex flex-col items-center justify-center text-zinc-300 gap-3">
                         <PlayCircle className="w-10 h-10 text-zinc-200" strokeWidth={1.5} />
                         <span className="text-[12px]">选择左侧章节查看流</span>
                      </div>
                   )}
                </div>
              </motion.div>
            )}
          </AnimatePresence>
        </div>
      </div>
    </motion.div>
  );
}
