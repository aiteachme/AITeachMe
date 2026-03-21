import { useQuery } from "@tanstack/react-query";
import { BookOpen, FileText, Loader2 } from "lucide-react";
import { fetchChatChunkContext } from "../../api/chatApi";
import { Modal } from "../ui/Modal";
import { MarkdownViewer } from "../ui/MarkdownViewer";

interface ChatCitationModalProps {
  open: boolean;
  onClose: () => void;
  subject: string;
  chunkId: number | null;
}

export function ChatCitationModal({
  open,
  onClose,
  subject,
  chunkId,
}: ChatCitationModalProps) {
  const { data, isLoading, isError } = useQuery({
    queryKey: ["chat-chunk-context", subject, chunkId],
    queryFn: () => fetchChatChunkContext(subject, chunkId!),
    enabled: open && !!subject && chunkId !== null,
  });

  const title = data
    ? `${data.documentTitle} › ${data.chunkHeaderPath || data.chunkTitle}`
    : "查看原文";

  return (
    <Modal open={open} onClose={onClose} title={title} className="max-w-4xl">
      <div className="space-y-4">
        {isLoading ? (
          <div className="flex items-center justify-center py-10 text-sm text-slate-500">
            <Loader2 className="mr-2 h-5 w-5 animate-spin" />
            正在加载引用原文...
          </div>
        ) : null}

        {isError ? (
          <div className="rounded-2xl border border-rose-200 bg-rose-50 px-4 py-3 text-sm text-rose-600">
            原文加载失败，该引用对应的切块可能已经不存在。
          </div>
        ) : null}

        {data ? (
          <>
            <div className="rounded-2xl border border-slate-200 bg-slate-50 px-4 py-3">
              <div className="flex items-center gap-2 text-xs uppercase tracking-[0.18em] text-slate-400">
                <FileText className="h-3.5 w-3.5" />
                文档信息
              </div>
              <div className="mt-3 space-y-2 text-sm text-slate-600">
                <div className="flex items-start gap-2">
                  <BookOpen className="mt-0.5 h-4 w-4 text-sky-600" />
                  <span>{data.documentTitle}</span>
                </div>
                <div className="pl-6 text-slate-500">
                  {data.chunkHeaderPath || data.chunkTitle}
                </div>
              </div>
            </div>

            <div className="max-h-[60vh] overflow-y-auto rounded-3xl border border-slate-200 bg-white px-5 py-4 shadow-inner">
              <MarkdownViewer content={data.chunkContent} />
            </div>
          </>
        ) : null}
      </div>
    </Modal>
  );
}
