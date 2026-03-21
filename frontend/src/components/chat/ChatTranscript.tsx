import { AlertCircle, Bot, Sparkles, UserRound } from "lucide-react";
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
    <div className="mx-auto flex w-full max-w-4xl flex-col gap-5 px-4 py-8 xl:px-8">
      {messages.map((message) => {
        const isAssistant = message.role === "assistant";
        return (
          <div
            key={message.localId}
            className={cn(
              "flex gap-4",
              isAssistant ? "rounded-[28px] bg-white/80 px-4 py-5 shadow-sm ring-1 ring-slate-200/70" : "",
            )}
          >
            <div
              className={cn(
                "flex h-11 w-11 shrink-0 items-center justify-center rounded-2xl text-white shadow-sm",
                isAssistant
                  ? "bg-gradient-to-br from-sky-500 via-cyan-500 to-blue-600"
                  : "bg-slate-900",
              )}
            >
              {isAssistant ? <Bot className="h-5 w-5" /> : <UserRound className="h-5 w-5" />}
            </div>

            <div className="min-w-0 flex-1 pt-1">
              <div className="mb-2 flex items-center gap-2 text-xs font-medium uppercase tracking-[0.18em] text-slate-400">
                {isAssistant ? <Sparkles className="h-3.5 w-3.5" /> : null}
                <span>{isAssistant ? "Tutor" : "You"}</span>
              </div>

              {isAssistant ? (
                <div className="text-[15px] leading-7 text-slate-800">
                  <MarkdownViewer content={message.content || " "} />
                  {message.status === "streaming" ? (
                    <span className="ml-0.5 inline-block h-4 w-0.5 animate-pulse bg-slate-500 align-middle" />
                  ) : null}
                </div>
              ) : (
                <p className="whitespace-pre-wrap text-[15px] leading-7 text-slate-800">
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
        );
      })}
    </div>
  );
}
