import { useEffect, useRef, useState } from "react";
import {
  BookOpenText,
  Loader2,
  MessageSquareText,
  RotateCcw,
  Sparkles,
  Trash2,
} from "lucide-react";
import { useParams } from "react-router-dom";
import { ChatCitationModal } from "../components/chat/ChatCitationModal";
import { ChatComposer } from "../components/chat/ChatComposer";
import { ChatTranscript } from "../components/chat/ChatTranscript";
import { Button } from "../components/ui/Button";
import { Card, CardContent } from "../components/ui/Card";
import { useChatSession } from "../hooks/useChatSession";

const SUGGESTIONS = [
  "请帮我先概括这份资料的核心结构",
  "这部分内容我不太懂，请你一步一步讲清楚",
  "请结合资料说明这个概念和它的应用场景",
];

export function ChatPage() {
  const { subjectId = "" } = useParams();
  const [draft, setDraft] = useState("");
  const [selectedChunkId, setSelectedChunkId] = useState<number | null>(null);
  const scrollAnchorRef = useRef<HTMLDivElement>(null);
  const { messages, historyLoaded, historyError, isStreaming, sendMessage, abortStream, clearHistory } =
    useChatSession(subjectId);

  useEffect(() => {
    scrollAnchorRef.current?.scrollIntoView({ behavior: "smooth", block: "end" });
  }, [messages]);

  async function handleSend() {
    const result = await sendMessage({ question: draft });
    if (result.accepted) {
      setDraft("");
    }
  }

  function handleSuggestionClick(text: string) {
    setDraft(text);
  }

  const hasMessages = messages.length > 0;

  return (
    <>
      <div className="relative -m-6 min-h-[calc(100vh-4rem)] bg-zinc-50 px-4 py-6 lg:-m-8 lg:px-8 lg:py-8">
        <div className="pointer-events-none absolute inset-0 z-0 flex justify-center overflow-hidden">
          <div className="h-full w-full bg-[linear-gradient(to_right,#e4e4e7_1px,transparent_1px),linear-gradient(to_bottom,#e4e4e7_1px,transparent_1px)] bg-[size:32px_32px] [mask-image:radial-gradient(ellipse_120%_100%_at_50%_0%,#000_50%,transparent_100%)]"></div>
        </div>
        <div className="relative z-10 grid min-h-[calc(100vh-7rem)] gap-6 xl:grid-cols-[300px_minmax(0,1fr)]">
          <aside className="space-y-4">
            <Card className="overflow-hidden rounded-2xl border border-zinc-900 bg-zinc-900 text-white shadow-lg">
              <CardContent className="space-y-4 p-5">
                <div className="inline-flex h-10 w-10 items-center justify-center rounded-lg bg-white/10 shadow-inner">
                  <Sparkles className="h-5 w-5" />
                </div>
                <div>
                  <h1 className="text-xl font-semibold tracking-tight">教学对话</h1>
                  <p className="mt-2 text-[13px] leading-relaxed text-zinc-300">
                    先做可用版的赛博私教。现在已经支持流式回答、基于知识切块的引用来源，以及引用原文查看。
                  </p>
                </div>
              </CardContent>
            </Card>

            <Card className="rounded-2xl border border-zinc-200/60 bg-white shadow-[0_2px_8px_rgba(0,0,0,0.04)]">
              <CardContent className="space-y-3 p-5">
                <div className="flex items-center gap-2 text-[13px] font-semibold text-zinc-800">
                  <BookOpenText className="h-4 w-4 text-zinc-500" />
                  现在能做什么
                </div>
                <ul className="space-y-2 text-[13px] leading-relaxed text-zinc-600">
                  <li>结合当前学科材料做解释型回答</li>
                  <li>流式输出，避免长时间空白等待</li>
                  <li>展示引用切块，并可点开查看原文</li>
                </ul>
              </CardContent>
            </Card>

            <Card className="rounded-2xl border border-zinc-200/60 bg-white shadow-[0_2px_8px_rgba(0,0,0,0.04)]">
              <CardContent className="space-y-3 p-5">
                <div className="flex items-center gap-2 text-[13px] font-semibold text-zinc-800">
                  <MessageSquareText className="h-4 w-4 text-zinc-500" />
                  快速开始
                </div>
                <div className="space-y-2">
                  {SUGGESTIONS.map((suggestion) => (
                    <button
                      key={suggestion}
                      type="button"
                      onClick={() => handleSuggestionClick(suggestion)}
                      className="w-full rounded-xl border border-zinc-200/60 bg-zinc-50 px-3 py-2.5 text-left text-[13px] leading-relaxed text-zinc-600 transition-colors hover:border-zinc-300 hover:bg-white hover:text-zinc-900 shadow-[inset_0_1px_2px_rgba(0,0,0,0.01)]"
                    >
                      {suggestion}
                    </button>
                  ))}
                </div>
              </CardContent>
            </Card>
          </aside>

          <section className="relative flex min-h-0 flex-col overflow-hidden rounded-2xl border border-zinc-300/80 bg-white/95 shadow-[0_12px_32px_-12px_rgba(0,0,0,0.12),0_4px_12px_-4px_rgba(0,0,0,0.08)] backdrop-blur-xl">
            <div className="flex flex-wrap items-center justify-between gap-3 border-b border-zinc-100 bg-white/50 px-5 py-4 xl:px-6">
              <div>
                <div className="text-[11px] font-semibold uppercase tracking-widest text-zinc-400">
                  Interact
                </div>
                <h2 className="mt-1 text-base font-semibold tracking-tight text-zinc-900">
                  学习对话工作流
                </h2>
              </div>

              <div className="flex items-center gap-2">
                {isStreaming ? (
                  <Button
                    type="button"
                    variant="outline"
                    onClick={abortStream}
                    className="h-8 rounded-lg border-zinc-200 text-[13px] text-zinc-600 hover:bg-zinc-50"
                  >
                    <RotateCcw className="mr-1.5 h-3.5 w-3.5" />
                    停止回答
                  </Button>
                ) : null}
                <Button
                  type="button"
                  variant="outline"
                  onClick={clearHistory}
                  className="h-8 rounded-lg border-zinc-200 text-[13px] text-zinc-600 hover:bg-zinc-50"
                >
                  <Trash2 className="mr-1.5 h-3.5 w-3.5" />
                  清空记录
                </Button>
              </div>
            </div>

            {historyError ? (
              <div className="border-b border-red-100 bg-red-50/80 px-5 py-3 text-[13px] text-red-600 xl:px-6">
                {historyError}
              </div>
            ) : null}

            <div className="min-h-0 flex-1 overflow-y-auto pb-40">
              {!historyLoaded ? (
                <div className="flex h-full items-center justify-center text-[13px] text-zinc-500">
                  <Loader2 className="mr-2 h-4 w-4 animate-spin text-zinc-400" />
                  正在加载聊天记录...
                </div>
              ) : hasMessages ? (
                <>
                  <ChatTranscript
                    messages={messages}
                    onOpenCitation={(chunkId) => setSelectedChunkId(chunkId)}
                  />
                  <div ref={scrollAnchorRef} />
                </>
              ) : (
                <div className="flex h-full items-center justify-center px-4 py-10">
                  <div className="max-w-xl text-center">
                    <div className="mx-auto inline-flex h-14 w-14 items-center justify-center rounded-2xl border border-zinc-200/60 bg-white text-zinc-600 shadow-[0_2px_8px_rgba(0,0,0,0.04)]">
                      <MessageSquareText className="h-6 w-6" />
                    </div>
                    <h3 className="mt-5 text-xl font-semibold tracking-tight text-zinc-900">
                      开始第一轮教学对话
                    </h3>
                    <p className="mt-2.5 text-[14px] leading-relaxed text-zinc-500">
                      你可以直接提问，也可以让我先概括材料、解释某个知识点，或者按步骤带你一起推导。
                    </p>
                  </div>
                </div>
              )}
            </div>

            <ChatComposer
              value={draft}
              onChange={setDraft}
              onSend={handleSend}
              onAbort={abortStream}
              isStreaming={isStreaming}
              disabled={!subjectId}
            />
          </section>
        </div>
      </div>

      <ChatCitationModal
        open={selectedChunkId !== null}
        onClose={() => setSelectedChunkId(null)}
        subject={subjectId}
        chunkId={selectedChunkId}
      />
    </>
  );
}
