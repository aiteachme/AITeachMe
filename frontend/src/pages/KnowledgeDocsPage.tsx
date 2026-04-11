/* ------------------------------------------------------------------ */
/*  KnowledgeDocsPage — Restored workspace-style document view         */
/* ------------------------------------------------------------------ */

import { Suspense, useEffect, useMemo, useRef, useState } from "react";
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
import { useTextSelection } from "../components/knowledge-docs/hooks/useTextSelection";

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
  onClose,
}: {
  items: CommentSidebarItem[];
  onJumpToAnchor: (anchorId: string) => void;
  onClose: () => void;
}) {
  return (
    <div className="flex h-full min-h-0 flex-col bg-white">
      <div className="flex items-center justify-between border-b border-[#DEE0E3] px-4 py-3 shrink-0">
        <h3 className="text-[14px] text-[#1F2329]">
          评论 ({items.length})
        </h3>
        <button
          type="button"
          onClick={onClose}
          className="rounded text-[#8F959E] hover:bg-[#F0F2F5] p-0.5 transition"
        >
          <ChevronRight className="h-4 w-4" />
        </button>
      </div>

      <div className="min-h-0 flex-1 overflow-y-auto">
        {items.map((item) => (
          <section
            key={item.id}
            className="group border-b border-[#F0F2F5] bg-white px-5 py-4 transition-colors hover:bg-[#F8F9FA]"
          >
            <button
              type="button"
              onClick={() => onJumpToAnchor(item.anchorId)}
              className="mb-4 flex w-full items-center justify-between rounded border border-[#DEE0E3] bg-[#F8F9FA] px-2 py-1.5 transition hover:border-[#C2C7CC]"
            >
              <div className="flex items-center gap-1.5 overflow-hidden text-[#8F959E]">
                <span className="shrink-0 text-[12px] font-medium">[引用]</span>
                <span className="truncate text-[12px]">
                  {item.excerpt}
                </span>
              </div>
              <Sparkles className="h-3 w-3 shrink-0 text-[#8F959E]" />
            </button>

            <div className="flex items-start gap-2.5">
              <div className="flex h-[26px] w-[26px] shrink-0 items-center justify-center rounded-full bg-[#F54A45] text-[11px] text-white">
                {item.role === "assistant" ? "AI" : "用户"}
              </div>
              <div className="min-w-0 flex-1">
                <div className="flex items-center gap-2">
                  <span className="text-[13px] text-[#1F2329]">
                    {item.role === "assistant" ? "AI助教" : "测试用户"}
                  </span>
                  <span className="text-[11px] text-[#8F959E]">
                    {formatTime(item.createdAt)}
                  </span>
                </div>
                <p className="mt-[2px] text-[14px] leading-relaxed text-[#1F2329]">
                  {item.content}
                </p>
                
                <div className="mt-3 flex items-center rounded border border-[#DEE0E3] bg-white px-2.5 py-1.5 transition-colors focus-within:border-[#3370FF]">
                  <input 
                    type="text" 
                    placeholder="回复" 
                    className="flex-1 bg-transparent text-[13px] text-[#1F2329] outline-none placeholder:text-[#8F959E]" 
                  />
                  <MessageSquare className="h-4 w-4 shrink-0 text-[#8F959E]" />
                </div>
              </div>
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
  const [graphViewMode, setGraphViewMode] = useState<"hidden" | "split" | "full">("hidden");

  const openGraphPanel = () => setGraphViewMode(prev => prev === "hidden" ? "split" : "full");
  const closeGraphPanel = () => setGraphViewMode(prev => prev === "full" ? "split" : "hidden");

  const { settings, updateSettings } = useSettings();
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

  const initialCommentItems = useMemo<CommentSidebarItem[]>(() => {
    const headings = toc.toc.slice(0, 3);
    const now = Date.now();
    if (headings.length === 0) {
      return [
        {
          id: "comment-1",
          title: "文档总览",
          anchorId: "mock-overview",
          excerpt: doc.renderedDocSummary,
          role: "user",
          content: "这篇文章的整体结构看起来很不错，但部分细节可以再补充下。",
          createdAt: now - 1000 * 60 * 18,
        },
      ];
    }

    return headings.map((item, index) => ({
      id: `comment-${index + 1}`,
      title: item.text,
      anchorId: item.id,
      excerpt: item.text,
      role: index % 2 === 0 ? "user" : "user",
      content:
        index % 2 === 0
          ? "这里提到这部分概念，但是案例不够清晰，能详细举个例子吗？"
          : "我认为这一段说的很有道理，我完全同意这里的总结。",
      createdAt: now - (index + 1) * 1000 * 60 * 12,
    }));
  }, [doc.renderedDocSummary, toc.toc]);

  const [commentItems, setCommentItems] = useState<CommentSidebarItem[]>([]);
  
  // Initialize mock items once
  useEffect(() => {
    if (commentItems.length === 0 && initialCommentItems.length > 0) {
      setCommentItems(initialCommentItems);
    }
  }, [initialCommentItems, commentItems.length]);

  const { selection, setSelection } = useTextSelection(scrollRef);

  const handleCreateComment = () => {
    if (!selection) return;
    const newComment: CommentSidebarItem = {
      id: `comment-${Date.now()}`,
      title: selection.text.slice(0, 20) + "...",
      anchorId: selection.anchorId,
      excerpt: selection.text.slice(0, 60) + (selection.text.length > 60 ? "..." : ""),
      role: "user",
      content: "请帮我解释一下这段话的意思：\n" + (selection.text.length > 30 ? "..." : ""),
      createdAt: Date.now(),
    };
    setCommentItems(prev => [newComment, ...prev]);
    setIsCommentVisible(true);
    setSelection(null);
  };

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
    <div className="relative flex h-full w-full overflow-hidden bg-white text-[#1F2329] selection:bg-blue-100 selection:text-blue-900">
      {/* Mobile overlay */}
      {(isCommentVisible || graphViewMode !== "hidden") ? (
        <button
          type="button"
          aria-label="关闭侧边面板"
          onClick={() => {
            setIsCommentVisible(false);
            setGraphViewMode("hidden");
          }}
          className="fixed inset-0 z-10 bg-slate-900/10 backdrop-blur-[1px] xl:hidden"
        />
      ) : null}

      {/* 1. Left Sidebar: TOC */}
      {isTocVisible ? (
        <aside className="hidden h-full w-[280px] shrink-0 border-r border-[#DEE0E3] bg-[#F8F9FA] md:flex md:flex-col z-10 transition-all">
          <div className="px-5 py-4 flex items-center justify-between">
            <div className="flex items-center gap-2">
              <span className="w-1.5 h-4 rounded-[1px] bg-[#3370FF]"></span>
              <h2 className="text-[15px] font-semibold text-[#1F2329]">大纲</h2>
            </div>
            <button
              type="button"
              onClick={() => setIsTocVisible(false)}
              className="rounded-md p-1.5 text-[#8F959E] transition hover:bg-[#DEE0E3] hover:text-[#646A73]"
              title="收起大纲"
            >
              <PanelLeftClose className="h-[18px] w-[18px]" />
            </button>
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
        <div className="absolute left-3 top-4 z-20 hidden md:block">
          <button
            type="button"
            onClick={() => setIsTocVisible(true)}
            className="flex h-8 w-8 items-center justify-center rounded border border-[#DEE0E3] bg-white text-[#646A73] shadow-sm transition hover:bg-[#F8F9FA] hover:text-[#1F2329]"
            title="展开大纲"
          >
            <PanelLeftOpen className="h-[16px] w-[16px]" />
          </button>
        </div>
      ) : null}

      {/* 2. Middle Content Area */}
      <div 
        className={`relative flex min-w-0 flex-col overflow-hidden transition-all duration-500 ease-[cubic-bezier(0.25,1,0.5,1)] bg-white ${
          graphViewMode === "full" ? "w-0 opacity-0 hidden" : "flex-1 w-full"
        }`}
      >
        {/* Minimalist Top Toolbar */}
        <div className="flex items-center justify-between px-6 py-3 border-b border-transparent hover:border-[#F0F2F5] transition-colors shrink-0">
          <div className="flex items-center gap-2">
            {!isTocVisible ? <div className="w-8" /> : null} {/* Spacer if toggle is floating */}
          </div>
          <div className="flex items-center gap-3">
             <button
              type="button"
              onClick={() => updateSettings({ debugMode: !settings.debugMode })}
              title="点击切换测试排版数据"
              className={`inline-flex rounded border px-3 py-1 text-[13px] font-medium cursor-pointer transition ${
                settings.debugMode 
                  ? "border-[#34C759]/30 bg-[#34C759]/10 text-[#248A3D] hover:bg-[#34C759]/20" 
                  : "border-[#DEE0E3] bg-white text-[#646A73] hover:bg-[#F8F9FA]"
              }`}
            >
              <Sparkles className="h-3.5 w-3.5 mr-1.5" />
              {settings.debugMode ? "Debug Mock (运行中)" : "载入测试数据"}
            </button>
            <button
              type="button"
              onClick={() => setIsCommentVisible(!isCommentVisible)}
              className={`inline-flex h-7 items-center gap-1.5 rounded px-2.5 text-[13px] font-medium transition ${
                isCommentVisible ? "bg-[#F0F4FF] text-[#3370FF]" : "text-[#646A73] hover:bg-[#F0F2F5]"
              }`}
            >
              <MessageSquare className="h-3.5 w-3.5" />
              评论
            </button>
          </div>
        </div>

        {/* Restore DocUpdatingBanner */}
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

        {/* The Scrollable Document */}
        <div className="doc-scroll-container content-scroll relative flex-1 overflow-y-auto scroll-smooth" ref={scrollRef}>
          {/* Floating Selection Toolbar */}
          {selection ? (
            <div
              className="absolute z-50 flex items-center gap-1 rounded-[6px] border border-[#DEE0E3] bg-white p-1 shadow-[0_4px_12px_rgba(31,35,41,0.1)] transition-all"
              style={{
                top: `${Math.max(selection.top - 48, 10)}px`,
                left: `${selection.left}px`,
                transform: "translateX(-50%)",
              }}
            >
              <button
                type="button"
                onClick={handleCreateComment}
                className="flex items-center gap-1.5 rounded-[4px] px-2 py-1 text-[13px] font-medium text-[#1F2329] hover:bg-[#F0F2F5] transition"
              >
                <Sparkles className="h-3.5 w-3.5 text-[#3370FF]" />
                划词查问
              </button>
            </div>
          ) : null}

          <div className="mx-auto w-full max-w-[1100px] px-8 md:px-14 pb-32">
            <DocHeader
              title={doc.renderedDocTitle}
              summary={doc.renderedDocSummary}
              digestModeLabel={doc.renderedDigestModeLabel}
              docViewLabel={doc.renderedSubjectLabel}
              updatedLabel={doc.renderedDocUpdatedLabel}
              llmCalls={doc.buildMetrics?.llm_total_calls ?? null}
              chapterHighlights={doc.renderedChapterHighlights}
              className="border-none bg-transparent px-0 pb-2 md:pb-0 pt-8"
            />
            <div className="mt-8">
              <GeminiDocumentViewer content={doc.renderedMarkdown} />
            </div>
          </div>
        </div>
      </div>

      {/* 3. Right Sidebar: Comments (Flush) */}
      {isCommentVisible && graphViewMode !== "full" ? (
        <aside className="hidden h-full w-[310px] shrink-0 border-l border-[#DEE0E3] bg-white xl:block z-10 transition-all">
          <CommentSidebar items={commentItems} onJumpToAnchor={toc.scrollToHeading} onClose={() => setIsCommentVisible(false)} />
        </aside>
      ) : null}

      {/* 4. Sliding Handle for Graph Panel */}
      <div 
        className={`absolute top-1/2 -translate-y-1/2 z-[70] transition-all duration-500 ease-[cubic-bezier(0.25,1,0.5,1)] flex items-center justify-center gap-[2px] ${
          graphViewMode === "hidden" ? "right-0 opacity-90 hover:opacity-100" : 
          graphViewMode === "split" ? "right-[35%] translate-x-1/2 opacity-60 hover:opacity-100" : 
          "left-0 opacity-90 hover:opacity-100"
        }`}
      >
        {graphViewMode !== "full" && (
          <button 
            type="button"
            onClick={openGraphPanel}
            className="group flex items-center justify-center h-[60px] w-5 rounded-l border border-[#DEE0E3] bg-white shadow-sm text-[#8F959E] transition-all hover:bg-[#F8F9FA] hover:text-[#3370FF]"
            title={graphViewMode === "hidden" ? "打开知识图谱" : "全屏图谱"}
          >
            <ChevronLeft className="h-4 w-4" />
          </button>
        )}
        
        {graphViewMode !== "hidden" && (
          <button 
            type="button"
            onClick={closeGraphPanel}
            className="group flex items-center justify-center h-[60px] w-5 rounded-r border border-[#DEE0E3] bg-white shadow-sm text-[#8F959E] transition-all hover:bg-[#F8F9FA] hover:text-[#3370FF]"
            title={graphViewMode === "full" ? "收起图谱" : "收起图谱"}
          >
            <ChevronRight className="h-4 w-4" />
          </button>
        )}
      </div>

      {/* 5. Graph Area Wrapper */}
      <div 
        className={`relative h-full transition-all duration-500 ease-[cubic-bezier(0.25,1,0.5,1)] bg-[#F8F9FA] shrink-0 border-l border-[#DEE0E3] ${
          graphViewMode === "hidden" ? "w-0 overflow-hidden opacity-0" : 
          graphViewMode === "split" ? "w-[35%]" : "flex-1 w-full"
        }`}
      >
        {subjectId && graphViewMode !== "hidden" && (
          <Suspense fallback={
            <div className="flex h-full items-center justify-center">
              <Loader2 className="h-8 w-8 animate-spin text-[#8F959E]" />
            </div>
          }>
            <KnowledgeGraphSidePanel subjectId={subjectId} />
          </Suspense>
        )}
      </div>
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
