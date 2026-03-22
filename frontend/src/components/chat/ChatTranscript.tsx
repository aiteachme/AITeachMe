import { AlertCircle, Sparkles, UserRound } from "lucide-react";
import { type ChatSessionMessage } from "../../hooks/useChatSession";
import { cn } from "../../lib/utils";
import { ChatCitationList } from "./ChatCitationList";
import { MarkdownViewer } from "../ui/MarkdownViewer";

interface ChatTranscriptProps {
  messages: ChatSessionMessage[];
  onOpenCitation: (chunkId: number) => void;
}

export function ChatTranscript({ messages, onOpenCitation }: ChatTranscriptProps) {
  return (
    <div className="mx-auto flex w-full max-w-3xl flex-col gap-5 px-4 py-8 md:px-6">
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
                "flex w-full gap-3",
                isAssistant ? "max-w-[95%] items-start" : "max-w-[85%] flex-row-reverse items-end",
              )}
            >
              <div
                className={cn(
                  "flex h-10 w-10 shrink-0 items-center justify-center text-white shadow-sm",
                  isAssistant
                    ? "rounded-full bg-gradient-to-br from-emerald-500 via-teal-500 to-cyan-600 ring-4 ring-emerald-100/80"
                    : "rounded-full bg-slate-900",
                )}
              >
                {isAssistant ? <Sparkles className="h-4 w-4" /> : <UserRound className="h-4 w-4" />}
              </div>

              <div className="min-w-0 flex-1">
                <div
                  className={cn(
                    "mb-1.5 flex items-center gap-2 text-[11px] font-medium tracking-[0.12em]",
                    isAssistant ? "text-emerald-600/90" : "justify-end text-slate-400",
                  )}
                >
                  {isAssistant ? <Sparkles className="h-3.5 w-3.5" /> : null}
                  <span>{isAssistant ? "AI Tutor" : "You"}</span>
                </div>

                {isAssistant ? (
                  <div className="rounded-2xl bg-white/80 px-4 py-3 text-[15px] leading-7 text-slate-800 shadow-[0_10px_35px_-24px_rgba(15,23,42,0.42)]">
                    <MarkdownViewer content={message.content || " "} />
                    {message.status === "streaming" ? (
                      <span className="ml-0.5 inline-block h-4 w-0.5 animate-pulse bg-slate-500 align-middle" />
                    ) : null}
                  </div>
                ) : (
                  <p className="whitespace-pre-wrap rounded-3xl bg-slate-900 px-4 py-3 text-[15px] leading-7 text-slate-100 shadow-[0_10px_28px_-20px_rgba(15,23,42,0.6)]">
                    {message.content}
                  </p>
                )}

                {message.errorDetail ? (
                  <div
                    className={cn(
                      "mt-3 inline-flex items-center gap-2 rounded-2xl px-3 py-2 text-sm",
                      message.status === "interrupted"
                        ? "bg-amber-50 text-amber-700"
                        : "bg-rose-50 text-rose-600",
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
}
