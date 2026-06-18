import type { ReactNode } from "react";
import { FileText, GraduationCap, Layers3, ListChecks, Target } from "lucide-react";

import type { ExamPaperDetailResponse } from "../../api/generated/model";
import { cn } from "../../lib/utils";
import { MarkdownViewer } from "../ui/MarkdownViewer";
import type { ExamStudyGuideFocusUnit, ExamStudyGuideResponse } from "./types";
import { formatDateTime, getExamPaperDisplayTitle } from "./examDisplay";

const GUIDE_MARKDOWN_CLASS =
  "min-w-0 break-words text-slate-700 dark:text-slate-300 [&_p]:mb-2 [&_p]:text-[15px] [&_p]:leading-7 [&_p:last-child]:mb-0 [&_ul]:my-2 [&_ol]:my-2 [&_li]:leading-7 [&_.katex-display]:my-3 [&_.katex-display]:rounded-md [&_.katex-display]:border [&_.katex-display]:border-slate-200 [&_.katex-display]:bg-slate-50/80 [&_.katex-display]:px-3 [&_.katex-display]:py-2 dark:[&_.katex-display]:border-slate-800 dark:[&_.katex-display]:bg-slate-900/70 [&_.katex]:text-inherit";

function clampPercent(value: number) {
  return Math.max(0, Math.min(100, value));
}

function formatMasteryPercent(value?: number | null) {
  if (typeof value !== "number" || !Number.isFinite(value)) return null;
  return Math.round(clampPercent(value <= 1 ? value * 100 : value));
}

function getMasteryBarColor(percent: number) {
  if (percent <= 30) return "bg-rose-500";
  if (percent <= 70) return "bg-amber-500";
  return "bg-emerald-500";
}

function getMasteryTextColor(percent: number) {
  if (percent <= 30) return "text-rose-600 dark:text-rose-400";
  if (percent <= 70) return "text-amber-600 dark:text-amber-400";
  return "text-emerald-600 dark:text-emerald-400";
}

function getGuideItems(items?: string[] | null) {
  return (items ?? []).filter((item) => typeof item === "string" && item.trim().length > 0);
}

function getGuideUnits(units?: ExamStudyGuideFocusUnit[] | null) {
  return units ?? [];
}

function GuideMarkdown({
  content,
  className,
}: {
  content?: string | null;
  className?: string;
}) {
  const markdown = typeof content === "string" && content.trim() ? content : " ";

  return (
    <div className={cn(GUIDE_MARKDOWN_CLASS, className)}>
      <MarkdownViewer content={markdown} variant="default" />
    </div>
  );
}

function GuideSection({
  icon,
  title,
  items,
}: {
  icon: ReactNode;
  title: string;
  items?: string[] | null;
}) {
  const visibleItems = getGuideItems(items);
  if (!visibleItems.length) return null;

  return (
    <section className="border-t border-slate-200 py-8 dark:border-slate-800">
      <div className="flex items-center gap-3">
        <span className="grid h-9 w-9 shrink-0 place-items-center rounded-md border border-slate-200 bg-slate-50 text-slate-600 dark:border-slate-800 dark:bg-slate-900 dark:text-slate-300">
          {icon}
        </span>
        <h2 className="font-serif text-[20px] font-bold leading-7 text-slate-950 dark:text-slate-100">{title}</h2>
      </div>

      <ol className="mt-5 space-y-3">
        {visibleItems.map((item, index) => (
          <li
            key={`${title}-${index}`}
            className="flex gap-3 rounded-lg bg-slate-50/60 px-4 py-3.5 dark:bg-slate-900/40"
          >
            <span className="grid h-6 w-6 shrink-0 place-items-center rounded-full bg-slate-200/80 text-[11px] font-bold text-slate-500 dark:bg-slate-800 dark:text-slate-400">
              {index + 1}
            </span>
            <div className="min-w-0 flex-1 pt-px">
              <GuideMarkdown content={item} />
            </div>
          </li>
        ))}
      </ol>
    </section>
  );
}

function FocusUnitRow({ unit }: { unit: ExamStudyGuideFocusUnit }) {
  const masteryPercent = formatMasteryPercent(unit.mastery_score);
  const barColor = masteryPercent !== null ? getMasteryBarColor(masteryPercent) : "";
  const textColor = masteryPercent !== null ? getMasteryTextColor(masteryPercent) : "";

  return (
    <article className="rounded-xl border border-slate-200/80 bg-slate-50/50 px-5 py-4 dark:border-slate-800 dark:bg-slate-900/30">
      <GuideMarkdown
        content={unit.knowledge_unit_name}
        className="[&_p]:text-[16px] [&_p]:font-bold [&_p]:leading-7 [&_p]:text-slate-950 dark:[&_p]:text-slate-100"
      />

      {masteryPercent !== null ? (
        <div className="mt-3 flex items-center gap-3">
          <div className="h-2.5 min-w-0 flex-1 overflow-hidden rounded-full bg-slate-200/80 dark:bg-slate-800">
            <div className={`h-full rounded-full transition-all ${barColor}`} style={{ width: `${Math.max(masteryPercent, 2)}%` }} />
          </div>
          <span className={`shrink-0 text-xs font-bold ${textColor}`}>
            {masteryPercent}%
          </span>
        </div>
      ) : null}

      <GuideMarkdown
        content={unit.reason}
        className="mt-3 [&_p]:text-[13px] [&_p]:leading-6 [&_p]:text-slate-500 dark:[&_p]:text-slate-400"
      />
    </article>
  );
}

function FocusUnitsSection({ units }: { units?: ExamStudyGuideFocusUnit[] | null }) {
  const visibleUnits = getGuideUnits(units);
  if (!visibleUnits.length) return null;

  return (
    <section className="border-t border-slate-200 py-8 dark:border-slate-800">
      <div className="flex items-center gap-3">
        <span className="grid h-9 w-9 shrink-0 place-items-center rounded-md border border-slate-200 bg-slate-50 text-slate-600 dark:border-slate-800 dark:bg-slate-900 dark:text-slate-300">
          <Target className="h-4 w-4" />
        </span>
        <h2 className="font-serif text-[20px] font-bold leading-7 text-slate-950 dark:text-slate-100">重点知识点</h2>
      </div>

      <div className="mt-5 space-y-3">
        {visibleUnits.map((unit, index) => (
          <FocusUnitRow key={`${unit.knowledge_unit_id ?? unit.knowledge_unit_name}-${index}`} unit={unit} />
        ))}
      </div>
    </section>
  );
}

export function ExamStudyGuideView({
  guide,
  paper,
}: {
  guide: ExamStudyGuideResponse;
  paper: ExamPaperDetailResponse;
}) {
  const focusUnits = getGuideUnits(guide.focus_units);
  const reviewTasks = getGuideItems(guide.review_tasks);

  return (
    <div className="relative mx-auto w-full max-w-[1040px] pb-12">
      <div className="absolute bottom-8 -right-5 top-5 hidden w-full border border-slate-200 bg-white shadow-[0_18px_36px_rgba(15,23,42,0.08)] dark:border-slate-800 dark:bg-slate-900/80 dark:shadow-[0_18px_36px_rgba(0,0,0,0.42)] lg:block" />
      <div className="absolute bottom-4 -right-2 top-2 hidden w-full border border-slate-200 bg-white shadow-[0_14px_30px_rgba(15,23,42,0.06)] dark:border-slate-800 dark:bg-slate-900/90 dark:shadow-[0_14px_30px_rgba(0,0,0,0.36)] lg:block" />

      <article className="relative min-h-[1470px] overflow-hidden border border-slate-200 bg-white shadow-[0_26px_70px_rgba(15,23,42,0.15)] dark:border-slate-800 dark:bg-slate-950 dark:shadow-[0_28px_76px_-34px_rgba(0,0,0,0.9)]">
        <header className="px-6 pb-6 pt-12 text-center sm:px-10 sm:pt-16 lg:px-16">
          <h1 className="break-words font-serif text-3xl font-bold tracking-[0.08em] text-slate-950 dark:text-slate-100 sm:text-4xl">
            {getExamPaperDisplayTitle(paper)}
          </h1>
          <div className="mx-auto mt-5 flex max-w-md items-center justify-center gap-3 text-slate-400 dark:text-slate-600">
            <span className="h-px flex-1 bg-slate-300 dark:bg-slate-700" />
            <span className="h-2 w-2 rotate-45 bg-slate-800 dark:bg-slate-300" />
            <span className="h-px flex-1 bg-slate-300 dark:bg-slate-700" />
          </div>
          <p className="mt-4 font-serif text-base font-semibold text-slate-600 dark:text-slate-400">
            复习指南
          </p>

          <div className="mt-8 border-y border-dashed border-slate-300 py-5 text-left font-serif text-sm leading-8 text-slate-700 dark:border-slate-700 dark:text-slate-300 sm:text-base">
            <GuideMarkdown
              content={guide.overall_summary}
              className="[&_p]:font-serif [&_p]:text-sm [&_p]:leading-8 [&_p]:text-slate-700 [&_p]:text-justify dark:[&_p]:text-slate-300 sm:[&_p]:text-base"
            />
          </div>

          <div className="mt-5 flex flex-wrap items-center gap-2 text-xs font-semibold text-slate-500 dark:text-slate-400">
            {paper.score_obtained != null && paper.total_score != null ? (
              <span className="rounded-md bg-slate-100 px-2.5 py-1 dark:bg-slate-800">
                得分 {paper.score_obtained}/{paper.total_score}
              </span>
            ) : null}
            {paper.score_obtained != null && paper.total_score != null && paper.total_score > 0 ? (
              <span className="rounded-md bg-slate-100 px-2.5 py-1 dark:bg-slate-800">
                正确率 {Math.round((paper.score_obtained / paper.total_score) * 100)}%
              </span>
            ) : null}
            <span className="rounded-md bg-slate-100 px-2.5 py-1 dark:bg-slate-800">
              生成时间 {formatDateTime(guide.generated_at)}
            </span>
          </div>
        </header>

        <div className="px-6 pb-10 sm:px-10 lg:px-14">
          <GuideSection icon={<GraduationCap className="h-4 w-4" />} title="做得不错" items={guide.strengths} />
          <FocusUnitsSection units={focusUnits} />
          <GuideSection icon={<Layers3 className="h-4 w-4" />} title="优先补漏" items={guide.priority_gaps} />
          <GuideSection icon={<ListChecks className="h-4 w-4" />} title="下一步怎么学" items={guide.action_steps} />
          <GuideSection icon={<FileText className="h-4 w-4" />} title="复习任务" items={reviewTasks} />
        </div>
      </article>
    </div>
  );
}
