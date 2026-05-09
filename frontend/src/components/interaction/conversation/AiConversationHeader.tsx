import { History, MapPin, PanelRightClose, Plus } from "lucide-react";

import { cn } from "../../../lib/utils";
import type { ChatSessionSelectionTarget } from "./AiConversationTypes";
import { AiConversationSelectionTextPreview } from "./AiConversationSelectionTextPreview";

interface AiConversationHeaderProps {
  title: string;
  selectionTarget: ChatSessionSelectionTarget | null;
  onClose?: () => void;
  onReturnToSidebar?: () => void;
  onToggleHistory?: () => void;
  onStartNewSession: () => void;
  onJumpToSelectionTarget: (target: ChatSessionSelectionTarget) => void;
  isStreaming: boolean;
  isHistoryOpen?: boolean;
}

interface AiConversationReturnToSidebarButtonProps {
  onClick: () => void;
  className?: string;
  showLabel?: boolean;
}

export function AiConversationReturnToSidebarButton({
  onClick,
  className,
  showLabel = false,
}: AiConversationReturnToSidebarButtonProps) {
  return (
    <button
      type="button"
      onClick={onClick}
      className={cn(
        "inline-flex h-8 shrink-0 items-center justify-center whitespace-nowrap rounded-md text-zinc-500 transition hover:bg-zinc-100 hover:text-zinc-900 dark:text-slate-400 dark:hover:bg-slate-800 dark:hover:text-slate-100",
        showLabel ? "gap-1.5 px-2" : "w-8",
        className,
      )}
      aria-label="回到侧边栏"
      title="回到侧边栏"
    >
      <PanelRightClose className="h-4 w-4 shrink-0" />
      {showLabel ? <span className="text-[13px] font-medium">侧边栏</span> : null}
    </button>
  );
}

interface AiConversationCollapseButtonProps {
  onClick: () => void;
  className?: string;
  showLabel?: boolean;
}

export function AiConversationCollapseButton({
  onClick,
  className,
  showLabel = false,
}: AiConversationCollapseButtonProps) {
  return (
    <button
      type="button"
      onClick={onClick}
      className={cn(
        "inline-flex h-8 shrink-0 items-center justify-center whitespace-nowrap rounded-md text-zinc-500 transition hover:bg-zinc-100 hover:text-zinc-900 dark:text-slate-400 dark:hover:bg-slate-800 dark:hover:text-slate-100",
        showLabel ? "gap-1.5 px-2" : "w-8",
        className,
      )}
      aria-label="收起"
      title="收起"
    >
      <PanelRightClose className="h-4 w-4 shrink-0" />
      {showLabel ? <span className="text-[13px] font-medium">收起</span> : null}
    </button>
  );
}

interface AiConversationHistoryButtonProps {
  onClick: () => void;
  className?: string;
  showLabel?: boolean;
  active?: boolean;
}

export function AiConversationHistoryButton({
  onClick,
  className,
  showLabel = false,
  active = false,
}: AiConversationHistoryButtonProps) {
  return (
    <button
      type="button"
      onClick={onClick}
      data-ai-conversation-history-trigger="true"
      className={cn(
        "inline-flex h-8 shrink-0 items-center justify-center whitespace-nowrap rounded-md text-zinc-500 transition hover:bg-zinc-100 hover:text-zinc-900 dark:text-slate-400 dark:hover:bg-slate-800 dark:hover:text-slate-100",
        showLabel ? "gap-1.5 px-2" : "w-8",
        active && "bg-zinc-100 text-zinc-900 dark:bg-slate-800 dark:text-slate-100",
        className,
      )}
      aria-label="历史对话"
      title="历史对话"
    >
      <History className="h-4 w-4 shrink-0" />
      {showLabel ? <span className="text-[13px] font-medium">历史</span> : null}
    </button>
  );
}

export function AiConversationHeader({
  title,
  selectionTarget,
  onClose,
  onReturnToSidebar,
  onToggleHistory,
  onStartNewSession,
  onJumpToSelectionTarget,
  isStreaming,
  isHistoryOpen = false,
}: AiConversationHeaderProps) {
  return (
    <div className="flex shrink-0 items-center justify-between border-b border-zinc-200/60 bg-white px-4 py-2.5 dark:border-slate-800 dark:bg-slate-950">
      <div className="flex min-w-0 flex-1 items-center gap-2">
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
        {onReturnToSidebar ? (
          <AiConversationReturnToSidebarButton onClick={onReturnToSidebar} />
        ) : onClose ? (
          <AiConversationCollapseButton onClick={onClose} />
        ) : null}
        {onToggleHistory ? (
          <AiConversationHistoryButton onClick={onToggleHistory} active={isHistoryOpen} />
        ) : null}
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
      </div>
    </div>
  );
}
