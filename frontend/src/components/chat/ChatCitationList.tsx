import { BookOpenText, ChevronRight, LibraryBig } from "lucide-react";

import type { ChatContextItem } from "../../api/generated/model";

interface ChatCitationListProps {
  contexts: ChatContextItem[];
  onOpenContext: (context: ChatContextItem) => void;
}

export function ChatCitationList({ contexts, onOpenContext }: ChatCitationListProps) {
  const openableContexts = contexts.filter(
    (context) => context.chunk_id > 0 || Number(context.knowledge_unit_id ?? 0) > 0,
  );

  if (!openableContexts.length) {
    return null;
  }

  return (
    <div className="mt-4 space-y-2">
      <div className="flex items-center gap-2 text-xs font-medium uppercase tracking-[0.18em] text-slate-400 dark:text-slate-500">
        <LibraryBig className="h-3.5 w-3.5" />
        引用来源
      </div>

      <div className="grid gap-2">
        {openableContexts.map((context) => (
          <button
            key={`${context.chunk_id}-${context.knowledge_unit_id ?? "none"}-${context.file_id}-${context.title}`}
            type="button"
            onClick={() => onOpenContext(context)}
            className="group rounded-2xl border border-slate-200 bg-white px-4 py-3 text-left shadow-sm transition hover:border-slate-300 hover:shadow-md dark:border-slate-800 dark:bg-slate-950/80 dark:hover:border-slate-700 dark:hover:shadow-[0_18px_40px_-28px_rgba(0,0,0,0.72)]"
          >
            <div className="flex items-start justify-between gap-3">
              <div className="min-w-0">
                <div className="flex items-center gap-2 text-sm font-semibold text-slate-800 dark:text-slate-100">
                  <BookOpenText className="h-4 w-4 text-indigo-600" />
                  <span className="truncate">{context.title || "未命名片段"}</span>
                </div>
                <p className="mt-1 line-clamp-2 text-xs leading-5 text-slate-500 dark:text-slate-400">
                  {context.header_path || "未提供标题路径"}
                </p>
              </div>

              <div className="flex shrink-0 items-center gap-2 text-xs text-slate-400 dark:text-slate-500">
                <span className="rounded-full bg-slate-100 px-2 py-1 font-medium text-slate-500 dark:bg-slate-900 dark:text-slate-300">
                  相关度 {Math.round(context.score * 100)}%
                </span>
                <span className="rounded-full bg-slate-100 px-2 py-1 font-medium text-slate-500 dark:bg-slate-900 dark:text-slate-300">
                  {context.chunk_id > 0 ? "原文" : "知识点"}
                </span>
                <ChevronRight className="h-4 w-4 transition group-hover:translate-x-0.5" />
              </div>
            </div>
          </button>
        ))}
      </div>
    </div>
  );
}
