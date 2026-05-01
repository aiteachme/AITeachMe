import { useQuery } from "@tanstack/react-query";
import { BookOpen, FileText, Loader2 } from "lucide-react";

import {
  chunkContextApiV1CoursesCourseIdKnowledgeChunksContextPost,
  graphKnowledgeUnitDetailApiV1CoursesCourseIdKnowledgeGraphKnowledgeUnitsDetailPost,
} from "../../api/generated/knowledge";
import type { ChatContextItem } from "../../api/generated/model";
import { unwrapOrvalResponse } from "../../lib/unwrapOrvalResponse";
import { Modal } from "../ui/Modal";
import { MarkdownViewer } from "../ui/MarkdownViewer";

interface ChatCitationModalProps {
  open: boolean;
  onClose: () => void;
  course: string;
  context: ChatContextItem | null;
}

export function ChatCitationModal({
  open,
  onClose,
  course,
  context,
}: ChatCitationModalProps) {
  const chunkId = context?.chunk_id ?? null;
  const knowledgeUnitId = Number(context?.knowledge_unit_id ?? 0);
  const hasValidChunkId = typeof chunkId === "number" && chunkId > 0;
  const canLoadKnowledgeUnit = !hasValidChunkId && knowledgeUnitId > 0;

  const { data: chunkData, isLoading: isChunkLoading, isError: isChunkError } = useQuery({
    queryKey: ["chat-chunk-context", course, chunkId],
    queryFn: async () =>
      unwrapOrvalResponse(
        await chunkContextApiV1CoursesCourseIdKnowledgeChunksContextPost(course, {
          chunk_id: chunkId as number,
        }),
      ),
    enabled: open && !!course && hasValidChunkId,
  });

  const { data: unitData, isLoading: isUnitLoading, isError: isUnitError } = useQuery({
    queryKey: ["chat-knowledge-unit-context", course, knowledgeUnitId],
    queryFn: async () =>
      unwrapOrvalResponse(
        await graphKnowledgeUnitDetailApiV1CoursesCourseIdKnowledgeGraphKnowledgeUnitsDetailPost(course, {
          knowledge_unit_id: knowledgeUnitId,
        }),
      ),
    enabled: open && !!course && canLoadKnowledgeUnit,
  });

  const unitContent =
    unitData?.current_revision?.body?.trim() ||
    unitData?.current_revision?.summary?.trim() ||
    context?.evidence_quote?.trim() ||
    context?.title ||
    "";

  const title = chunkData
    ? `${chunkData.document_title} - ${chunkData.chunk_header_path || chunkData.chunk_title}`
    : unitData
      ? unitData.canonical_name
      : context?.title || "查看引用来源";
  const isLoading = isChunkLoading || isUnitLoading;
  const isError = (hasValidChunkId && isChunkError) || (canLoadKnowledgeUnit && isUnitError);
  const hasOpenableTarget = hasValidChunkId || canLoadKnowledgeUnit;

  return (
    <Modal open={open} onClose={onClose} title={title} className="max-w-4xl">
      <div className="space-y-4">
        {open && !hasOpenableTarget ? (
          <div className="rounded-2xl border border-amber-200 bg-amber-50 px-4 py-3 text-sm text-amber-700 dark:border-amber-500/30 dark:bg-amber-500/10 dark:text-amber-200">
            该引用没有可打开的来源详情。
          </div>
        ) : null}

        {isLoading ? (
          <div className="flex items-center justify-center py-10 text-sm text-slate-500 dark:text-slate-400">
            <Loader2 className="mr-2 h-5 w-5 animate-spin" />
            正在加载引用来源...
          </div>
        ) : null}

        {isError ? (
          <div className="rounded-2xl border border-rose-200 bg-rose-50 px-4 py-3 text-sm text-rose-600 dark:border-rose-500/30 dark:bg-rose-500/10 dark:text-rose-300">
            引用来源加载失败，该引用对应的内容可能已经不存在。
          </div>
        ) : null}

        {chunkData ? (
          <>
            <div className="rounded-2xl border border-slate-200 bg-slate-50 px-4 py-3 dark:border-slate-800 dark:bg-slate-900/80">
              <div className="flex items-center gap-2 text-xs uppercase tracking-[0.18em] text-slate-400 dark:text-slate-500">
                <FileText className="h-3.5 w-3.5" />
                文档信息
              </div>
              <div className="mt-3 space-y-2 text-sm text-slate-600 dark:text-slate-300">
                <div className="flex items-start gap-2">
                  <BookOpen className="mt-0.5 h-4 w-4 text-indigo-600" />
                  <span>{chunkData.document_title}</span>
                </div>
                <div className="pl-6 text-slate-500 dark:text-slate-400">
                  {chunkData.chunk_header_path || chunkData.chunk_title}
                </div>
              </div>
            </div>

            <div className="max-h-[60vh] overflow-y-auto rounded-3xl border border-slate-200 bg-white px-5 py-4 shadow-inner dark:border-slate-800 dark:bg-slate-950/70 dark:shadow-[inset_0_1px_0_rgba(255,255,255,0.04)]">
              <MarkdownViewer content={chunkData.chunk_content} />
            </div>
          </>
        ) : null}

        {!chunkData && unitData ? (
          <>
            <div className="rounded-2xl border border-slate-200 bg-slate-50 px-4 py-3 dark:border-slate-800 dark:bg-slate-900/80">
              <div className="flex items-center gap-2 text-xs uppercase tracking-[0.18em] text-slate-400 dark:text-slate-500">
                <BookOpen className="h-3.5 w-3.5" />
                知识点信息
              </div>
              <div className="mt-3 space-y-2 text-sm text-slate-600 dark:text-slate-300">
                <div className="flex items-start gap-2">
                  <FileText className="mt-0.5 h-4 w-4 text-indigo-600" />
                  <span>{unitData.canonical_name}</span>
                </div>
                <div className="pl-6 text-slate-500 dark:text-slate-400">
                  {unitData.knowledge_unit_type}
                  {context?.relation_path ? ` · ${context.relation_path}` : ""}
                </div>
              </div>
            </div>

            <div className="max-h-[60vh] overflow-y-auto rounded-3xl border border-slate-200 bg-white px-5 py-4 shadow-inner dark:border-slate-800 dark:bg-slate-950/70 dark:shadow-[inset_0_1px_0_rgba(255,255,255,0.04)]">
              <MarkdownViewer content={unitContent || "暂无可展示的知识点内容。"} />
            </div>
          </>
        ) : null}
      </div>
    </Modal>
  );
}
