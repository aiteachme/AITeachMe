import { useEffect } from "react";
import { Bot } from "lucide-react";

import { useSubjectAiAssistant } from "../components/ai/SubjectAiAssistant";

export function GlobalAssistantPage() {
  const { openAssistant, isOpen } = useSubjectAiAssistant();

  useEffect(() => {
    openAssistant();
  }, [openAssistant]);

  return (
    <section className="flex min-h-[calc(100dvh-8rem)] flex-col items-center justify-center px-4 text-center">
      <div className="flex h-14 w-14 items-center justify-center rounded-xl border border-slate-200 bg-white text-slate-600 shadow-sm dark:border-slate-800 dark:bg-slate-950 dark:text-slate-300">
        <Bot className="h-6 w-6" strokeWidth={2.2} />
      </div>
      <h1 className="mt-5 text-2xl font-semibold tracking-tight text-slate-950 dark:text-slate-100">
        全局助手
      </h1>
      <p className="mt-2 max-w-md text-sm leading-6 text-slate-500 dark:text-slate-400">
        跨学科的学习安排、资料整理和临时问题都可以放在这里。
      </p>
      <button
        type="button"
        onClick={() => openAssistant()}
        className="mt-5 inline-flex h-10 items-center justify-center rounded-lg border border-slate-200 bg-white px-4 text-sm font-medium text-slate-700 transition hover:bg-slate-50 hover:text-slate-950 dark:border-slate-800 dark:bg-slate-950 dark:text-slate-300 dark:hover:bg-slate-900 dark:hover:text-slate-100"
      >
        {isOpen ? "继续对话" : "打开全局助手"}
      </button>
    </section>
  );
}
