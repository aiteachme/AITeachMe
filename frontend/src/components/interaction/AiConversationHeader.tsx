import { ChevronRight, MapPin, Plus, Trash2 } from "lucide-react";

import { cn } from "../../lib/utils";
import type { ChatSessionSelectionTarget } from "./AiConversationTypes";
import { AiConversationSelectionTextPreview } from "./AiConversationSelectionTextPreview";

interface AiConversationHeaderProps {
  title: string;
  selectionTarget: ChatSessionSelectionTarget | null;
  onClose?: () => void;
  onStartNewSession: () => void;
  onClearCurrentSession: () => void;
  onJumpToSelectionTarget: (target: ChatSessionSelectionTarget) => void;
  isStreaming: boolean;
  selectedSessionId: string | null;
}

export function AiConversationHeader({
  title,
  selectionTarget,
  onClose,
  onStartNewSession,
  onClearCurrentSession,
  onJumpToSelectionTarget,
  isStreaming,
  selectedSessionId,
}: AiConversationHeaderProps) {
  return (
    <div className="flex shrink-0 items-center justify-between border-b border-zinc-200/60 bg-white px-4 py-2.5 dark:border-slate-800 dark:bg-slate-950">
      <div className="flex min-w-0 flex-1 items-center gap-2">
        {onClose ? (
          <>
            <button
              type="button"
              onClick={onClose}
              className="inline-flex h-8 shrink-0 items-center justify-center gap-1.5 whitespace-nowrap rounded-md px-2 text-zinc-500 transition hover:bg-zinc-100 hover:text-zinc-900 dark:text-slate-400 dark:hover:bg-slate-800 dark:hover:text-slate-100"
              aria-label="收起"
            >
              <ChevronRight className="h-4 w-4 shrink-0" />
              <span className="hidden whitespace-nowrap text-[13px] font-medium lg:inline">收起</span>
            </button>
            <div className="mx-1 h-4 w-px shrink-0 bg-slate-200 dark:bg-slate-800" />
          </>
        ) : null}

        <div className="min-w-0 flex-1 pr-2">
          <div className="flex min-w-0 items-center gap-2">
            <h2 className="truncate text-[14px] font-semibold tracking-tight text-zinc-900 dark:text-slate-100">
              {title}
            </h2>
            {selectionTarget ? (
              <button
                type="button"
                onClick={() => onJumpToSelectionTarget(selectionTarget)}
                className={cn(
                  "inline-flex h-7 shrink-0 items-center gap-1 rounded-md border px-2 text-[12px] font-medium transition",
                  selectionTarget.kind === "exam_question"
                    ? "border-violet-200 bg-violet-50 text-violet-700 hover:border-violet-300 hover:bg-violet-100 hover:text-violet-800 dark:border-violet-500/30 dark:bg-violet-500/10 dark:text-violet-200 dark:hover:bg-violet-500/15"
                    : "border-amber-200 bg-amber-50 text-amber-700 hover:border-amber-300 hover:bg-amber-100 hover:text-amber-800 dark:border-amber-500/30 dark:bg-amber-500/10 dark:text-amber-200 dark:hover:bg-amber-500/15",
                )}
                title={`${selectionTarget.kind === "exam_question" ? "定位题目" : "定位原文"}：${selectionTarget.selectedText}`}
                aria-label={selectionTarget.kind === "exam_question" ? "定位题目" : "定位原文"}
              >
                <MapPin className="h-3.5 w-3.5" />
                <span className="hidden sm:inline">
                  {selectionTarget.kind === "exam_question" ? "定位题目" : "定位原文"}
                </span>
              </button>
            ) : null}
          </div>
          {selectionTarget ? (
            <AiConversationSelectionTextPreview
              prefix={selectionTarget.kind === "exam_question" ? "题目：" : "划词："}
              text={selectionTarget.selectedText}
              className="mt-0.5 hidden max-w-[32rem] text-[11px] text-zinc-400 dark:text-slate-500 md:block"
            />
          ) : null}
        </div>
      </div>

      <div className="flex shrink-0 items-center gap-1">
        <button
          type="button"
          onClick={onStartNewSession}
          disabled={isStreaming}
          className="inline-flex h-8 w-8 items-center justify-center rounded-md text-zinc-500 transition hover:bg-zinc-100 hover:text-zinc-900 disabled:opacity-50 dark:text-slate-400 dark:hover:bg-slate-800 dark:hover:text-slate-100"
          aria-label="新建会话"
          title="新建会话"
        >
          <Plus className="h-4 w-4" />
        </button>
        <button
          type="button"
          onClick={onClearCurrentSession}
          disabled={!selectedSessionId || isStreaming}
          className="inline-flex h-8 w-8 items-center justify-center rounded-md text-zinc-500 transition hover:bg-zinc-100 hover:text-zinc-900 disabled:opacity-50 dark:text-slate-400 dark:hover:bg-slate-800 dark:hover:text-slate-100"
          aria-label="清空记录"
          title="清空记录"
        >
          <Trash2 className="h-4 w-4" />
        </button>
      </div>
    </div>
  );
}
