import { BookOpenText, ChevronRight, LibraryBig } from "lucide-react";

import type { ChatContextItem } from "../../api/generated/model";
import { cn } from "../../lib/utils";

interface ChatCitationListProps {
  contexts: ChatContextItem[];
  onOpenContext: (context: ChatContextItem) => void;
  variant?: "default" | "compact";
}

export function ChatCitationList({
  contexts,
  onOpenContext,
  variant = "default",
}: ChatCitationListProps) {
  const openableContexts = dedupeOpenableContexts(contexts);

  if (!openableContexts.length) {
    return null;
  }

  if (variant === "compact") {
    const firstContext = openableContexts[0];
    return (
      <details className="group mt-3 overflow-hidden rounded-lg border border-slate-200 bg-slate-50/80 text-left dark:border-slate-800 dark:bg-slate-900/60">
        <summary className="flex cursor-pointer list-none items-center gap-2 px-3 py-2 text-xs text-slate-600 outline-none transition hover:bg-white/70 focus-visible:ring-2 focus-visible:ring-indigo-500/35 dark:text-slate-300 dark:hover:bg-slate-900 [&::-webkit-details-marker]:hidden">
          <LibraryBig className="h-3.5 w-3.5 shrink-0 text-indigo-500" />
          <span className="shrink-0 font-medium">引用来源</span>
          <span className="shrink-0 rounded-full bg-white px-1.5 py-0.5 text-[10px] font-semibold text-slate-500 dark:bg-slate-800 dark:text-slate-300">
            {openableContexts.length}
          </span>
          <span className="min-w-0 flex-1 truncate text-slate-400 dark:text-slate-500">
            {getContextTitle(firstContext)}
          </span>
          <ChevronRight className="h-3.5 w-3.5 shrink-0 text-slate-400 transition-transform group-open:rotate-90" />
        </summary>

        <div className="max-h-56 overflow-y-auto border-t border-slate-200 bg-white dark:border-slate-800 dark:bg-slate-950/70">
          {openableContexts.map((context, index) => (
            <button
              key={getContextKey(context)}
              type="button"
              onClick={() => onOpenContext(context)}
              className={cn(
                "group/item flex w-full items-start gap-2 px-3 py-2.5 text-left transition hover:bg-slate-50 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-indigo-500/35 dark:hover:bg-slate-900",
                index > 0 && "border-t border-slate-100 dark:border-slate-800/70",
              )}
            >
              <span className="mt-0.5 flex h-5 w-5 shrink-0 items-center justify-center rounded-md bg-indigo-50 text-[10px] font-semibold text-indigo-600 dark:bg-indigo-500/15 dark:text-indigo-200">
                {index + 1}
              </span>
              <span className="min-w-0 flex-1">
                <span className="flex min-w-0 items-center gap-1.5">
                  <span className="truncate text-[13px] font-medium leading-5 text-slate-800 dark:text-slate-100">
                    {getContextTitle(context)}
                  </span>
                  <span className="shrink-0 rounded bg-slate-100 px-1.5 py-0.5 text-[10px] font-medium leading-none text-slate-500 dark:bg-slate-800 dark:text-slate-300">
                    {getContextKindLabel(context)}
                  </span>
                </span>
                <span className="mt-0.5 line-clamp-2 text-[11px] leading-4 text-slate-500 dark:text-slate-400">
                  {getContextSubtitle(context)}
                </span>
              </span>
              <span className="mt-0.5 flex shrink-0 items-center gap-1 text-[10px] font-medium text-slate-400 dark:text-slate-500">
                {formatScore(context.score)}
                <ChevronRight className="h-3.5 w-3.5 transition group-hover/item:translate-x-0.5" />
              </span>
            </button>
          ))}
        </div>
      </details>
    );
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
            key={getContextKey(context)}
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
                  相关度 {formatScore(context.score)}
                </span>
                <span className="rounded-full bg-slate-100 px-2 py-1 font-medium text-slate-500 dark:bg-slate-900 dark:text-slate-300">
                  {getContextKindLabel(context)}
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

function dedupeOpenableContexts(contexts: ChatContextItem[]): ChatContextItem[] {
  const seen = new Set<string>();
  const result: ChatContextItem[] = [];
  for (const context of contexts) {
    if (!isOpenableContext(context)) {
      continue;
    }
    const key = getContextKey(context);
    if (seen.has(key)) {
      continue;
    }
    seen.add(key);
    result.push(context);
  }
  return result;
}

function isOpenableContext(context: ChatContextItem): boolean {
  return Number(context.chunk_id ?? 0) > 0 || Number(context.knowledge_unit_id ?? 0) > 0;
}

function getContextKey(context: ChatContextItem): string {
  const chunkId = Number(context.chunk_id ?? 0);
  const unitId = Number(context.knowledge_unit_id ?? 0);
  if (chunkId > 0) {
    return `chunk-${chunkId}`;
  }
  if (unitId > 0) {
    return `unit-${unitId}`;
  }
  return `${context.file_id}-${context.title}-${context.header_path}`;
}

function getContextTitle(context: ChatContextItem): string {
  return context.knowledge_unit_name?.trim() || context.title?.trim() || "未命名片段";
}

function getContextSubtitle(context: ChatContextItem): string {
  return (
    context.evidence_quote?.trim() ||
    context.relation_path?.trim() ||
    context.header_path?.trim() ||
    context.title?.trim() ||
    "未提供来源摘要"
  );
}

function getContextKindLabel(context: ChatContextItem): string {
  if (Number(context.chunk_id ?? 0) > 0) {
    return "原文";
  }
  return "知识点";
}

function formatScore(score: number): string {
  if (!Number.isFinite(score)) {
    return "--";
  }
  return `${Math.round(score * 100)}%`;
}
