import type { ReactNode } from "react";
import { ArrowLeft, FileText, GraduationCap, Layers3, ListChecks, Target } from "lucide-react";

import type { ExamPaperDetailResponse } from "../../api/generated/model";
import { Button } from "../ui/Button";
import type { ExamStudyGuideFocusUnit, ExamStudyGuideResponse } from "./types";
import { buildExamTitle, formatDateTime } from "./examDisplay";

function clampPercent(value: number) {
  return Math.max(0, Math.min(100, value));
}

function formatMasteryPercent(value?: number | null) {
  if (typeof value !== "number" || !Number.isFinite(value)) return null;
  return Math.round(clampPercent(value <= 1 ? value * 100 : value));
}

function GuideSection({
  icon,
  title,
  items,
}: {
  icon: ReactNode;
  title: string;
  items: string[];
}) {
  if (!items.length) return null;

  return (
    <section className="border-t border-slate-200 pt-6 dark:border-slate-800">
      <div className="flex items-center gap-3">
        <span className="grid h-9 w-9 shrink-0 place-items-center rounded-xl bg-slate-100 text-slate-600 dark:bg-slate-800 dark:text-slate-300">
          {icon}
        </span>
        <h2 className="font-serif text-lg font-bold text-slate-950 dark:text-slate-100">{title}</h2>
      </div>
      <ol className="mt-4 space-y-3">
        {items.map((item, index) => (
          <li
            key={`${title}-${index}`}
            className="flex gap-3 rounded-xl bg-slate-50 px-4 py-3 text-sm leading-7 text-slate-700 dark:bg-slate-900/70 dark:text-slate-300"
          >
            <span className="w-6 shrink-0 pt-0.5 text-xs font-semibold text-slate-400 dark:text-slate-500">
              {String(index + 1).padStart(2, "0")}
            </span>
            <span className="min-w-0 flex-1 break-words">{item}</span>
          </li>
        ))}
      </ol>
    </section>
  );
}

function FocusUnitRow({ unit }: { unit: ExamStudyGuideFocusUnit }) {
  const masteryPercent = formatMasteryPercent(unit.mastery_score);

  return (
    <article className="px-4 py-4 sm:px-5">
      <div className="flex flex-col gap-2 sm:flex-row sm:items-start sm:justify-between">
        <h3 className="min-w-0 break-words text-sm font-semibold text-slate-900 dark:text-slate-100">
          {unit.knowledge_unit_name}
        </h3>
        {masteryPercent !== null ? (
          <span className="shrink-0 text-xs font-semibold text-slate-500 dark:text-slate-400">
            掌握度 {masteryPercent}%
          </span>
        ) : null}
      </div>
      <p className="mt-3 break-words text-sm leading-7 text-slate-600 dark:text-slate-300">{unit.reason}</p>
      {masteryPercent !== null ? (
        <div className="mt-3 h-1.5 overflow-hidden rounded-full bg-slate-100 dark:bg-slate-800">
          <div className="h-full rounded-full bg-slate-900 dark:bg-slate-100" style={{ width: `${masteryPercent}%` }} />
        </div>
      ) : null}
    </article>
  );
}

function FocusUnitsSection({ units }: { units: ExamStudyGuideFocusUnit[] }) {
  if (!units.length) return null;

  return (
    <section className="pt-6">
      <div className="flex items-center gap-3">
        <span className="grid h-9 w-9 shrink-0 place-items-center rounded-xl bg-slate-100 text-slate-600 dark:bg-slate-800 dark:text-slate-300">
          <Target className="h-4 w-4" />
        </span>
        <h2 className="font-serif text-lg font-bold text-slate-950 dark:text-slate-100">重点知识点</h2>
      </div>
      <div className="mt-4 overflow-hidden rounded-2xl border border-slate-200 bg-white dark:border-slate-800 dark:bg-slate-950">
        <div className="divide-y divide-slate-200 dark:divide-slate-800">
          {units.map((unit, index) => (
            <FocusUnitRow key={`${unit.knowledge_unit_id ?? unit.knowledge_unit_name}-${index}`} unit={unit} />
          ))}
        </div>
      </div>
    </section>
  );
}

export function ExamStudyGuideView({
  guide,
  paper,
  onBackToReview,
}: {
  guide: ExamStudyGuideResponse;
  paper: ExamPaperDetailResponse;
  onBackToReview: () => void;
}) {
  return (
    <article className="mx-auto max-w-4xl overflow-hidden rounded-[26px] border border-slate-200 bg-white shadow-[0_26px_70px_rgba(15,23,42,0.10)] dark:border-slate-800 dark:bg-slate-950 dark:shadow-[0_28px_70px_-34px_rgba(0,0,0,0.9)]">
      <header className="border-b border-slate-200 px-6 py-6 dark:border-slate-800 sm:px-8 sm:py-7">
        <div className="flex flex-col gap-4 sm:flex-row sm:items-start sm:justify-between">
          <div className="min-w-0">
            <p className="text-sm font-semibold text-slate-500 dark:text-slate-400">学习指南</p>
            <h1 className="mt-2 break-words font-serif text-2xl font-bold text-slate-950 dark:text-slate-100 sm:text-3xl">
              {buildExamTitle(paper)}
            </h1>
          </div>
          <Button variant="outline" className="h-10 shrink-0 rounded-full px-4 text-sm" onClick={onBackToReview}>
            <ArrowLeft className="h-4 w-4" />
            返回批改结果
          </Button>
        </div>

        <p className="mt-5 break-words text-sm leading-8 text-slate-700 dark:text-slate-300">
          {guide.overall_summary}
        </p>

        <div className="mt-5 flex flex-wrap items-center gap-2 text-xs font-semibold text-slate-500 dark:text-slate-400">
          <span className="rounded-full bg-slate-100 px-2.5 py-1 dark:bg-slate-800">
            生成 {formatDateTime(guide.generated_at)}
          </span>
          <span className="rounded-full bg-slate-100 px-2.5 py-1 dark:bg-slate-800">
            {guide.focus_units.length} 个重点知识点
          </span>
          <span className="rounded-full bg-slate-100 px-2.5 py-1 dark:bg-slate-800">
            {guide.review_tasks.length} 个复习任务
          </span>
        </div>
      </header>

      <div className="space-y-6 px-6 pb-7 pt-2 sm:px-8 sm:pb-8">
        <FocusUnitsSection units={guide.focus_units} />
        <GuideSection icon={<Layers3 className="h-4 w-4" />} title="优先补漏" items={guide.priority_gaps} />
        <GuideSection icon={<ListChecks className="h-4 w-4" />} title="下一步怎么学" items={guide.action_steps} />
        <GuideSection icon={<FileText className="h-4 w-4" />} title="复习任务" items={guide.review_tasks} />
        <GuideSection icon={<GraduationCap className="h-4 w-4" />} title="做得不错" items={guide.strengths} />
      </div>
    </article>
  );
}
