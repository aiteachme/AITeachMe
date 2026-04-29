import { CheckCircle2, XCircle } from "lucide-react";

import type { ExamPaperItemResponse } from "../../api/generated/model";
import { ExamMarkdown } from "./ExamMarkdown";
import { buildKnowledgeLabel, formatDifficultyLabel, formatQuestionTypeLabel } from "./examDisplay";

interface ExamQuestionAnalysisSheetProps {
  item?: ExamPaperItemResponse | null;
}

function AnalysisBlock({ title, content }: { title: string; content: string }) {
  return (
    <section className="border-t border-slate-200 pt-5 dark:border-slate-800">
      <h3 className="font-serif text-lg font-bold text-slate-950 dark:text-slate-100">{title}</h3>
      <div className="mt-3 break-words text-sm leading-8 text-slate-700 dark:text-slate-300 [&_p]:mb-2 [&_.katex-display]:my-3">
        <ExamMarkdown content={content} />
      </div>
    </section>
  );
}

export function ExamQuestionAnalysisSheet({ item }: ExamQuestionAnalysisSheetProps) {
  if (!item) {
    return (
      <aside className="relative min-h-[560px] w-full min-w-0 overflow-hidden border border-slate-200 bg-white px-8 py-8 shadow-[0_26px_70px_rgba(15,23,42,0.12)] dark:border-slate-800 dark:bg-slate-950 dark:shadow-[0_28px_70px_-34px_rgba(0,0,0,0.9)]">
        <h2 className="font-serif text-2xl font-bold text-slate-950 dark:text-slate-100">题目解析</h2>
        <div className="mt-8 rounded-xl border border-dashed border-slate-200 px-5 py-8 text-center text-sm text-slate-500 dark:border-slate-800 dark:text-slate-400">
          请选择左侧题目查看解析。
        </div>
      </aside>
    );
  }

  const isCorrect = item.is_correct === true;

  return (
    <aside className="relative min-h-[720px] w-full min-w-0 overflow-hidden border border-slate-200 bg-white px-6 py-7 shadow-[0_26px_70px_rgba(15,23,42,0.12)] dark:border-slate-800 dark:bg-slate-950 dark:shadow-[0_28px_70px_-34px_rgba(0,0,0,0.9)] sm:px-8 lg:sticky lg:top-24">
      <header className="border-b border-slate-200 pb-5 dark:border-slate-800">
        <div className="flex flex-wrap items-start justify-between gap-4">
          <div>
            <p className="text-xs font-semibold uppercase tracking-[0.18em] text-slate-400">第 {item.item_order} 题</p>
            <h2 className="mt-2 font-serif text-2xl font-bold text-slate-950 dark:text-slate-100">题目解析</h2>
          </div>
          <span
            className={`inline-flex items-center gap-1.5 rounded-full px-3 py-1 text-xs font-semibold ${
              isCorrect ? "bg-emerald-50 text-emerald-700 dark:bg-emerald-500/10 dark:text-emerald-300" : "bg-rose-50 text-rose-700 dark:bg-rose-500/10 dark:text-rose-300"
            }`}
          >
            {isCorrect ? <CheckCircle2 className="h-3.5 w-3.5" /> : <XCircle className="h-3.5 w-3.5" />}
            {isCorrect ? "正确" : "需要订正"}
          </span>
        </div>
        <div className="mt-4 flex flex-wrap items-center gap-2 text-xs font-semibold text-slate-500 dark:text-slate-400">
          <span className="rounded-full bg-slate-100 px-2.5 py-1 dark:bg-slate-800">{formatDifficultyLabel(item.difficulty)}</span>
          <span className="rounded-full bg-slate-100 px-2.5 py-1 dark:bg-slate-800">{formatQuestionTypeLabel(item.question_type)}</span>
          <span className="max-w-full break-words rounded-md bg-slate-50 px-2.5 py-1 text-slate-500 ring-1 ring-inset ring-slate-200 dark:bg-slate-900 dark:text-slate-400 dark:ring-slate-800">
            {buildKnowledgeLabel(item)}
          </span>
        </div>
      </header>

      <div className="mt-6 space-y-6">
        <section>
          <h3 className="font-serif text-lg font-bold text-slate-950 dark:text-slate-100">题干</h3>
          <div className="mt-3 break-words text-sm leading-8 text-slate-700 dark:text-slate-300 [&_p]:mb-2 [&_.katex-display]:my-3">
            <ExamMarkdown content={item.stem} />
          </div>
        </section>

        <AnalysisBlock title="你的答案" content={item.user_answer || "未作答"} />
        <AnalysisBlock title="正确答案" content={item.correct_answer || "无标准答案"} />
        <AnalysisBlock title="解析" content={item.explanation || "暂无解析"} />
      </div>
    </aside>
  );
}
