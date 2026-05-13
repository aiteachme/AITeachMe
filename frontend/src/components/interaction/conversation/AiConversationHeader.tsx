import {
  ChevronDown,
  ChevronsLeft,
  CirclePlus,
  Maximize2,
  PanelRight,
  PanelRightOpen,
  Share2,
  X,
  type LucideIcon,
} from "lucide-react";

import { cn } from "../../../lib/utils";
import type { ChatSessionSelectionTarget } from "./AiConversationTypes";
import { AiConversationSelectionTextPreview } from "./AiConversationSelectionTextPreview";

interface AiConversationHeaderProps {
  title: string;
  selectionTarget: ChatSessionSelectionTarget | null;
  onClose?: () => void;
  onReturnToSidebar?: () => void;
  onToggleHistory?: () => void;
  onTogglePresentation?: () => void;
  onStartNewSession: () => void;
  onJumpToSelectionTarget: (target: ChatSessionSelectionTarget) => void;
  isStreaming: boolean;
  isHistoryOpen?: boolean;
  isFullscreen?: boolean;
}

interface AiConversationReturnToSidebarButtonProps {
  onClick: () => void;
  className?: string;
  showLabel?: boolean;
}

const TITLE_BAR_ICON_BUTTON_CLASS_NAME =
  "inline-flex h-7 w-7 shrink-0 items-center justify-center whitespace-nowrap rounded-md text-zinc-500 transition hover:bg-zinc-100 hover:text-zinc-900 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-zinc-200 disabled:cursor-not-allowed disabled:opacity-45 dark:text-slate-400 dark:hover:bg-slate-800 dark:hover:text-slate-100 dark:focus-visible:ring-slate-700";

interface AiConversationHeaderIconButtonProps {
  icon: LucideIcon;
  label: string;
  onClick: () => void;
  active?: boolean;
  disabled?: boolean;
  className?: string;
  dataHistoryTrigger?: boolean;
}

function AiConversationHeaderIconButton({
  icon: Icon,
  label,
  onClick,
  active = false,
  disabled = false,
  className,
  dataHistoryTrigger = false,
}: AiConversationHeaderIconButtonProps) {
  return (
    <button
      type="button"
      onClick={onClick}
      disabled={disabled}
      data-ai-conversation-history-trigger={dataHistoryTrigger ? "true" : undefined}
      className={cn(
        TITLE_BAR_ICON_BUTTON_CLASS_NAME,
        active && "bg-zinc-100 text-zinc-900 dark:bg-slate-800 dark:text-slate-100",
        className,
      )}
      aria-label={label}
      title={label}
    >
      <Icon className="h-4 w-4 shrink-0" strokeWidth={2} />
    </button>
  );
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
        TITLE_BAR_ICON_BUTTON_CLASS_NAME,
        showLabel ? "w-auto gap-1.5 px-2" : undefined,
        className,
      )}
      aria-label="回到侧边栏"
      title="回到侧边栏"
    >
      <ChevronsLeft className="h-4 w-4 shrink-0" strokeWidth={2} />
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
        TITLE_BAR_ICON_BUTTON_CLASS_NAME,
        showLabel ? "w-auto gap-1.5 px-2" : undefined,
        className,
      )}
      aria-label="收起"
      title="收起"
    >
      <ChevronsLeft className="h-4 w-4 shrink-0" strokeWidth={2} />
      {showLabel ? <span className="text-[13px] font-medium">收起</span> : null}
    </button>
  );
}

interface AiConversationCloseButtonProps {
  onClick: () => void;
  className?: string;
}

export function AiConversationCloseButton({
  onClick,
  className,
}: AiConversationCloseButtonProps) {
  return (
    <button
      type="button"
      onClick={onClick}
      className={cn(TITLE_BAR_ICON_BUTTON_CLASS_NAME, className)}
      aria-label="关闭对话"
      title="关闭对话"
    >
      <X className="h-4 w-4 shrink-0" strokeWidth={2} />
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
        TITLE_BAR_ICON_BUTTON_CLASS_NAME,
        showLabel ? "w-auto gap-1.5 px-2" : undefined,
        active && "bg-zinc-100 text-zinc-900 dark:bg-slate-800 dark:text-slate-100",
        className,
      )}
      aria-label="历史对话"
      title="历史对话"
    >
      <PanelRight className="h-4 w-4 shrink-0" strokeWidth={2} />
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
  onTogglePresentation,
  onStartNewSession,
  onJumpToSelectionTarget,
  isStreaming,
  isHistoryOpen = false,
  isFullscreen = false,
}: AiConversationHeaderProps) {
  const PresentationIcon = isFullscreen ? PanelRightOpen : Maximize2;
  const presentationLabel = isFullscreen ? "切换为侧边栏" : "切换为全屏";

  return (
    <div className="flex h-[calc(4.25rem+env(safe-area-inset-top))] shrink-0 items-center border-b border-zinc-200 bg-white px-4 pt-[calc(0.75rem+env(safe-area-inset-top))] dark:border-slate-800 dark:bg-slate-950">
      <div className="flex min-w-0 flex-1 items-center gap-1.5">
        <div className="flex min-w-0 flex-1 items-center gap-2 px-0.5">
          {onToggleHistory ? (
            <button
              type="button"
              onClick={onToggleHistory}
              data-ai-conversation-history-trigger="true"
              className={cn(
                "flex h-7 min-w-0 items-center gap-1.5 rounded-md px-1.5 text-left transition hover:bg-zinc-100 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-zinc-200 dark:hover:bg-slate-800 dark:focus-visible:ring-slate-700",
                isHistoryOpen && "bg-zinc-100 dark:bg-slate-800",
              )}
              aria-expanded={isHistoryOpen}
              aria-label="展开历史选择"
              title="展开历史选择"
            >
              <h2 className="truncate text-[13px] font-medium tracking-normal text-zinc-800 dark:text-slate-100">
                {title}
              </h2>
              <ChevronDown
                className={cn(
                  "h-3.5 w-3.5 shrink-0 text-zinc-400 transition-transform dark:text-slate-500",
                  isHistoryOpen && "rotate-180",
                )}
                strokeWidth={2}
              />
            </button>
          ) : (
            <div className="flex min-w-0 items-center gap-1.5 px-1.5">
              <h2 className="truncate text-[13px] font-medium tracking-normal text-zinc-800 dark:text-slate-100">
                {title}
              </h2>
              <ChevronDown className="h-3.5 w-3.5 shrink-0 text-zinc-400 dark:text-slate-500" strokeWidth={2} />
            </div>
          )}
          {selectionTarget ? (
            <AiConversationSelectionTextPreview
              prefix={selectionTarget.kind === "exam_question" ? "题目：" : "划词："}
              text={selectionTarget.selectedText}
              className="hidden min-w-0 max-w-[12rem] truncate text-[11px] text-zinc-400 dark:text-slate-500 xl:block"
            />
          ) : null}
        </div>
      </div>

      <div className="flex shrink-0 items-center gap-0.5 pl-1.5">
        {selectionTarget ? (
          <AiConversationHeaderIconButton
            icon={Share2}
            label={`${selectionTarget.kind === "exam_question" ? "定位题目" : "定位原文"}：${selectionTarget.selectedText}`}
            onClick={() => onJumpToSelectionTarget(selectionTarget)}
            className={cn(
              selectionTarget.kind === "exam_question"
                ? "hover:text-violet-700 dark:hover:text-violet-200"
                : "hover:text-amber-700 dark:hover:text-amber-200",
            )}
          />
        ) : null}
        <AiConversationHeaderIconButton
          icon={CirclePlus}
          label="新建会话"
          onClick={onStartNewSession}
          disabled={isStreaming}
        />
        {onTogglePresentation ? (
          <AiConversationHeaderIconButton
            icon={PresentationIcon}
            label={presentationLabel}
            onClick={onTogglePresentation}
            className="hidden sm:inline-flex"
          />
        ) : null}
        {onClose && isFullscreen ? (
          <AiConversationCloseButton onClick={onClose} />
        ) : onReturnToSidebar ? (
          <AiConversationReturnToSidebarButton onClick={onReturnToSidebar} />
        ) : onClose ? (
          <AiConversationCollapseButton onClick={onClose} />
        ) : null}
      </div>
    </div>
  );
}
