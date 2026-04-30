import { MessageSquareText, X } from "lucide-react";

import type { ChatModelChoice } from "../chat/ChatModelSelect";
import { ChatComposer } from "../chat/ChatComposer";
import { cn } from "../../lib/utils";
import { AI_SOURCE_EXAM_QUESTION } from "./types";
import type { PendingSelectionContext } from "./AiConversationTypes";
import { AiConversationSelectionTextPreview } from "./AiConversationSelectionTextPreview";

interface AiConversationComposerDockProps {
  draft: string;
  onDraftChange: (value: string) => void;
  onSend: () => void;
  onAbort: () => void;
  isStreaming: boolean;
  disabled: boolean;
  autoFocusKey: number;
  modelValue: ChatModelChoice;
  onModelChange: (value: ChatModelChoice) => void;
  isPlannerConversation: boolean;
  pendingSelectionContext: PendingSelectionContext | null;
  onClearPendingSelectionContext: () => void;
}

export function AiConversationComposerDock({
  draft,
  onDraftChange,
  onSend,
  onAbort,
  isStreaming,
  disabled,
  autoFocusKey,
  modelValue,
  onModelChange,
  isPlannerConversation,
  pendingSelectionContext,
  onClearPendingSelectionContext,
}: AiConversationComposerDockProps) {
  const isExamQuestionContext = pendingSelectionContext?.source === AI_SOURCE_EXAM_QUESTION;

  return (
    <div className="shrink-0 border-t border-transparent bg-white dark:bg-slate-950">
      {isPlannerConversation ? (
        <div className="border-t border-amber-100 bg-amber-50/80 px-4 py-2 text-[12px] leading-relaxed text-amber-700">
          这是构建规划会话，可在这里回看；继续修改规划请回到构建页操作。
        </div>
      ) : null}
      {pendingSelectionContext ? (
        <div className="mx-auto max-w-3xl px-4 pt-3 md:px-8 xl:max-w-4xl 2xl:max-w-5xl">
          <div
            className={cn(
              "flex items-start gap-2 rounded-2xl border px-3 py-2.5 shadow-sm",
              isExamQuestionContext
                ? "border-violet-100 bg-violet-50/80 text-violet-950 dark:border-violet-500/20 dark:bg-violet-500/10 dark:text-violet-100"
                : "border-sky-100 bg-sky-50/80 text-sky-900 dark:border-sky-500/20 dark:bg-sky-500/10 dark:text-sky-100",
            )}
          >
            <MessageSquareText
              className={cn(
                "mt-0.5 h-4 w-4 shrink-0",
                isExamQuestionContext ? "text-violet-600" : "text-sky-600",
              )}
            />
            <div className="min-w-0 flex-1">
              <p className="text-[12px] font-semibold">
                {isExamQuestionContext ? "已附加这道题的上下文" : "已附加原文与相关上下文"}
              </p>
              <p
                className={cn(
                  "mt-0.5 text-[11px] leading-4",
                  isExamQuestionContext
                    ? "text-violet-600 dark:text-violet-200/80"
                    : "text-sky-600 dark:text-sky-200/80",
                )}
              >
                {isExamQuestionContext
                  ? "将结合题干、选项和当前作答状态回答；未批改时不会主动泄露标准答案。"
                  : "将结合选中片段、所在段落和相关资料回答。"}
              </p>
              <AiConversationSelectionTextPreview
                prefix={isExamQuestionContext ? "题目：" : "选中："}
                text={pendingSelectionContext.selectedText}
                placement="above"
                className={cn(
                  "mt-1 text-[12px] leading-5",
                  isExamQuestionContext
                    ? "text-violet-700 dark:text-violet-100/90"
                    : "text-sky-700 dark:text-sky-100/90",
                )}
              />
            </div>
            <button
              type="button"
              onClick={onClearPendingSelectionContext}
              className={cn(
                "inline-flex h-7 w-7 shrink-0 items-center justify-center rounded-lg transition",
                isExamQuestionContext
                  ? "text-violet-500 hover:bg-violet-100 hover:text-violet-800"
                  : "text-sky-500 hover:bg-sky-100 hover:text-sky-800",
              )}
              aria-label="移除参考上下文"
              title="移除参考上下文"
            >
              <X className="h-3.5 w-3.5" />
            </button>
          </div>
        </div>
      ) : null}
      <ChatComposer
        value={draft}
        onChange={onDraftChange}
        onSend={onSend}
        onAbort={onAbort}
        isStreaming={isStreaming}
        disabled={disabled}
        autoFocusKey={autoFocusKey}
        modelValue={modelValue}
        onModelChange={onModelChange}
        placeholder={pendingSelectionContext ? (
          isExamQuestionContext ? "围绕这道题提问..." : "结合原文上下文提问..."
        ) : undefined}
      />
    </div>
  );
}
