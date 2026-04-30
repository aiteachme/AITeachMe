import type { MutableRefObject } from "react";
import { Loader2 } from "lucide-react";

import type { ChatSessionMessage } from "../../hooks/useChatSession";
import { ChatTranscript } from "../chat/ChatTranscript";
import { AiConversationDraftHome } from "./AiConversationDraftHome";

interface AiConversationMessageViewProps {
  scrollRef: MutableRefObject<HTMLDivElement | null>;
  onScroll: () => void;
  messages: ChatSessionMessage[];
  selectedSessionId: string | null;
  historyLoaded: boolean;
  isStreaming: boolean;
  emptyAnimationKey: number;
  onOpenCitation: (chunkId: number) => void;
}

export function AiConversationMessageView({
  scrollRef,
  onScroll,
  messages,
  selectedSessionId,
  historyLoaded,
  isStreaming,
  emptyAnimationKey,
  onOpenCitation,
}: AiConversationMessageViewProps) {
  return (
    <div
      ref={scrollRef}
      onScroll={onScroll}
      className="min-h-0 flex-1 overflow-y-auto pt-2"
    >
      {messages.length > 0 && (!selectedSessionId || historyLoaded || isStreaming) ? (
        <ChatTranscript
          messages={messages}
          onOpenCitation={onOpenCitation}
        />
      ) : !selectedSessionId ? (
        <AiConversationDraftHome
          animationKey={emptyAnimationKey}
          title="开始对话"
          description="直接从下方输入问题发送即可开始。系统会自动创建全新会话。"
        />
      ) : !historyLoaded ? (
        <div className="flex h-full items-center justify-center text-[13px] text-zinc-500 dark:text-slate-400">
          <Loader2 className="mr-2 h-4 w-4 animate-spin" />
          加载会话中...
        </div>
      ) : (
        <AiConversationDraftHome
          animationKey={emptyAnimationKey}
          title="这个会话还没有消息"
          description="开始提问后，这里会展示你和 AITeachMe 的对话记录。"
        />
      )}
    </div>
  );
}
