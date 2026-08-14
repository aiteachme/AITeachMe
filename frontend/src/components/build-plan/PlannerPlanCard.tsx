import type { ReactNode } from "react";
import { BookOpen, RefreshCw } from "lucide-react";

import { PlannerPreviewMarkdown } from "./PlannerPreviewMarkdown";

export const PLANNER_CARD_CLASSNAME =
  "rounded-md border border-zinc-200/80 bg-white px-5 py-5 shadow-[0_1px_2px_rgba(15,23,42,0.04)] dark:border-slate-800 dark:bg-slate-950";

export interface PlannerPlanOutlineItem {
  title: string;
  description?: string;
  tooltip?: string;
}

export function PlannerPlanCardShell({
  courseName,
  stageDescription,
  stageBadge,
  children,
}: {
  courseName: string;
  stageDescription: string;
  stageBadge: ReactNode;
  children: ReactNode;
}) {
  return (
    <article className={PLANNER_CARD_CLASSNAME}>
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div className="flex min-w-0 items-center gap-2">
          <span className="flex h-8 w-8 shrink-0 items-center justify-center rounded-md bg-zinc-950 text-white dark:bg-slate-100 dark:text-slate-950">
            <BookOpen className="h-4 w-4" />
          </span>
          <div className="min-w-0">
            <div className="truncate text-sm font-semibold text-zinc-950 dark:text-slate-100">
              {courseName || "课程方案"}
            </div>
            <div className="truncate text-xs leading-5 text-zinc-500 dark:text-slate-400">
              {stageDescription}
            </div>
          </div>
        </div>
        {stageBadge}
      </div>
      {children}
    </article>
  );
}

export function PlannerPlanSummary({
  introText,
  introMarkdown = false,
  adjustmentQuestions = [],
  outlineItems = [],
  showIntro = true,
}: {
  introText: string;
  introMarkdown?: boolean;
  adjustmentQuestions?: string[];
  outlineItems?: PlannerPlanOutlineItem[];
  showIntro?: boolean;
}) {
  return (
    <>
      {showIntro ? (
        <div className="mt-4">
          {introText ? (
            introMarkdown ? (
              <div className="planner-stream-preview text-[16px] font-medium leading-7 text-zinc-950 dark:text-slate-100">
                <PlannerPreviewMarkdown markdown={introText} />
              </div>
            ) : (
              <p className="text-[16px] font-medium leading-7 text-zinc-950 dark:text-slate-100">
                {introText}
              </p>
            )
          ) : (
            <p className="text-[16px] font-medium leading-7 text-zinc-950 dark:text-slate-100">
              我会先整理资料主线，再生成一份可继续调整的初步大纲。
            </p>
          )}
          {adjustmentQuestions.length ? (
            <div className="mt-4 rounded-md bg-zinc-50/80 px-3 py-3 text-sm leading-6 text-zinc-700 dark:bg-slate-900/60 dark:text-slate-300">
              <div className="mb-1.5 flex items-center gap-2 text-xs font-medium text-zinc-500 dark:text-slate-400">
                <RefreshCw className="h-3.5 w-3.5" />
                可以继续这样改
              </div>
              {adjustmentQuestions.map((item, index) => (
                <p key={`${index}-${item}`}>{item}</p>
              ))}
            </div>
          ) : null}
        </div>
      ) : null}

      {outlineItems.length ? (
        <div className="mt-5 space-y-3">
          {outlineItems.map((item, index) => (
            <div key={`${index}-${item.title}`} className="rounded-md px-1 py-1">
              <div className="min-w-0">
                <div className="text-[15px] font-semibold leading-6 text-zinc-900 dark:text-slate-100">{item.title}</div>
                {item.description ? (
                  <div title={item.tooltip || item.description} className="mt-1 line-clamp-2 text-sm leading-6 text-zinc-600 dark:text-slate-400">
                    {item.description}
                  </div>
                ) : null}
              </div>
            </div>
          ))}
        </div>
      ) : null}
    </>
  );
}
