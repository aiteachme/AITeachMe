import { memo, useCallback, useEffect, useMemo, useState } from "react";
import { AlertCircle, Check, ChevronRight, Copy, Loader2, Paperclip, SquareTerminal } from "lucide-react";
import type { ChatContextItem } from "../../api/generated/model";
import { type ChatClientAction, type ChatMessageToolRun, type ChatSessionMessage } from "../../hooks/useChatSession";
import { cn } from "../../lib/utils";
import { ChatCitationList } from "./ChatCitationList";
import { MarkdownViewer } from "../ui/MarkdownViewer";

interface ChatTranscriptProps {
  messages: ChatSessionMessage[];
  onOpenCitation: (context: ChatContextItem) => void;
  onSubmitClientActionOption?: (value: string) => void;
  presentation?: "sidebar" | "fullscreen";
}

export const ChatTranscript = memo(function ChatTranscript({
  messages,
  onOpenCitation,
  onSubmitClientActionOption,
  presentation = "fullscreen",
}: ChatTranscriptProps) {
  const hasStreamingAssistant = useMemo(
    () => messages.some((message) => message.role === "assistant" && message.status === "streaming"),
    [messages],
  );
  const [nowMs, setNowMs] = useState(() => Date.now());
  const [copiedMessageId, setCopiedMessageId] = useState<string | null>(null);
  const isSidebar = presentation === "sidebar";

  const handleCopyMessage = useCallback(async (message: ChatSessionMessage) => {
    const text = message.content.trim();
    if (!text) {
      return;
    }
    try {
      await copyTextToClipboard(text);
      setCopiedMessageId(message.localId);
      window.setTimeout(() => {
        setCopiedMessageId((current) => current === message.localId ? null : current);
      }, 1400);
    } catch {
      setCopiedMessageId(null);
    }
  }, []);

  useEffect(() => {
    if (!hasStreamingAssistant) {
      return;
    }
    setNowMs(Date.now());
    const timerId = window.setInterval(() => {
      setNowMs(Date.now());
    }, 1000);
    return () => window.clearInterval(timerId);
  }, [hasStreamingAssistant]);

  return (
    <div
      className={cn(
        "mx-auto flex w-full flex-col",
        isSidebar
          ? "max-w-none gap-5 px-3 py-5"
          : "max-w-3xl gap-7 px-4 py-8 md:px-8 xl:max-w-4xl 2xl:max-w-5xl",
      )}
    >
      {messages.map((message) => {
        const isAssistant = message.role === "assistant";

        if (isAssistant) {
          const learningStatus = getAssistantLearningStatus(message, nowMs);
          const showStatusDetail = Boolean(
            message.statusDetail && !message.statusStage?.startsWith("tool_call_"),
          );

          return (
            <div key={message.localId} className="group/message flex w-full justify-start">
              <div className={cn(
                "min-w-0 w-full max-w-[min(780px,100%)]",
                isSidebar ? "px-0" : "px-1",
              )}>
                <div className="mb-3 flex max-w-full items-center gap-1.5 text-[13px] leading-none text-zinc-400 dark:text-slate-500">
                  {message.status === "streaming" ? (
                    <Loader2 className="h-3.5 w-3.5 shrink-0 animate-spin" />
                  ) : null}
                  <span>{learningStatus.label}</span>
                  {learningStatus.elapsed ? (
                    <span>{learningStatus.elapsed}</span>
                  ) : null}
                  {showStatusDetail ? (
                    <>
                      <ChevronRight className="h-3.5 w-3.5 shrink-0" />
                      <span className="mx-1 h-1 w-1 shrink-0 rounded-full bg-zinc-300 dark:bg-slate-600" />
                      <span className="truncate">{message.statusDetail}</span>
                    </>
                  ) : null}
                </div>

                <div className="max-w-none text-[15px] leading-7 text-zinc-900 dark:text-slate-100">
                  <AssistantMessageBody message={message} />
                  {message.status === "streaming" ? (
                    <span className="ml-0.5 inline-block h-4 w-0.5 animate-pulse bg-zinc-500 align-middle dark:bg-slate-400" />
                  ) : null}
                </div>

                <AssistantClientActions
                  actions={message.clientActions ?? []}
                  onSubmitOption={onSubmitClientActionOption}
                />

                <MessageCopyControls
                  align="start"
                  copied={copiedMessageId === message.localId}
                  disabled={!message.content.trim() || message.status === "streaming"}
                  onCopy={() => void handleCopyMessage(message)}
                />

                {message.errorDetail ? (
                  <div
                    className={cn(
                      "mt-3 inline-flex items-center gap-2 rounded-2xl px-3 py-2 text-sm",
                      message.status === "interrupted"
                        ? "bg-amber-50 text-amber-700 dark:bg-amber-500/10 dark:text-amber-300"
                        : "bg-rose-50 text-rose-600 dark:bg-rose-500/10 dark:text-rose-300",
                    )}
                  >
                    <AlertCircle className="h-4 w-4" />
                    <span>{message.errorDetail}</span>
                  </div>
                ) : null}

                {message.contexts?.length ? (
                  <ChatCitationList
                    contexts={message.contexts}
                    onOpenContext={onOpenCitation}
                    variant={isSidebar ? "compact" : "default"}
                  />
                ) : null}
              </div>
            </div>
          );
        }

        return (
          <div key={message.localId} className="group/message flex w-full justify-end">
            <div className={cn(isSidebar ? "max-w-[88%]" : "max-w-[min(680px,82%)]")}>
              <p className="whitespace-pre-wrap rounded-[22px] bg-zinc-950 px-4 py-2.5 text-[14px] font-medium leading-6 text-white shadow-[0_16px_36px_-26px_rgba(24,24,27,0.95)] dark:bg-slate-100 dark:text-slate-950 dark:shadow-[0_18px_30px_-24px_rgba(255,255,255,0.22)] sm:px-5">
                {message.content}
              </p>
              {getAttachedFileCount(message) > 0 ? (
                <div className="mt-1.5 flex justify-end pr-1">
                  <span className="inline-flex h-6 items-center gap-1.5 rounded-full border border-zinc-200 bg-white/85 px-2.5 text-[11px] font-medium text-zinc-500 shadow-sm dark:border-slate-800 dark:bg-slate-900/85 dark:text-slate-400">
                    <Paperclip className="h-3 w-3" strokeWidth={2} />
                    已附加 {getAttachedFileCount(message)} 份资料
                  </span>
                </div>
              ) : null}

              <MessageCopyControls
                align="end"
                copied={copiedMessageId === message.localId}
                disabled={!message.content.trim()}
                onCopy={() => void handleCopyMessage(message)}
              />

              {message.errorDetail ? (
                <div
                  className={cn(
                    "mt-3 inline-flex items-center gap-2 rounded-2xl px-3 py-2 text-sm",
                    message.status === "interrupted"
                      ? "bg-amber-50 text-amber-700 dark:bg-amber-500/10 dark:text-amber-300"
                      : "bg-rose-50 text-rose-600 dark:bg-rose-500/10 dark:text-rose-300",
                  )}
                >
                  <AlertCircle className="h-4 w-4" />
                  <span>{message.errorDetail}</span>
                </div>
              ) : null}
            </div>
          </div>
        );
      })}
    </div>
  );
});

function getAttachedFileCount(message: ChatSessionMessage): number {
  return message.attachedFileCount ?? message.attachedFileIds?.length ?? 0;
}

function MessageCopyControls({
  align,
  copied,
  disabled,
  onCopy,
}: {
  align: "start" | "end";
  copied: boolean;
  disabled: boolean;
  onCopy: () => void;
}) {
  if (disabled) {
    return null;
  }
  return (
    <div
      className={cn(
        "mt-1.5 flex h-7 items-center opacity-100 transition sm:opacity-0 sm:group-hover/message:opacity-100 sm:focus-within:opacity-100",
        align === "end" ? "justify-end pr-1" : "justify-start pl-1",
      )}
    >
      <button
        type="button"
        onClick={onCopy}
        className="inline-flex h-7 w-7 items-center justify-center rounded-md text-zinc-400 transition hover:bg-zinc-100 hover:text-zinc-900 focus:outline-none focus:ring-4 focus:ring-zinc-900/10 dark:hover:bg-slate-800 dark:hover:text-slate-100"
        title={copied ? "已复制" : "复制"}
        aria-label={copied ? "已复制" : "复制消息"}
      >
        {copied ? <Check className="h-3.5 w-3.5" /> : <Copy className="h-3.5 w-3.5" />}
      </button>
    </div>
  );
}

async function copyTextToClipboard(text: string): Promise<void> {
  if (typeof navigator !== "undefined" && navigator.clipboard?.writeText) {
    await navigator.clipboard.writeText(text);
    return;
  }
  if (typeof document === "undefined") {
    throw new Error("Clipboard API is unavailable");
  }

  const textarea = document.createElement("textarea");
  textarea.value = text;
  textarea.setAttribute("readonly", "true");
  textarea.style.position = "fixed";
  textarea.style.left = "-9999px";
  textarea.style.top = "0";
  document.body.appendChild(textarea);
  textarea.select();
  document.execCommand("copy");
  document.body.removeChild(textarea);
}

function AssistantMessageBody({ message }: { message: ChatSessionMessage }) {
  const parts = splitContentWithToolRuns(message.content, message.toolRuns ?? []);
  if (!parts.length) {
    return <MarkdownViewer content=" " />;
  }
  return (
    <>
      {parts.map((part) => {
        if (part.type === "tool") {
          return (
            <ToolRunMarker
              key={`tool-${part.position}-${part.runs.map((run) => run.id).join("-")}`}
              runs={part.runs}
            />
          );
        }
        return <MarkdownViewer key={`text-${part.index}`} content={part.content || " "} />;
      })}
    </>
  );
}

function AssistantClientActions({
  actions,
  onSubmitOption,
}: {
  actions: ChatClientAction[];
  onSubmitOption?: (value: string) => void;
}) {
  const askActions = actions
    .map(parseAskUserOptionsAction)
    .filter((action): action is AskUserOptionsAction => action !== null);
  if (!askActions.length) {
    return null;
  }
  return (
    <div className="mt-3 space-y-3">
      {askActions.map((action, index) => (
        <AskUserOptionsPanel
          key={`${action.question}-${index}`}
          action={action}
          onSubmitOption={onSubmitOption}
        />
      ))}
    </div>
  );
}

interface AskUserOptionsAction {
  question: string;
  options: AskUserOption[];
  allowCustomResponse: boolean;
}

interface AskUserOption {
  id: string;
  label: string;
  value: string;
  description: string;
}

function AskUserOptionsPanel({
  action,
  onSubmitOption,
}: {
  action: AskUserOptionsAction;
  onSubmitOption?: (value: string) => void;
}) {
  const [selectedId, setSelectedId] = useState<string | null>(null);
  return (
    <div className="max-w-xl space-y-2">
      {action.question ? (
        <div className="text-[13px] leading-5 text-zinc-500 dark:text-slate-400">
          {action.question}
        </div>
      ) : null}
      <div className="flex flex-wrap gap-2">
        {action.options.map((option) => {
          const selected = selectedId === option.id;
          return (
            <button
              key={option.id}
              type="button"
              disabled={!onSubmitOption || selectedId !== null}
              onClick={() => {
                setSelectedId(option.id);
                onSubmitOption?.(option.value || option.label);
              }}
              className={cn(
                "inline-flex max-w-full flex-col rounded-lg border px-3 py-2 text-left text-[13px] leading-5 transition",
                selected
                  ? "border-zinc-950 bg-zinc-950 text-white dark:border-slate-100 dark:bg-slate-100 dark:text-slate-950"
                  : "border-zinc-200 bg-zinc-50 text-zinc-700 hover:border-zinc-300 hover:bg-white disabled:cursor-default disabled:opacity-70 dark:border-slate-800 dark:bg-slate-900/60 dark:text-slate-200 dark:hover:border-slate-700 dark:hover:bg-slate-900",
              )}
              title={option.description || option.label}
            >
              <span className="truncate font-medium">{option.label}</span>
              {option.description ? (
                <span className={cn(
                  "mt-0.5 max-w-full truncate text-[12px]",
                  selected ? "text-white/75 dark:text-slate-700" : "text-zinc-400 dark:text-slate-500",
                )}>
                  {option.description}
                </span>
              ) : null}
            </button>
          );
        })}
      </div>
      {action.allowCustomResponse ? (
        <div className="text-[12px] leading-5 text-zinc-400 dark:text-slate-500">
          {"\u4e5f\u53ef\u4ee5\u76f4\u63a5\u5728\u8f93\u5165\u6846\u91cc\u56de\u590d\u5176\u4ed6\u60f3\u6cd5"}
        </div>
      ) : null}
    </div>
  );
}

function parseAskUserOptionsAction(action: ChatClientAction): AskUserOptionsAction | null {
  if (action.type !== "ask_user_options" || !isRecord(action.payload)) {
    return null;
  }
  const question = typeof action.payload.question === "string" ? action.payload.question.trim() : "";
  const options = parseAskUserOptions(action.payload.options);
  if (options.length === 0) {
    return null;
  }
  return {
    question,
    options,
    allowCustomResponse: action.payload.allow_custom_response !== false,
  };
}

function parseAskUserOptions(value: unknown): AskUserOption[] {
  if (!Array.isArray(value)) {
    return [];
  }
  return value
    .map((item, index): AskUserOption | null => {
      if (typeof item === "string") {
        const label = item.trim();
        return label
          ? { id: `option_${index + 1}`, label, value: label, description: "" }
          : null;
      }
      if (!isRecord(item)) {
        return null;
      }
      const label = stringField(item, "label") ?? stringField(item, "text") ?? stringField(item, "value");
      if (!label) {
        return null;
      }
      return {
        id: stringField(item, "id") ?? `option_${index + 1}`,
        label,
        value: stringField(item, "value") ?? label,
        description: stringField(item, "description") ?? stringField(item, "detail") ?? "",
      };
    })
    .filter((item): item is AskUserOption => item !== null)
    .slice(0, 6);
}

function stringField(record: Record<string, unknown>, key: string): string | null {
  const value = record[key];
  return typeof value === "string" && value.trim() ? value.trim() : null;
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null;
}

type AssistantBodyPart =
  | { type: "text"; index: number; content: string }
  | { type: "tool"; position: number; runs: ChatMessageToolRun[] };

function splitContentWithToolRuns(content: string, toolRuns: ChatMessageToolRun[]): AssistantBodyPart[] {
  const sortedRuns = [...toolRuns]
    .filter((run) => Number.isFinite(run.position))
    .sort((a, b) => a.position - b.position);
  if (!sortedRuns.length) {
    return content ? [{ type: "text", index: 0, content }] : [];
  }

  const parts: AssistantBodyPart[] = [];
  let cursor = 0;
  let textIndex = 0;
  let index = 0;
  while (index < sortedRuns.length) {
    const position = clampPosition(sortedRuns[index].position, content.length);
    if (position > cursor) {
      parts.push({ type: "text", index: textIndex, content: content.slice(cursor, position) });
      textIndex += 1;
    }
    const runsAtPosition: ChatMessageToolRun[] = [];
    while (index < sortedRuns.length && clampPosition(sortedRuns[index].position, content.length) === position) {
      runsAtPosition.push(sortedRuns[index]);
      index += 1;
    }
    parts.push({ type: "tool", position, runs: runsAtPosition });
    cursor = position;
  }
  if (cursor < content.length) {
    parts.push({ type: "text", index: textIndex, content: content.slice(cursor) });
  }
  return parts;
}

function clampPosition(position: number, contentLength: number): number {
  return Math.max(0, Math.min(contentLength, Math.round(position)));
}

function ToolRunMarker({ runs }: { runs: ChatMessageToolRun[] }) {
  const label = getToolRunMarkerLabel(runs);
  return (
    <div
      className="my-3 inline-flex max-w-full items-center gap-1.5 text-[13px] leading-none text-zinc-400 dark:text-slate-500"
      title={label}
    >
      <SquareTerminal className="h-3.5 w-3.5 shrink-0" />
      <span className="truncate">{label}</span>
    </div>
  );
}

function getToolRunMarkerLabel(runs: ChatMessageToolRun[]): string {
  if (runs.some((run) => run.detail?.trim() || run.toolDisplayName?.trim() || run.toolName?.trim())) {
    return getDetailedToolRunMarkerLabel(runs);
  }
  const runningCount = runs.filter((run) => run.status === "running").length;
  const failedCount = runs.filter((run) => run.status === "failed").length;
  const completedCount = runs.filter((run) => run.status === "completed").length;
  if (runningCount > 0) {
    return runningCount > 1 ? `正在运行 ${runningCount} 个工具` : "正在运行工具";
  }
  if (failedCount > 0 && completedCount === 0) {
    return failedCount > 1 ? `${failedCount} 个工具运行失败` : "工具运行失败";
  }
  const total = completedCount + failedCount;
  return total > 1 ? `已运行 ${total} 个工具` : "已运行工具";
}

const TOOL_DISPLAY_NAME_FALLBACKS: Record<string, string> = {
  web_search: "\u8054\u7f51\u641c\u7d22",
  recall_info: "\u56de\u5fc6\u7528\u6237\u4fe1\u606f",
  remember_info: "\u8bb0\u4f4f\u7528\u6237\u4fe1\u606f",
  search_kb: "\u68c0\u7d22\u8bfe\u7a0b\u77e5\u8bc6\u5e93",
  create_course_from_home_intake: "\u521b\u5efa\u5b66\u79d1",
  ask_user_options: "\u8be2\u95ee\u7528\u6237",
};

function getDetailedToolRunMarkerLabel(runs: ChatMessageToolRun[]): string {
  if (runs.length === 0) {
    return "\u5de5\u5177\u8c03\u7528";
  }
  if (runs.length === 1) {
    return getSingleToolRunMarkerLabel(runs[0]);
  }

  const runningCount = runs.filter((run) => run.status === "running").length;
  const failedCount = runs.filter((run) => run.status === "failed").length;
  const completedCount = runs.filter((run) => run.status === "completed").length;
  const total = runningCount + failedCount + completedCount;
  const toolNames = summarizeToolRunNames(runs);
  if (runningCount > 0) {
    return `\u6b63\u5728\u6267\u884c ${runningCount} \u4e2a\u5de5\u5177\uff1a${toolNames}`;
  }
  if (failedCount > 0 && completedCount === 0) {
    return `\u6267\u884c\u5931\u8d25 ${failedCount} \u4e2a\u5de5\u5177\uff1a${toolNames}`;
  }
  if (failedCount > 0) {
    return `\u5df2\u5b8c\u6210 ${completedCount} \u4e2a\u5de5\u5177\uff0c${failedCount} \u4e2a\u5931\u8d25\uff1a${toolNames}`;
  }
  return `\u5df2\u5b8c\u6210 ${total} \u4e2a\u5de5\u5177\uff1a${toolNames}`;
}

function getSingleToolRunMarkerLabel(run: ChatMessageToolRun): string {
  const detail = run.detail?.trim();
  if (detail) {
    return detail;
  }
  const toolName = getToolRunActionLabel(run);
  if (run.status === "running") {
    return `\u6b63\u5728\u6267\u884c\uff1a${toolName}`;
  }
  if (run.status === "failed") {
    return `\u6267\u884c\u5931\u8d25\uff1a${toolName}`;
  }
  return `\u5df2\u5b8c\u6210\uff1a${toolName}`;
}

function summarizeToolRunNames(runs: ChatMessageToolRun[]): string {
  const names = Array.from(new Set(runs.map(getToolRunActionLabel))).filter(Boolean);
  if (names.length === 0) {
    return "\u5de5\u5177\u8c03\u7528";
  }
  const visibleNames = names.slice(0, 3);
  const suffix = names.length > visibleNames.length
    ? `\u7b49 ${names.length} \u4e2a`
    : "";
  return `${visibleNames.join("\u3001")}${suffix}`;
}

function getToolRunActionLabel(run: ChatMessageToolRun): string {
  const displayName = run.toolDisplayName?.trim();
  if (displayName) {
    return displayName;
  }
  const toolName = run.toolName?.trim();
  if (toolName) {
    return TOOL_DISPLAY_NAME_FALLBACKS[toolName] ?? toolName;
  }
  return "\u5de5\u5177\u8c03\u7528";
}

function getAssistantLearningStatus(
  message: ChatSessionMessage,
  nowMs: number,
): { label: string; elapsed: string | null } {
  const elapsedMs = getAssistantElapsedMs(message, nowMs);
  const elapsed = formatElapsed(elapsedMs);

  if (message.status === "streaming") {
    if (message.content.trim()) {
      return { label: "正在生成回答", elapsed };
    }
    if (message.statusStage === "tool_call_started") {
      return { label: formatToolStatusLabel("正在", message.activeToolDisplayName), elapsed };
    }
    if (message.statusStage === "tool_call_completed") {
      return { label: formatToolStatusLabel("已完成", message.activeToolDisplayName), elapsed };
    }
    if (message.statusStage === "tool_call_failed") {
      return { label: formatToolStatusLabel("未完成", message.activeToolDisplayName), elapsed };
    }
    if (message.statusStage === "answering" && message.statusDetail?.includes("联网")) {
      return { label: "准备联网检索", elapsed };
    }
    if (message.statusStage === "answering" && message.statusDetail?.includes("课程")) {
      return { label: "准备检索资料", elapsed };
    }
    if (message.statusStage === "home_intake") {
      return { label: "正在理解需求", elapsed };
    }
    return { label: "正在梳理", elapsed };
  }
  if (message.status === "interrupted") {
    return { label: "已暂停梳理", elapsed };
  }
  if (message.status === "error") {
    return { label: "梳理遇到问题", elapsed };
  }
  return { label: "已梳理", elapsed };
}

function formatToolStatusLabel(prefix: string, toolDisplayName: string | null | undefined): string {
  const toolName = toolDisplayName?.trim();
  return toolName ? `${prefix}${toolName}` : `${prefix}使用工具`;
}

function getAssistantElapsedMs(message: ChatSessionMessage, nowMs: number): number | null {
  if (typeof message.elapsedMs === "number" && Number.isFinite(message.elapsedMs) && message.elapsedMs >= 0) {
    return message.elapsedMs;
  }
  if (message.status !== "streaming" || !message.createdAt) {
    return null;
  }
  const createdAtMs = Date.parse(message.createdAt);
  if (!Number.isFinite(createdAtMs) || nowMs < createdAtMs) {
    return null;
  }
  return nowMs - createdAtMs;
}

function formatElapsed(elapsedMs: number | null): string | null {
  if (elapsedMs === null) {
    return null;
  }
  const totalSeconds = Math.max(1, Math.round(elapsedMs / 1000));
  if (totalSeconds < 60) {
    return `${totalSeconds}s`;
  }
  const minutes = Math.floor(totalSeconds / 60);
  const seconds = totalSeconds % 60;
  return seconds > 0 ? `${minutes}m ${seconds}s` : `${minutes}m`;
}
