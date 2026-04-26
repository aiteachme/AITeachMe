import { memo } from "react";
import { AlertCircle, UserRound } from "lucide-react";
import { type ChatSessionMessage } from "../../hooks/useChatSession";
import { cn } from "../../lib/utils";
import { publicAssetPath } from "../../lib/publicAsset";
import { ChatCitationList } from "./ChatCitationList";
import { MarkdownViewer } from "../ui/MarkdownViewer";

const LOGO_SRC = publicAssetPath("logo.svg");

interface ChatTranscriptProps {
  messages: ChatSessionMessage[];
  onOpenCitation: (chunkId: number) => void;
}

export const ChatTranscript = memo(function ChatTranscript({ messages, onOpenCitation }: ChatTranscriptProps) {
  return (
    <div className="mx-auto flex w-full max-w-3xl flex-col gap-7 px-4 py-8 md:px-8 xl:max-w-4xl 2xl:max-w-5xl">
      {messages.map((message) => {
        const isAssistant = message.role === "assistant";
        return (
          <div
            key={message.localId}
            className={cn(
              "flex",
              isAssistant ? "justify-start" : "justify-end",
            )}
          >
            <div
              className={cn(
                "flex gap-3 sm:gap-4",
                isAssistant ? "w-full items-start" : "max-w-[82%] flex-row-reverse items-end",
              )}
            >
              <div
                className={cn(
                  "flex h-9 w-9 shrink-0 items-center justify-center shadow-sm sm:h-10 sm:w-10",
                  isAssistant
                    ? "rounded-full bg-slate-50 ring-2 ring-slate-200/50 p-1.5 dark:bg-slate-900 dark:ring-slate-700/70"
                    : "rounded-full bg-slate-900 text-white dark:bg-slate-100 dark:text-slate-900",
                )}
              >
                {isAssistant ? <img src={LOGO_SRC} alt="AI" className="h-full w-full object-contain" /> : <UserRound className="h-4 w-4" />}
              </div>

              <div className="min-w-0 flex-1">
                <div
                  className={cn(
                    "mb-1.5 flex items-center gap-2 text-[11px] font-medium tracking-[0.12em]",
                    isAssistant ? "text-emerald-600/90 dark:text-emerald-400/90" : "justify-end text-slate-400 dark:text-slate-500",
                  )}
                >
                  <span>{isAssistant ? "AITeachMe" : "You"}</span>
                </div>

                {isAssistant ? (
                  <div className="max-w-none px-1 py-1 text-[15px] leading-7 text-slate-800 dark:text-slate-100">
                    <MarkdownViewer content={message.content || " "} />
                    {message.status === "streaming" ? (
                      <span className="ml-0.5 inline-block h-4 w-0.5 animate-pulse bg-slate-500 align-middle dark:bg-slate-400" />
                    ) : null}
                  </div>
                ) : (
                  <p className="whitespace-pre-wrap rounded-3xl bg-slate-900 px-4 py-3 text-[15px] leading-7 text-slate-100 shadow-[0_10px_28px_-20px_rgba(15,23,42,0.6)] dark:bg-slate-100 dark:text-slate-900 dark:shadow-[0_18px_30px_-24px_rgba(255,255,255,0.22)]">
                    {message.content}
                  </p>
                )}

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

                {isAssistant && message.contexts?.length ? (
                  <ChatCitationList
                    contexts={message.contexts}
                    onOpenContext={onOpenCitation}
                  />
                ) : null}
              </div>
            </div>
          </div>
        );
      })}
    </div>
  );
});
