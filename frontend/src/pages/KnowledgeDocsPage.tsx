/* ------------------------------------------------------------------ */
/*  KnowledgeDocsPage — Restored workspace-style document view         */
/* ------------------------------------------------------------------ */

import { Suspense, useMemo, useRef, useState } from "react";
import {
  ChevronLeft,
  ChevronRight,
  Loader2,
  MessageSquare,
  PanelLeftClose,
  PanelLeftOpen,
  Sparkles,
} from "lucide-react";

import { useDocMarkdown } from "../components/knowledge-docs/hooks/useDocMarkdown";
import { useDocBuildProgress } from "../components/knowledge-docs/hooks/useDocBuildProgress";
import { useDocToc } from "../components/knowledge-docs/hooks/useDocToc";
import { useSettings } from "../hooks/useSettings";
import { BuildView } from "../components/knowledge-docs/BuildView";
import { DocEmptyState } from "../components/knowledge-docs/DocEmptyState";
import { DocErrorState } from "../components/knowledge-docs/DocErrorState";
import { DocUpdatingBanner } from "../components/knowledge-docs/DocUpdatingBanner";
import { DocTocSidebar } from "../components/knowledge-docs/DocTocSidebar";
import { DocHeader } from "../components/knowledge-docs/DocHeader";
import { KnowledgeGraphSidePanel } from "../components/pages/KnowledgeGraphSidePanel";
import { formatTime } from "../components/knowledge-docs/utils";
import { GeminiDocumentViewer } from "../components/knowledge-docs/ui/GeminiDocumentViewer";

type CommentSidebarItem = {
  id: string;
  title: string;
  anchorId: string;
  excerpt: string;
  role: "assistant" | "user";
  content: string;
  createdAt: number;
};

function CommentSidebar({
  items,
  onJumpToAnchor,
  compact = false,
}: {
  items: CommentSidebarItem[];
  onJumpToAnchor: (anchorId: string) => void;
  compact?: boolean;
}) {
  return (
    <div className="flex h-full min-h-0 flex-col rounded-[24px] border border-slate-200 bg-white shadow-[0_18px_48px_-28px_rgba(15,23,42,0.22)]">
      <div className="flex items-center justify-between border-b border-slate-200 px-4 py-4">
        <div>
          <p className="text-[11px] font-semibold uppercase tracking-[0.16em] text-slate-400">Discuss</p>
          <h3 className="mt-1 flex items-center gap-2 text-sm font-semibold text-slate-900">
            <MessageSquare className="h-4 w-4 text-slate-500" />
            评论与批注
          </h3>
        </div>
        <div className="rounded-full border border-slate-200 bg-slate-50 px-2.5 py-1 text-[11px] font-medium text-slate-500">
          {items.length} 条
        </div>
      </div>

      <div className="border-b border-slate-100 bg-slate-50/70 px-4 py-3">
        <div className="flex items-start gap-2 rounded-2xl border border-slate-200 bg-white px-3 py-2.5 text-xs leading-5 text-slate-500">
          <Sparkles className="mt-0.5 h-3.5 w-3.5 shrink-0 text-blue-500" />
          <p>先恢复旧版右侧评论区的位置和节奏，下一步再继续接回真实划词线程。</p>
        </div>
      </div>

      <div className="min-h-0 flex-1 space-y-3 overflow-y-auto p-3">
        {items.map((item) => (
          <section
            key={item.id}
            className="rounded-2xl border border-slate-200 bg-white p-3 shadow-sm transition hover:border-slate-300"
          >
            <button
              type="button"
              onClick={() => onJumpToAnchor(item.anchorId)}
              className="mb-3 block text-left"
            >
              <p className="text-[11px] font-semibold uppercase tracking-[0.14em] text-slate-400">Anchor</p>
              <h4 className="mt-1 text-sm font-semibold text-slate-900">{item.title}</h4>
              <p className="mt-1 line-clamp-2 text-xs leading-5 text-slate-500">“{item.excerpt}”</p>
            </button>

            <div
              className={
                item.role === "assistant"
                  ? "rounded-2xl bg-slate-900 px-3 py-2.5 text-white"
                  : "rounded-2xl bg-slate-100 px-3 py-2.5 text-slate-700"
              }
            >
              <div className="mb-1 flex items-center justify-between gap-3">
                <span className="text-[11px] font-medium opacity-80">
                  {item.role === "assistant" ? "AI 助教" : "评论"}
                </span>
                <span className="text-[10px] opacity-70">{formatTime(item.createdAt)}</span>
              </div>
              <p className={`text-xs leading-5 ${compact ? "line-clamp-4" : ""}`}>{item.content}</p>
            </div>
          </section>
        ))}
      </div>
    </div>
  );
}

export function KnowledgeDocsPage() {
  const scrollRef = useRef<HTMLDivElement>(null);

  const [isTocVisible, setIsTocVisible] = useState(true);
  const [isCommentVisible, setIsCommentVisible] = useState(true);
  const [isGraphPanelVisible, setIsGraphPanelVisible] = useState(false);

  const { settings } = useSettings();
  const doc = useDocMarkdown();
  const progress = useDocBuildProgress({
    buildMeta: doc.buildMeta,
    buildStatus: doc.buildStatus,
    hasLiveDocMarkdown: doc.hasLiveDocMarkdown,
    hasDraftDocMarkdown: doc.hasDraftDocMarkdown,
    isBuildActive: doc.isBuildActive,
    isBuildFailure: doc.isBuildFailure,
    isRequestedBuildReady: doc.isRequestedBuildReady,
    isWaitingForRequestedBuild: doc.isWaitingForRequestedBuild,
  });

  const toc = useDocToc(doc.renderedMarkdown, scrollRef);
  const subjectId = doc.subjectId ?? "";

  const commentItems = useMemo<CommentSidebarItem[]>(() => {
    const headings = toc.toc.slice(0, 3);
    const now = Date.now();
    if (headings.length === 0) {
      return [
        {
          id: "comment-1",
          title: "文档总览",
          anchorId: "mock-overview",
          excerpt: doc.renderedDocSummary,
          role: "assistant",
          content: "这一版先恢复评论区样式和工作区位置，方便继续往旧版飞书文档效果靠拢。",
          createdAt: now - 1000 * 60 * 18,
        },
      ];
    }

    return headings.map((item, index) => ({
      id: `comment-${index + 1}`,
      title: item.text,
      anchorId: item.id,
      excerpt: item.text,
      role: index % 2 === 0 ? "assistant" : "user",
      content:
        index % 2 === 0
          ? "这里可以放老师式批注、概念提醒或 AI 补充说明，后续再接回真实线程。"
          : "这一段建议继续做成可评论、可追问、可定位回正文的交互。",
      createdAt: now - (index + 1) * 1000 * 60 * 12,
    }));
  }, [doc.renderedDocSummary, toc.toc]);

  if (doc.docMarkdownQuery.isLoading) {
    return (
      <div className="flex h-full items-center justify-center bg-white">
        <Loader2 className="h-8 w-8 animate-spin text-slate-300" />
      </div>
    );
  }

  if (doc.docMarkdownQuery.isError) {
    return (
      <DocErrorState
        message={doc.docMarkdownQuery.error?.message ?? "未知错误"}
        onRetry={() => void doc.docMarkdownQuery.refetch()}
      />
    );
  }

  if (doc.showDocGeneratingState) {
    return (
      <div className="h-full overflow-y-auto bg-white px-6">
        <BuildView
          isFetching={doc.docMarkdownQuery.isFetching}
          progress={progress.buildProgress}
          statusText={progress.buildStatusText}
          buildPreview={doc.buildPreview}
          buildMetrics={doc.buildMetrics}
          sourceFiles={doc.sourceFiles}
          sourceFilesFetching={doc.sourceFilesFetching}
          buildStage={doc.buildMeta?.stage}
        />
      </div>
    );
  }

  if (doc.showDocBuildFailureState) {
    return (
      <DocErrorState
        message={doc.buildMeta?.error_message ?? "知识构建失败，请稍后重试"}
        onRetry={() => void doc.docMarkdownQuery.refetch()}
      />
    );
  }

  if (doc.showDocEmptyState) {
    return <DocEmptyState />;
  }

  return (
    <div className="relative flex h-full w-full overflow-hidden bg-[#F5F6F7] text-slate-900 selection:bg-blue-100 selection:text-blue-900">
      {(isCommentVisible || isGraphPanelVisible) ? (
        <button
          type="button"
          aria-label="关闭侧边面板"
          onClick={() => {
            setIsCommentVisible(false);
            setIsGraphPanelVisible(false);
          }}
          className="fixed inset-0 z-10 bg-slate-900/10 backdrop-blur-[1px] xl:hidden"
        />
      ) : null}

      {isTocVisible ? (
        <aside className="hidden h-full w-[288px] shrink-0 border-r border-slate-200 bg-[#FBFBFC] md:flex md:flex-col">
          <div className="border-b border-slate-200 px-5 py-5">
            <div className="flex items-center justify-between gap-3">
              <div>
                <p className="text-[11px] font-semibold uppercase tracking-[0.16em] text-slate-400">Knowledge</p>
                <h2 className="mt-1 text-sm font-semibold text-slate-900">章节目录</h2>
              </div>
              <button
                type="button"
                onClick={() => setIsTocVisible(false)}
                className="rounded-lg p-2 text-slate-400 transition hover:bg-slate-100 hover:text-slate-700"
                title="收起目录"
              >
                <PanelLeftClose className="h-4 w-4" />
              </button>
            </div>
          </div>
          <div className="flex-1 overflow-y-auto">
            <DocTocSidebar
              tocTree={toc.tocTree}
              activeHeading={toc.activeHeading}
              onTocItemClick={toc.scrollToHeading}
              className="h-full"
            />
          </div>
        </aside>
      ) : null}

      {!isTocVisible ? (
        <div className="absolute left-4 top-24 z-20 hidden md:block">
          <button
            type="button"
            onClick={() => setIsTocVisible(true)}
            className="inline-flex h-11 items-center gap-2 rounded-xl border border-slate-200 bg-white/95 px-3 text-sm font-medium text-slate-600 shadow-sm backdrop-blur transition hover:border-slate-300 hover:text-slate-900"
          >
            <PanelLeftOpen className="h-4 w-4" />
            目录
          </button>
        </div>
      ) : null}

      <div className={`relative flex min-w-0 flex-1 overflow-hidden ${isGraphPanelVisible ? "2xl:pr-[520px]" : ""}`}>
        <div className="relative flex min-w-0 flex-1 flex-col overflow-hidden bg-[#F5F6F7]">
          <div className="border-b border-slate-200 bg-white/92 px-4 py-3 backdrop-blur md:px-6">
            <div className="mx-auto flex w-full max-w-[1180px] items-center justify-between gap-3">
              <div className="flex items-center gap-2">
                {!isTocVisible ? (
                  <button
                    type="button"
                    onClick={() => setIsTocVisible(true)}
                    className="inline-flex h-10 items-center gap-2 rounded-xl border border-slate-200 bg-white px-3 text-sm font-medium text-slate-600 shadow-sm transition hover:border-slate-300 hover:text-slate-900"
                  >
                    <PanelLeftOpen className="h-4 w-4" />
                    目录
                  </button>
                ) : null}
                <div className="hidden rounded-full border border-slate-200 bg-slate-50 px-3 py-1.5 text-xs font-medium text-slate-500 md:inline-flex">
                  工作区视图
                </div>
                {settings.debugMode ? (
                  <div className="inline-flex rounded-full border border-amber-200 bg-amber-50 px-3 py-1.5 text-xs font-medium text-amber-700">
                    Debug Mock 已启用
                  </div>
                ) : null}
              </div>

              <button
                type="button"
                onClick={() => setIsCommentVisible((value) => !value)}
                className="inline-flex h-10 items-center gap-2 rounded-xl border border-slate-200 bg-white px-3 text-sm font-medium text-slate-600 shadow-sm transition hover:border-slate-300 hover:text-slate-900"
              >
                <MessageSquare className="h-4 w-4" />
                {isCommentVisible ? "收起评论" : "打开评论"}
              </button>
            </div>
          </div>

          {doc.showDocUpdatingBanner ? (
            <DocUpdatingBanner
              progress={progress.buildProgress}
              statusText={progress.buildStatusText}
              isFetching={doc.docMarkdownQuery.isFetching}
              viewMode={doc.effectiveDocViewMode}
              hasLiveVersion={doc.hasLiveDocMarkdown}
              hasDraftVersion={doc.hasDraftDocMarkdown}
              liveUpdatedAt={doc.liveUpdatedAt}
              draftUpdatedAt={doc.draftUpdatedAt}
              buildPreview={doc.buildPreview}
              onViewModeChange={doc.setDocViewMode}
            />
          ) : null}

          <div className="doc-scroll-container content-scroll relative flex-1 overflow-y-auto scroll-smooth" ref={scrollRef}>
            <div className="mx-auto w-full max-w-[1360px] px-4 pb-24 pt-8 md:px-8">
              <div className="flex items-start gap-6">
                <div className="min-w-0 flex-1 overflow-hidden rounded-[28px] border border-slate-200 bg-white shadow-[0_24px_80px_-32px_rgba(15,23,42,0.18)]">
                  <DocHeader
                    title={doc.renderedDocTitle}
                    summary={doc.renderedDocSummary}
                    digestModeLabel={doc.renderedDigestModeLabel}
                    docViewLabel={doc.renderedSubjectLabel}
                    updatedLabel={doc.renderedDocUpdatedLabel}
                    llmCalls={doc.buildMetrics?.llm_total_calls ?? null}
                    chapterHighlights={doc.renderedChapterHighlights}
                    className="border-none bg-transparent px-6 pb-0 pt-6 md:px-10 md:pb-0 md:pt-8"
                  />
                  <GeminiDocumentViewer content={doc.renderedMarkdown} />
                </div>

                {isCommentVisible ? (
                  <aside className="sticky top-6 hidden h-[calc(100vh-9rem)] w-[320px] shrink-0 xl:block">
                    <CommentSidebar items={commentItems} onJumpToAnchor={toc.scrollToHeading} />
                  </aside>
                ) : null}
              </div>
            </div>
          </div>
        </div>
      </div>

      {isCommentVisible ? (
        <div className="fixed inset-y-24 right-4 z-30 w-[min(24rem,calc(100vw-2rem))] xl:hidden">
          <CommentSidebar items={commentItems} onJumpToAnchor={toc.scrollToHeading} compact />
        </div>
      ) : null}

      <div className="absolute right-0 top-1/2 z-30 flex -translate-y-1/2 items-center">
        {!isGraphPanelVisible ? (
          <button
            type="button"
            onClick={() => setIsGraphPanelVisible(true)}
            className="flex h-[88px] w-8 items-center justify-center rounded-l-full border border-r-0 border-slate-200 bg-white/95 text-slate-500 shadow-[0_12px_32px_-20px_rgba(15,23,42,0.35)] backdrop-blur transition hover:w-10 hover:text-blue-600"
            title="拉开知识图谱"
          >
            <ChevronLeft className="h-5 w-5" />
          </button>
        ) : (
          <button
            type="button"
            onClick={() => setIsGraphPanelVisible(false)}
            className="mr-[min(34vw,520px)] flex h-[88px] w-8 items-center justify-center rounded-l-full border border-r-0 border-slate-200 bg-white/95 text-slate-500 shadow-[0_12px_32px_-20px_rgba(15,23,42,0.35)] backdrop-blur transition hover:w-10 hover:text-blue-600"
            title="收起知识图谱"
          >
            <ChevronRight className="h-5 w-5" />
          </button>
        )}
      </div>

      {isGraphPanelVisible ? (
        <div className="absolute inset-y-0 right-0 z-20 hidden w-[min(34vw,520px)] min-w-[360px] border-l border-slate-200 bg-white shadow-[-18px_0_40px_-28px_rgba(15,23,42,0.22)] 2xl:block">
          <KnowledgeGraphSidePanel subjectId={subjectId} />
        </div>
      ) : null}

      {isGraphPanelVisible ? (
        <div className="fixed inset-x-0 bottom-0 top-24 z-20 border-t border-slate-200 bg-white shadow-2xl 2xl:hidden">
          <KnowledgeGraphSidePanel subjectId={subjectId} />
        </div>
      ) : null}
    </div>
  );
}

export default function KnowledgeDocsPageWithSuspense() {
  return (
    <Suspense
      fallback={
        <div className="flex h-full items-center justify-center bg-white">
          <Loader2 className="h-8 w-8 animate-spin text-slate-300" />
        </div>
      }
    >
      <KnowledgeDocsPage />
    </Suspense>
  );
}
