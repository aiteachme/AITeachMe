import { useQuery } from "@tanstack/react-query";
import { BookOpen, FileText, Loader2 } from "lucide-react";

import { chunkContextApiV1CoursesCourseIdKnowledgeChunksContextPost } from "../../api/generated/knowledge";
import { unwrapOrvalResponse } from "../../lib/unwrapOrvalResponse";
import { Modal } from "../ui/Modal";
import { MarkdownViewer } from "../ui/MarkdownViewer";

interface ChatCitationModalProps {
  open: boolean;
  onClose: () => void;
  course: string;
  chunkId: number | null;
}

export function ChatCitationModal({
  open,
  onClose,
  course,
  chunkId,
}: ChatCitationModalProps) {
  const { data, isLoading, isError } = useQuery({
    queryKey: ["chat-chunk-context", course, chunkId],
    queryFn: async () =>
      unwrapOrvalResponse(
        await chunkContextApiV1CoursesCourseIdKnowledgeChunksContextPost(course, {
          chunk_id: chunkId!,
        }),
      ),
    enabled: open && !!course && chunkId !== null,
  });

  const title = data
    ? `${data.document_title} - ${data.chunk_header_path || data.chunk_title}`
    : "查看原文";

  return (
    <Modal open={open} onClose={onClose} title={title} className="max-w-4xl">
      <div className="space-y-4">
        {isLoading ? (
          <div className="flex items-center justify-center py-10 text-sm text-slate-500 dark:text-slate-400">
            <Loader2 className="mr-2 h-5 w-5 animate-spin" />
            正在加载引用原文...
          </div>
        ) : null}

        {isError ? (
          <div className="rounded-2xl border border-rose-200 bg-rose-50 px-4 py-3 text-sm text-rose-600 dark:border-rose-500/30 dark:bg-rose-500/10 dark:text-rose-300">
            原文加载失败，该引用对应的片段可能已经不存在。
          </div>
        ) : null}

        {data ? (
          <>
            <div className="rounded-2xl border border-slate-200 bg-slate-50 px-4 py-3 dark:border-slate-800 dark:bg-slate-900/80">
              <div className="flex items-center gap-2 text-xs uppercase tracking-[0.18em] text-slate-400 dark:text-slate-500">
                <FileText className="h-3.5 w-3.5" />
                文档信息
              </div>
              <div className="mt-3 space-y-2 text-sm text-slate-600 dark:text-slate-300">
                <div className="flex items-start gap-2">
                  <BookOpen className="mt-0.5 h-4 w-4 text-indigo-600" />
                  <span>{data.document_title}</span>
                </div>
                <div className="pl-6 text-slate-500 dark:text-slate-400">
                  {data.chunk_header_path || data.chunk_title}
                </div>
              </div>
            </div>

            <div className="max-h-[60vh] overflow-y-auto rounded-3xl border border-slate-200 bg-white px-5 py-4 shadow-inner dark:border-slate-800 dark:bg-slate-950/70 dark:shadow-[inset_0_1px_0_rgba(255,255,255,0.04)]">
              <MarkdownViewer content={data.chunk_content} />
            </div>
          </>
        ) : null}
      </div>
    </Modal>
  );
}
