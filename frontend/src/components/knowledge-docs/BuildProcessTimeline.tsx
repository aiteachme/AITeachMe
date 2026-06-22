/* ------------------------------------------------------------------ */
/*  BuildProcessTimeline — DocGen workspace phase rail                 */
/* ------------------------------------------------------------------ */

import { useMemo } from "react";
import { motion } from "framer-motion";
import { Check, Loader2 } from "lucide-react";

import { cn } from "../../lib/utils";
import type { BuildProcessStep, ProcessStepState } from "./types";

interface Props {
  steps: BuildProcessStep[];
  className?: string;
}

export function BuildProcessTimeline({ steps, className }: Props) {
  return (
    <div className={cn("relative", className)}>
      <div className="absolute bottom-3 left-[11px] top-3 w-px bg-zinc-200 dark:bg-slate-800" />

        <div className="space-y-1.5">
          {steps.map((step, index) => {
            const isActive = step.state === "active";
            const isDone = step.state === "done";

            return (
              <motion.div
                key={step.key}
                initial={{ opacity: 0, x: -8 }}
                animate={{ opacity: 1, x: 0 }}
                transition={{ delay: index * 0.05, duration: 0.26, ease: "easeOut" }}
                className={cn(
                  "relative flex items-start gap-3 rounded-lg px-2 py-2.5 transition-colors leading-[1.2]",
                  isActive ? "bg-blue-50/60 dark:bg-blue-500/10" : "hover:bg-zinc-50/80 dark:hover:bg-slate-800/50",
                )}
              >
                <div className="relative z-10 mt-0.5 shrink-0">
                  {isDone ? (
                    <div className="flex h-5 w-5 items-center justify-center rounded-full border border-emerald-200 bg-emerald-100 text-emerald-500 dark:border-emerald-500/30 dark:bg-emerald-500/10 dark:text-emerald-300">
                      <Check className="h-3 w-3" strokeWidth={3} />
                    </div>
                  ) : isActive ? (
                    <div className="relative">
                      <div className="flex h-5 w-5 items-center justify-center rounded-full border border-blue-200 bg-blue-100 text-blue-600 dark:border-blue-500/30 dark:bg-blue-500/10 dark:text-blue-300">
                        <Loader2 className="h-3 w-3 animate-spin" strokeWidth={3} />
                      </div>
                    </div>
                  ) : (
                    <div className="h-5 w-5 rounded-full border border-zinc-200 bg-white dark:border-slate-700 dark:bg-slate-900" />
                  )}
                </div>

                <div className="min-w-0">
                  <div className="flex items-center gap-2">
                    <span className="text-[10px] font-medium text-zinc-300 dark:text-slate-600">{String(index + 1).padStart(2, "0")}</span>
                    <p
                      className={cn(
                        "text-[13px] leading-5 transition-colors",
                        isDone
                          ? "font-medium text-zinc-700 dark:text-slate-300"
                          : isActive
                            ? "font-semibold text-blue-700 dark:text-blue-300"
                            : "text-zinc-400 dark:text-slate-500",
                      )}
                    >
                      {step.title}
                    </p>
                  </div>
                  <p
                    className={cn(
                      "mt-1 text-[11px] leading-5",
                      isActive ? "text-blue-600 dark:text-blue-300" : isDone ? "text-zinc-400 dark:text-slate-500" : "text-zinc-300 dark:text-slate-600",
                    )}
                  >
                    {step.description}
                  </p>
                </div>
              </motion.div>
            );
          })}
        </div>
    </div>
  );
}

const TIMELINE_STEPS = [
  { key: "freeze_plan", title: "冻结方案", description: "确认章节边界、模式和本轮执行范围。" },
  { key: "understand_materials", title: "理解资料", description: "通读文件、判断重点并识别写作意图。" },
  { key: "build_backbone", title: "构建骨架", description: "先搭整本文档的概念骨架与章节合同。" },
  { key: "parallel_writing", title: "并行写作", description: "多章并行研究、成稿并做章节增强。" },
  { key: "review_loop", title: "复核回流", description: "检查覆盖、证据和一致性，记录修补动作。" },
  { key: "publish_merge", title: "合并发布", description: "整本收口、标题同步并发布正式文档。" },
];

const TIMELINE_STEPS_WITH_GRAPH = [
  ...TIMELINE_STEPS,
  { key: "sync_graph", title: "同步图谱", description: "同步知识点、语义索引和关系数据。" },
];

const STAGE_TO_STEP_INDEX: Record<string, number> = {
  build_accepted: 0,
  planner_confirmed: 0,
  load_context: 0,

  prepare_shared: 1,
  preparing_docgen_global_seed: 1,
  preparing_docgen_context: 1,
  prepare_parallel_inputs: 1,

  dispatch_ready: 2,
  backbone_seed_ready: 2,
  confirm_and_dispatch: 2,
  building_document_backbone: 2,
  build_document_backbone: 2,
  preparing_chapter_execution_briefs: 2,

  generating_chapters: 3,
  enhancing_chapters: 3,
  chapters_enhanced: 3,
  generate_chapters: 3,
  enhance_chapters: 3,

  reviewing_content: 4,
  content_reviewed: 4,
  repairing_or_routing: 4,
  repair_routed: 4,
  review_content: 4,
  repair_or_route: 4,

  merge_reviewed: 5,
  titles_finalized: 5,
  doc_lane_staged: 5,
  docgen_finalized: 5,
  publishing: 5,
  graph_pending: 6,
  manual_graph_requested: 6,
  queued_after_docgen: 6,
  graph_docs_sync: 6,
  graph_ready: 6,
  disabled: 6,
  completed: 6,
};

export function useBuildTimelineSteps(stage: string | null | undefined): BuildProcessStep[] {
  return useMemo(() => {
    const stageKey = (stage ?? "").trim() || "build_accepted";
    const activeStepIndex = STAGE_TO_STEP_INDEX[stageKey] ?? 0;
    const isCompleted = stageKey === "completed";

    return TIMELINE_STEPS_WITH_GRAPH.map((step, index) => {
      let state: ProcessStepState;
      if (isCompleted || index < activeStepIndex) {
        state = "done";
      } else if (index === activeStepIndex) {
        state = "active";
      } else {
        state = "pending";
      }

      return {
        ...step,
        state,
      };
    });
  }, [stage]);
}
