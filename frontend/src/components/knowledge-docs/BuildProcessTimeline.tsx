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
    <section
      className={cn(
        "overflow-hidden rounded-[28px] border border-stone-200/80 bg-white/90 p-4 shadow-[0_20px_60px_-48px_rgba(28,25,23,0.35)] backdrop-blur-sm md:p-5",
        className,
      )}
    >
      <div className="flex items-center justify-between gap-3 border-b border-stone-200/70 pb-3">
        <div>
          <p className="text-[11px] font-semibold uppercase tracking-[0.24em] text-stone-400">Build Rail</p>
          <h3 className="mt-1 text-sm font-semibold text-stone-900">构建阶段</h3>
        </div>
        <span className="rounded-full border border-stone-200 bg-stone-50 px-2.5 py-1 text-[11px] text-stone-500">
          {steps.filter((step) => step.state === "done").length}/{steps.length}
        </span>
      </div>

      <div className="relative mt-4">
        <div className="absolute bottom-3 left-[11px] top-3 w-px bg-gradient-to-b from-stone-200 via-stone-200 to-transparent" />

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
                  "relative flex items-start gap-3 rounded-2xl px-2 py-2.5 transition-colors",
                  isActive ? "bg-sky-50/70" : "hover:bg-stone-50/80",
                )}
              >
                <div className="relative z-10 mt-0.5 shrink-0">
                  {isDone ? (
                    <div className="flex h-[22px] w-[22px] items-center justify-center rounded-full bg-emerald-500 shadow-sm shadow-emerald-500/20">
                      <Check className="h-3 w-3 text-white" strokeWidth={3} />
                    </div>
                  ) : isActive ? (
                    <div className="relative">
                      <div className="flex h-[22px] w-[22px] items-center justify-center rounded-full bg-sky-500 shadow-sm shadow-sky-500/30">
                        <Loader2 className="h-3 w-3 animate-spin text-white" strokeWidth={3} />
                      </div>
                      <motion.div
                        className="absolute -inset-1 rounded-full border border-sky-400/40"
                        animate={{ scale: [1, 1.38, 1], opacity: [0.65, 0, 0.65] }}
                        transition={{ duration: 2, repeat: Infinity, ease: "easeInOut" }}
                      />
                    </div>
                  ) : (
                    <div className="h-[22px] w-[22px] rounded-full border border-stone-200 bg-stone-50" />
                  )}
                </div>

                <div className="min-w-0">
                  <div className="flex items-center gap-2">
                    <span className="text-[10px] font-medium text-stone-300">{String(index + 1).padStart(2, "0")}</span>
                    <p
                      className={cn(
                        "text-[13px] leading-5 transition-colors",
                        isDone
                          ? "font-medium text-stone-700"
                          : isActive
                            ? "font-semibold text-sky-800"
                            : "text-stone-400",
                      )}
                    >
                      {step.title}
                    </p>
                  </div>
                  <p
                    className={cn(
                      "mt-1 text-[11px] leading-5",
                      isActive ? "text-sky-600" : isDone ? "text-stone-500" : "text-stone-400",
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
    </section>
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

const STAGE_TO_STEP_INDEX: Record<string, number> = {
  build_accepted: 0,
  planner_confirmed: 0,
  load_context: 0,

  prepare_shared: 1,
  preparing_docgen_context: 1,
  prepare_parallel_inputs: 1,

  dispatch_ready: 2,
  confirm_and_dispatch: 2,
  building_document_backbone: 2,
  build_document_backbone: 2,

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
  graph_ready: 5,
  publishing: 5,
  completed: 5,
};

export function useBuildTimelineSteps(stage: string | null | undefined): BuildProcessStep[] {
  return useMemo(() => {
    const stageKey = (stage ?? "").trim() || "build_accepted";
    const activeStepIndex = STAGE_TO_STEP_INDEX[stageKey] ?? 0;
    const isCompleted = stageKey === "completed";

    return TIMELINE_STEPS.map((step, index) => {
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
