import type { ReactNode } from "react";
import { ArrowRight, FileText, GraduationCap, Layers3, Sparkles, Target } from "lucide-react";

import type { ExamPaperDetailResponse } from "../../api/generated/model";
import { Button } from "../ui/Button";
import type { ExamStudyGuideResponse } from "./types";
import { buildExamTitle } from "./examDisplay";

function StudyGuideSection({
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
    <section className="rounded-[28px] border border-slate-200/80 bg-white/92 p-6 shadow-sm">
      <div className="flex items-center gap-3">
        <div className="grid h-10 w-10 place-items-center rounded-2xl bg-slate-100 text-slate-700">
          {icon}
        </div>
        <div>
          <h2 className="text-lg font-semibold text-slate-950">{title}</h2>
          <p className="text-sm text-slate-500">根据本次考卷与当前掌握情况生成</p>
        </div>
      </div>
      <div className="mt-5 space-y-3">
        {items.map((item, index) => (
          <div key={`${title}-${index}`} className="flex gap-3 rounded-2xl bg-slate-50 px-4 py-3 text-sm leading-7 text-slate-700">
            <span className="mt-1 text-xs font-semibold text-slate-400">{index + 1}</span>
            <span>{item}</span>
          </div>
        ))}
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
    <div className="space-y-8">
      <section className="rounded-[32px] border border-slate-200/80 bg-[linear-gradient(135deg,#ffffff_0%,#f8fbff_52%,#f2f7ff_100%)] px-6 py-7 shadow-sm sm:px-8">
        <div className="flex flex-col gap-5 lg:flex-row lg:items-start lg:justify-between">
          <div className="max-w-3xl">
            <div className="inline-flex items-center gap-2 rounded-full bg-slate-100 px-3 py-1 text-xs font-semibold tracking-[0.16em] text-slate-500">
              <Sparkles className="h-3.5 w-3.5" />
              学习指南
            </div>
            <h1 className="mt-4 text-3xl font-semibold tracking-[-0.04em] text-slate-950 sm:text-4xl">
              {buildExamTitle(paper)}
            </h1>
            <p className="mt-4 text-base leading-8 text-slate-600">{guide.overall_summary}</p>
          </div>
          <Button variant="outline" className="rounded-full px-5" onClick={onBackToReview}>
            返回批改结果
          </Button>
        </div>
      </section>

      {guide.focus_units.length > 0 && (
        <section className="rounded-[28px] border border-slate-200/80 bg-white/92 p-6 shadow-sm">
          <div className="flex items-center gap-3">
            <div className="grid h-10 w-10 place-items-center rounded-2xl bg-rose-50 text-rose-700">
              <Target className="h-5 w-5" />
            </div>
            <div>
              <h2 className="text-lg font-semibold text-slate-950">重点查漏知识点</h2>
              <p className="text-sm text-slate-500">优先处理这些最影响当前表现的知识点</p>
            </div>
          </div>
          <div className="mt-5 grid gap-4 lg:grid-cols-2">
            {guide.focus_units.map((unit, index) => (
              <div key={`${unit.knowledge_unit_name}-${index}`} className="rounded-[24px] border border-slate-200 bg-slate-50 px-5 py-4">
                <div className="flex items-center justify-between gap-3">
                  <h3 className="text-base font-semibold text-slate-900">{unit.knowledge_unit_name}</h3>
                  {typeof unit.mastery_score === "number" && (
                    <span className="rounded-full bg-white px-3 py-1 text-xs font-medium text-slate-500 ring-1 ring-inset ring-slate-200">
                      掌握度 {(unit.mastery_score * 100).toFixed(0)}%
                    </span>
                  )}
                </div>
                <p className="mt-3 text-sm leading-7 text-slate-600">{unit.reason}</p>
              </div>
            ))}
          </div>
        </section>
      )}

      <div className="grid gap-6 xl:grid-cols-2">
        <StudyGuideSection icon={<GraduationCap className="h-5 w-5" />} title="做得不错" items={guide.strengths} />
        <StudyGuideSection icon={<Layers3 className="h-5 w-5" />} title="优先补漏" items={guide.priority_gaps} />
        <StudyGuideSection icon={<ArrowRight className="h-5 w-5" />} title="下一步怎么学" items={guide.action_steps} />
        <StudyGuideSection icon={<FileText className="h-5 w-5" />} title="立刻可做的复习任务" items={guide.review_tasks} />
      </div>
    </div>
  );
}
