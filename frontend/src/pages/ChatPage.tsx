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
      <div className="-m-6 min-h-[calc(100vh-4rem)] bg-[radial-gradient(circle_at_top,_rgba(120,113,108,0.08),_transparent_40%),linear-gradient(180deg,_#fcfcfc_0%,_#f7f7f5_60%,_#f0eee9_100%)] px-4 py-6 lg:-m-8 lg:px-8 lg:py-8">
        <div className="grid min-h-[calc(100vh-7rem)] gap-6 xl:grid-cols-[320px_minmax(0,1fr)]">
          <aside className="space-y-4">
            <Card className="overflow-hidden border-0 bg-slate-900 text-white shadow-[0_24px_80px_-40px_rgba(15,23,42,0.8)]">
              <CardContent className="space-y-4 p-6">
                <div className="inline-flex h-12 w-12 items-center justify-center rounded-2xl bg-white/10">
                  <Sparkles className="h-6 w-6" />
                </div>
                <div>
                  <h1 className="text-2xl font-semibold tracking-tight">教学对话</h1>
                  <p className="mt-2 text-sm leading-6 text-slate-300">
                    先做可用版的赛博私教。现在已经支持流式回答、基于知识切块的引用来源，以及引用原文查看。
                  </p>
                </div>
              </CardContent>
            </Card>

            <Card className="border-white/70 bg-white/85 shadow-[0_20px_70px_-45px_rgba(15,23,42,0.55)]">
              <CardContent className="space-y-3 p-5">
                <div className="flex items-center gap-2 text-sm font-semibold text-slate-800">
                  <BookOpenText className="h-4 w-4 text-sky-600" />
                  现在能做什么
                </div>
                <ul className="space-y-2 text-sm leading-6 text-slate-600">
                  <li>结合当前学科材料做解释型回答</li>
                  <li>流式输出，避免长时间空白等待</li>
                  <li>展示引用切块，并可点开查看原文</li>
                </ul>
              </CardContent>
            </Card>

            <Card className="border-white/70 bg-white/85 shadow-[0_20px_70px_-45px_rgba(15,23,42,0.55)]">
              <CardContent className="space-y-3 p-5">
                <div className="flex items-center gap-2 text-sm font-semibold text-slate-800">
                  <MessageSquareText className="h-4 w-4 text-stone-600" />
                  快速开始
                </div>
                <div className="space-y-2">
                  {SUGGESTIONS.map((suggestion) => (
                    <button
                      key={suggestion}
                      type="button"
                      onClick={() => handleSuggestionClick(suggestion)}
                      className="w-full rounded-2xl border border-slate-200 bg-slate-50 px-4 py-3 text-left text-sm leading-6 text-slate-600 transition hover:border-sky-200 hover:bg-sky-50 hover:text-slate-800"
                    >
                      {suggestion}
                    </button>
                  ))}
                </div>
              </CardContent>
            </Card>
          </aside>

          <section className="flex min-h-0 flex-col overflow-hidden rounded-[32px] border border-white/80 bg-white/75 shadow-[0_24px_90px_-48px_rgba(15,23,42,0.45)] backdrop-blur-xl">
            <div className="flex flex-wrap items-center justify-between gap-3 border-b border-slate-200/80 px-5 py-4 xl:px-8">
              <div>
                <div className="text-xs font-medium uppercase tracking-[0.2em] text-slate-400">
                  Interact
                </div>
                <h2 className="mt-1 text-lg font-semibold text-slate-900">
                  学习对话工作流
                </h2>
              </div>

              <div className="flex items-center gap-2">
                {isStreaming ? (
                  <Button
                    type="button"
                    variant="outline"
                    onClick={abortStream}
                    className="border-rose-200 text-rose-600 hover:bg-rose-50"
                  >
                    <RotateCcw className="h-4 w-4" />
                    停止回答
                  </Button>
                ) : null}
                <Button
                  type="button"
                  variant="outline"
                  onClick={clearHistory}
                  className="border-slate-200 text-slate-600 hover:bg-slate-50"
                >
                  <Trash2 className="h-4 w-4" />
                  清空记录
                </Button>
              </div>
            </div>

            {historyError ? (
              <div className="border-b border-rose-100 bg-rose-50/80 px-5 py-3 text-sm text-rose-600 xl:px-8">
                {historyError}
              </div>
            ) : null}

            <div className="min-h-0 flex-1 overflow-y-auto pb-40 relative">
              {!historyLoaded ? (
                <div className="flex h-full items-center justify-center text-slate-500">
                  <Loader2 className="mr-2 h-5 w-5 animate-spin" />
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
                    <div className="mx-auto inline-flex h-16 w-16 items-center justify-center rounded-[24px] bg-gradient-to-br from-stone-500 via-stone-600 to-stone-800 text-white shadow-md shadow-stone-500/20">
                      <MessageSquareText className="h-8 w-8" />
                    </div>
                    <h3 className="mt-6 text-2xl font-semibold tracking-tight text-slate-900">
                      开始第一轮教学对话
                    </h3>
                    <p className="mt-3 text-sm leading-7 text-slate-500">
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
