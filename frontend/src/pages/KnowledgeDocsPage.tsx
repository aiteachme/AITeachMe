/* ------------------------------------------------------------------ */
/*  KnowledgeDocsPage — Thin orchestrator (refactored)                 */
/*  ~250 lines replacing the original 3,966-line monolith.             */
/*  All logic lives in hooks, all UI in focused components.            */
/* ------------------------------------------------------------------ */

import { Suspense, useState, useRef, useEffect, useMemo, useCallback } from "react";
import { Loader2 } from "lucide-react";
import { cn } from "../lib/utils";
import { useSubjectAiAssistant } from "../components/ai/SubjectAiAssistant";
import { StudyPlanPanel } from "../components/pages/StudyPlanPanel";
import { SubjectVectorNotice } from "../components/pages/SubjectVectorNotice";
import { MarkdownViewer } from "../components/ui/MarkdownViewer";

/* Hooks */
import { useDocMarkdown } from "../components/knowledge-docs/hooks/useDocMarkdown";
import { useDocBuildProgress } from "../components/knowledge-docs/hooks/useDocBuildProgress";
import { useDocToc } from "../components/knowledge-docs/hooks/useDocToc";
import { useDocSelection } from "../components/knowledge-docs/hooks/useDocSelection";
import { useDocComments } from "../components/knowledge-docs/hooks/useDocComments";

/* Components */
import { BuildView } from "../components/knowledge-docs/BuildView";
import { DocHeader } from "../components/knowledge-docs/DocHeader";
import { DocEmptyState } from "../components/knowledge-docs/DocEmptyState";
import { DocErrorState } from "../components/knowledge-docs/DocErrorState";
import { DocUpdatingBanner } from "../components/knowledge-docs/DocUpdatingBanner";
import { DocTocSidebar } from "../components/knowledge-docs/DocTocSidebar";
import { DocFloatingToolbar } from "../components/knowledge-docs/DocFloatingToolbar";
import { DocHighlightOverlay } from "../components/knowledge-docs/DocHighlightOverlay";

import { COMPACT_PANEL_BREAKPOINT } from "../components/knowledge-docs/utils";



/* ------------------------------------------------------------------ */
/*  Component                                                          */
/* ------------------------------------------------------------------ */

export function KnowledgeDocsPage() {
  const { openAssistant } = useSubjectAiAssistant();

  /* ---- Refs ---- */
  const scrollRef = useRef<HTMLDivElement>(null);
  const contentAreaRef = useRef<HTMLDivElement>(null);
  const commentPanelRef = useRef<HTMLDivElement>(null);

  /* ---- Layout state ---- */
  const [isTocCollapsed, setIsTocCollapsed] = useState(false);
  const [isCompactPanels, setIsCompactPanels] = useState(false);

  useEffect(() => {
    const sync = () => setIsCompactPanels(window.innerWidth < COMPACT_PANEL_BREAKPOINT);
    sync();
    window.addEventListener("resize", sync);
    return () => window.removeEventListener("resize", sync);
  }, []);

  /* ---- Core data hooks ---- */
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
  const selection = useDocSelection(scrollRef, contentAreaRef, commentPanelRef);

  const tocOrderMap = useMemo(
    () => new Map(toc.toc.map((item, index) => [item.id, index])),
    [toc.toc],
  );
  const comments = useDocComments(doc.subjectId, tocOrderMap);

  const commentsForAnchor = useCallback(
    (anchorId: string) => comments.threadCountByAnchor.get(anchorId) ?? 0,
    [comments.threadCountByAnchor],
  );

  /* ---- Rebuild selection highlights when comments load ---- */
  useEffect(() => {
    if (!doc.hasRenderedMarkdown || comments.commentThreads.length === 0) return;
    selection.setSelectionHighlights((prev) => {
      const threadIdSet = new Set(comments.commentThreads.map((t) => t.threadId));
      const kept = prev.filter((item) => threadIdSet.has(item.threadId));
      const existing = new Set(kept.map((item) => item.threadId));
      let changed = kept.length !== prev.length;
      const next = [...kept];
      for (const thread of comments.commentThreads) {
        if (existing.has(thread.threadId) || !thread.selectedText) continue;
        const segments = selection.buildSelectionSegmentsFromText(thread.anchorId, thread.selectedText);
        if (segments.length > 0) {
          next.push({
            id: `highlight-${thread.threadId}`,
            threadId: thread.threadId,
            anchorId: thread.anchorId,
            selectedText: thread.selectedText,
            segments,
          });
          changed = true;
        }
      }
      return changed ? next.slice(0, 200) : prev;
    });
  }, [doc.hasRenderedMarkdown, comments.commentThreads, selection]);

  /* ---- "Ask AI" from floating toolbar ---- */
  const handleAskAi = useCallback(() => {
    if (!selection.floatingToolbar) return;
    const { anchorId, selectedText } = selection.floatingToolbar;
    const threadId = comments.createLocalThreadId(anchorId);
    const segments = selection.captureSelectionSegments();
    selection.addSelectionHighlight(threadId, anchorId, selectedText, segments);
    selection.clearSelectionHighlight();
    selection.setFloatingToolbar(null);

    if (isCompactPanels) {
      openAssistant({ draft: selectedText });
    } else {
      selection.setFloatingComment({
        anchorId,
        selectedText,
        selectionViewportTop: selection.floatingToolbar.selectionViewportTop,
        top: selection.computeCommentComposerTop(selection.floatingToolbar.selectionViewportTop),
      });
      selection.setFloatingInput("");
    }
  }, [selection, comments, isCompactPanels, openAssistant]);

  /* ---- Submit floating comment ---- */
  const handleFloatingSubmit = useCallback(() => {
    if (!selection.floatingComment) return;
    const question = selection.floatingInput.trim();
    if (!question) return;
    const { anchorId, selectedText } = selection.floatingComment;
    const threadId = comments.createLocalThreadId(anchorId);
    selection.addSelectionHighlight(threadId, anchorId, selectedText);
    comments.setActiveCommentThreadId(threadId);
    comments.setPinnedThreadId(threadId);
    selection.dismissCommentComposer();
    void comments.streamAssistantReply(threadId, anchorId, selectedText, question);
  }, [selection, comments]);

  /* ---- Locate thread on highlight click ---- */
  const handleLocateThread = useCallback(
    (threadId: string) => {
      comments.setActiveCommentThreadId(threadId);
      comments.setPinnedThreadId(threadId);
    },
    [comments],
  );

  /* ================================================================== */
  /*  Render                                                             */
  /* ================================================================== */

  /* Loading */
  if (doc.docMarkdownQuery.isLoading) {
    return (
      <div className="flex h-full items-center justify-center">
        <Loader2 className="w-6 h-6 animate-spin text-stone-400" />
      </div>
    );
  }

  /* Error */
  if (doc.docMarkdownQuery.isError) {
    return (
      <DocErrorState
        message={doc.docMarkdownQuery.error?.message ?? "未知错误"}
        onRetry={() => void doc.docMarkdownQuery.refetch()}
      />
    );
  }

  /* Build in progress (no document yet) */
  if (doc.showDocGeneratingState) {
    return (
      <div className="h-full overflow-y-auto px-6">
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

  /* Build failed (no document) */
  if (doc.showDocBuildFailureState) {
    return (
      <DocErrorState
        message={doc.buildMeta?.error_message ?? "知识构建失败，请稍后重试"}
        onRetry={() => void doc.docMarkdownQuery.refetch()}
      />
    );
  }

  /* Empty (no build, no document) */
  if (doc.showDocEmptyState) {
    return <DocEmptyState />;
  }

  /* ---- Document reader view ---- */
  return (
    <div className="flex h-full overflow-hidden">
      {/* TOC Sidebar */}
      <DocTocSidebar
        tocTree={toc.tocTree}
        activeHeading={toc.activeHeading}
        collapsedTocIds={toc.collapsedTocIds}
        commentsForAnchor={commentsForAnchor}
        onTocItemClick={toc.scrollToHeading}
        onToggleCollapse={toc.toggleTocCollapse}
        tocNavRef={toc.tocNavRef}
        isCollapsed={isTocCollapsed}
        onCollapsedChange={setIsTocCollapsed}
        activeTocText={toc.activeTocItem?.text}
        className={cn(
          "shrink-0 border-r border-[#DEE0E3] bg-[#FAFAFA] transition-all duration-200",
          isTocCollapsed ? "w-14" : "w-60",
        )}
      />

      {/* Main content area */}
      <div className="flex flex-1 min-w-0 flex-col overflow-hidden">
        {/* Vector notice */}
        {doc.subjectId && (
          <SubjectVectorNotice />
        )}

        {/* Document header */}
        <DocHeader
          title={doc.renderedDocTitle}
          summary={doc.renderedDocSummary}
          digestModeLabel={doc.renderedDigestModeLabel}
          docViewLabel={doc.effectiveDocViewMode === "draft" ? "草稿" : "正式版"}
          updatedLabel={doc.renderedDocUpdatedLabel}
          llmCalls={doc.buildMetrics?.llm_total_calls ?? null}
          chapterHighlights={doc.renderedChapterHighlights}
        />

        {/* Updating banner */}
        {doc.showDocUpdatingBanner && (
          <div className="px-6 pt-4">
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
          </div>
        )}

        {/* Scroll container with markdown */}
        <div
          ref={scrollRef}
          className="doc-scroll-container content-scroll flex-1 overflow-y-auto relative"
          onMouseUp={selection.handleTextSelect}
        >
          <div className="mx-auto max-w-4xl px-6 md:px-10 pb-24">
            <div ref={contentAreaRef} className="feishu-doc-content">
              <MarkdownViewer
                content={doc.renderedMarkdown}
                variant="document"
              />
            </div>
          </div>

          {/* Floating toolbar */}
          {selection.floatingToolbar && (
            <DocFloatingToolbar
              toolbar={selection.floatingToolbar}
              floatingRef={selection.floatingRef}
              onAskAi={handleAskAi}
            />
          )}

          {/* Selection highlights */}
          <DocHighlightOverlay
            highlights={selection.selectionHighlights}
            highlightedThreadId={comments.activeCommentThreadId}
            onLocateThread={handleLocateThread}
          />

          {/* Floating comment input */}
          {selection.floatingComment && !isCompactPanels && (
            <div
              ref={commentPanelRef}
              className="absolute right-6 z-40"
              style={{ top: selection.floatingComment.top }}
            >
              <div className="w-72 rounded-lg border border-[#DEE0E3] bg-white shadow-[0_4px_16px_rgba(0,0,0,0.08)] p-3">
                <p className="text-[11px] text-[#8F959E] mb-2 truncate">
                  &ldquo;{selection.floatingComment.selectedText.slice(0, 80)}&rdquo;
                </p>
                <textarea
                  value={selection.floatingInput}
                  onChange={(e) => selection.setFloatingInput(e.target.value)}
                  onKeyDown={(e) => {
                    if (e.key === "Enter" && !e.shiftKey) {
                      e.preventDefault();
                      handleFloatingSubmit();
                    }
                    if (e.key === "Escape") {
                      selection.dismissCommentComposer();
                    }
                  }}
                  placeholder="向 AI 提问这段内容..."
                  className="w-full resize-none rounded-md border border-[#DEE0E3] bg-[#F5F6F7] px-3 py-2 text-[13px] text-[#1F2329] placeholder:text-[#8F959E] focus:border-[#3370FF] focus:outline-none focus:ring-1 focus:ring-[#3370FF]/30 focus:bg-white"
                  rows={2}
                  autoFocus
                />
                <div className="mt-2 flex justify-end gap-2">
                  <button
                    onClick={selection.dismissCommentComposer}
                    className="rounded-md px-3 py-1.5 text-[12px] text-[#646A73] hover:bg-[#F5F6F7]"
                  >
                    取消
                  </button>
                  <button
                    onClick={handleFloatingSubmit}
                    disabled={!selection.floatingInput.trim()}
                    className="rounded-md bg-[#3370FF] px-3 py-1.5 text-[12px] font-medium text-white shadow-sm hover:bg-[#245BDB] disabled:opacity-40"
                  >
                    发送
                  </button>
                </div>
              </div>
            </div>
          )}
        </div>
      </div>

      {/* Study plan side panel */}
      {doc.subjectId && (
        <Suspense fallback={null}>
          <StudyPlanPanel subject={doc.subjectId} />
        </Suspense>
      )}
    </div>
  );
}
