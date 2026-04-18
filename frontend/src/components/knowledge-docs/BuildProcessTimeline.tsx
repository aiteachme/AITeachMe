/* ------------------------------------------------------------------ */
/*  BuildProcessTimeline — Compact vertical timeline (Gemini-style)    */
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
      {/* Vertical line */}
      <div className="absolute left-[11px] top-3 bottom-3 w-[1.5px] bg-gradient-to-b from-stone-200 via-stone-200 to-transparent" />

      <div className="space-y-0.5">
        {steps.map((step, index) => (
          <motion.div
            key={step.key}
            initial={{ opacity: 0, x: -8 }}
            animate={{ opacity: 1, x: 0 }}
            transition={{ delay: index * 0.06, duration: 0.3, ease: "easeOut" }}
            className="relative flex items-start gap-2.5 py-1.5"
          >
            {/* Dot */}
            <div className="relative z-10 shrink-0 mt-[3px]">
              {step.state === "done" ? (
                <div className="w-[22px] h-[22px] rounded-full bg-emerald-500 flex items-center justify-center shadow-sm shadow-emerald-500/20">
                  <Check className="w-3 h-3 text-white" strokeWidth={3} />
                </div>
              ) : step.state === "active" ? (
                <div className="relative">
                  <div className="w-[22px] h-[22px] rounded-full bg-sky-500 flex items-center justify-center shadow-sm shadow-sky-500/25">
                    <Loader2 className="w-3 h-3 text-white animate-spin" strokeWidth={3} />
                  </div>
                  <motion.div
                    className="absolute -inset-1 rounded-full border border-sky-400/40"
                    animate={{ scale: [1, 1.4, 1], opacity: [0.6, 0, 0.6] }}
                    transition={{ duration: 2, repeat: Infinity }}
                  />
                </div>
              ) : (
                <div className="w-[22px] h-[22px] rounded-full border-[1.5px] border-stone-250 bg-stone-50" />
              )}
            </div>

            {/* Label */}
            <div className="min-w-0 pt-[1px]">
              <p className={cn(
                "text-[12px] leading-5 transition-colors",
                step.state === "done"
                  ? "text-stone-600 font-medium"
                  : step.state === "active"
                    ? "text-sky-700 font-semibold"
                    : "text-stone-400",
              )}>
                {step.title}
              </p>
              {step.state === "active" && (
                <p className="text-[10px] leading-4 text-sky-500/80 mt-0.5">{step.description}</p>
              )}
            </div>
          </motion.div>
        ))}
      </div>
    </div>
  );
}

/* ---- Helper to derive steps from build stage ---- */

const TIMELINE_STEPS = [
  { key: "prepare", title: "分析材料", description: "解析上传的课件与文档" },
  { key: "research", title: "深度检索", description: "对每个章节进行针对性检索" },
  { key: "draft", title: "知识成文", description: "生成结构化知识文档" },
  { key: "enrich", title: "富化增强", description: "添加图表、公式与案例" },
  { key: "publish", title: "发布文档", description: "验证质量并发布" },
];

const STAGE_TO_STEP_INDEX: Record<string, number> = {
  build_accepted: 0,
  planner_confirmed: 0,
  prepare_shared: 0,
  preparing_docgen_context: 1,
  dispatch_ready: 1,
  building_document_backbone: 1,
  generating_chapters: 2,
  enhancing_chapters: 3,
  chapters_enhanced: 3,
  reviewing_content: 4,
  content_reviewed: 4,
  repairing_or_routing: 4,
  repair_routed: 4,
  merge_reviewed: 4,
  titles_finalized: 4,
  doc_lane_staged: 4,
  docgen_finalized: 4,
  graph_ready: 4,
  publishing: 4,
  completed: 5,
};

export function useBuildTimelineSteps(stage: string | null | undefined): BuildProcessStep[] {
  return useMemo(() => {
    const stageKey = (stage ?? "").trim() || "build_accepted";
    const activeStepIndex = STAGE_TO_STEP_INDEX[stageKey] ?? 0;

    return TIMELINE_STEPS.map((step, index) => ({
      ...step,
      state: (index < activeStepIndex ? "done" : index === activeStepIndex ? "active" : "pending") as ProcessStepState,
    }));
  }, [stage]);
}
