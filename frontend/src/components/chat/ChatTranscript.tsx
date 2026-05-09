import { memo, useEffect, useMemo, useState } from "react";
import { AlertCircle, ChevronRight, Loader2 } from "lucide-react";
import type { ChatContextItem } from "../../api/generated/model";
import { type ChatSessionMessage } from "../../hooks/useChatSession";
import { cn } from "../../lib/utils";
import { ChatCitationList } from "./ChatCitationList";
import { MarkdownViewer } from "../ui/MarkdownViewer";

interface ChatTranscriptProps {
  messages: ChatSessionMessage[];
  onOpenCitation: (context: ChatContextItem) => void;
}

export const ChatTranscript = memo(function ChatTranscript({ messages, onOpenCitation }: ChatTranscriptProps) {
  const hasStreamingAssistant = useMemo(
    () => messages.some((message) => message.role === "assistant" && message.status === "streaming"),
    [messages],
  );
  const [nowMs, setNowMs] = useState(() => Date.now());

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
    <div className="mx-auto flex w-full max-w-3xl flex-col gap-7 px-4 py-8 md:px-8 xl:max-w-4xl 2xl:max-w-5xl">
      {messages.map((message) => {
        const isAssistant = message.role === "assistant";

        if (isAssistant) {
          const learningStatus = getAssistantLearningStatus(message, nowMs);

          return (
            <div key={message.localId} className="flex w-full justify-start">
              <div className="min-w-0 w-full max-w-[min(780px,100%)] px-1">
                <div className="mb-3 flex max-w-full items-center gap-1.5 text-[13px] leading-none text-zinc-400 dark:text-slate-500">
                  {message.status === "streaming" ? (
                    <Loader2 className="h-3.5 w-3.5 shrink-0 animate-spin" />
                  ) : null}
                  <span>{learningStatus.label}</span>
                  {learningStatus.elapsed ? (
                    <span>{learningStatus.elapsed}</span>
                  ) : null}
                  <ChevronRight className="h-3.5 w-3.5 shrink-0" />
                  {message.statusDetail ? (
                    <>
                      <span className="mx-1 h-1 w-1 shrink-0 rounded-full bg-zinc-300 dark:bg-slate-600" />
                      <span className="truncate">{message.statusDetail}</span>
                    </>
                  ) : null}
                </div>

                <div className="max-w-none text-[15px] leading-7 text-zinc-900 dark:text-slate-100">
                  <MarkdownViewer content={message.content || " "} />
                  {message.status === "streaming" ? (
                    <span className="ml-0.5 inline-block h-4 w-0.5 animate-pulse bg-zinc-500 align-middle dark:bg-slate-400" />
                  ) : null}
                </div>

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
                  />
                ) : null}
              </div>
            </div>
          );
        }

        return (
          <div key={message.localId} className="flex w-full justify-end">
            <div className="max-w-[min(680px,82%)]">
              <p className="whitespace-pre-wrap rounded-[22px] bg-zinc-950 px-4 py-2.5 text-[14px] font-medium leading-6 text-white shadow-[0_16px_36px_-26px_rgba(24,24,27,0.95)] dark:bg-slate-100 dark:text-slate-950 dark:shadow-[0_18px_30px_-24px_rgba(255,255,255,0.22)] sm:px-5">
                {message.content}
              </p>

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

function getAssistantLearningStatus(
  message: ChatSessionMessage,
  nowMs: number,
): { label: string; elapsed: string | null } {
  const elapsedMs = getAssistantElapsedMs(message, nowMs);
  const elapsed = formatElapsed(elapsedMs);

  if (message.status === "streaming") {
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
