import { useState, useRef, useEffect, useMemo, useCallback } from "react";

import ReactMarkdown from "react-markdown";
import remarkMath from "remark-math";
import rehypeKatex from "rehype-katex";
import "katex/dist/katex.min.css";
import {
  FileText,
  ChevronRight,
  Send,
  MoreHorizontal,
  Trash2,
  Clock,
} from "lucide-react";
import { useParams } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";

import { cn } from "../lib/utils";
import { TopBar } from "../components/layout/TopBar";
import { fetchDocGenContent } from "../api/graphApi";
import {
  DocGenBuildProvider,
  DocGenBuildButton,
  DocGenBuildProgress,
} from "../components/pages/DocGenBuildPanel";

/* ------------------------------------------------------------------ */
/*  Types                                                              */
/* ------------------------------------------------------------------ */

interface TocItem {
  id: string;
  text: string;
  level: number;
}

interface Comment {
  id: string;
  anchorId: string;
  selectedText: string;
  author: string;
  content: string;
  createdAt: number;
  resolved: boolean;
}

interface FloatingComment {
  anchorId: string;
  selectedText: string;
  top: number;
}

/* ------------------------------------------------------------------ */
/*  Demo markdown                                                      */
/* ------------------------------------------------------------------ */

const DEMO_MARKDOWN = `# 课程概述

本课程旨在帮助学生系统性地掌握核心知识点，通过理论与实践相结合的方式，深入理解学科的基本概念和应用场景。

## 学习目标

通过本课程的学习，你将能够：

- 理解学科的基本概念和核心理论
- 掌握常用的分析方法和工具
- 能够独立完成相关的实践项目
- 具备进一步深入学习的基础

## 第一章：基础概念

### 1.1 核心定义

在开始深入学习之前，我们需要先明确几个核心概念。这些概念是整个学科体系的基石，理解它们对于后续的学习至关重要。

> 知识的积累是一个循序渐进的过程，每一个概念都建立在前一个概念的基础之上。

### 1.2 基本原理

基本原理是指导我们理解和分析问题的核心框架。掌握这些原理，能够帮助我们在面对复杂问题时，找到正确的分析思路。

| 原理 | 描述 | 应用场景 |
|------|------|----------|
| 原理一 | 系统性思维 | 复杂问题分析 |
| 原理二 | 抽象建模 | 模型构建 |
| 原理三 | 迭代优化 | 持续改进 |

### 1.3 发展历程

学科的发展经历了多个重要阶段，每个阶段都有其标志性的突破和贡献。了解这些历史，有助于我们更好地理解当前的知识体系。

## 第二章：核心理论

### 2.1 理论框架

理论框架为我们提供了一个系统化的视角来审视和理解问题。一个好的理论框架应该具备以下特征：

1. **完整性**：能够覆盖所有关键方面
2. **一致性**：内部逻辑自洽
3. **可验证性**：可以通过实验或观察来验证
4. **简洁性**：用最少的假设解释最多的现象

### 2.2 关键定理

关键定理是理论体系中最重要的结论，它们经过严格的证明，具有普遍的适用性。

$$
E = mc^2
$$

这个著名的公式揭示了质量与能量之间的等价关系，是现代物理学的基石之一。

### 2.3 应用方法

将理论应用到实际问题中，需要掌握一套系统的方法论。以下是常用的分析步骤：

1. 问题定义与分析
2. 模型选择与构建
3. 参数估计与验证
4. 结果解释与应用

## 第三章：实践应用

### 3.1 案例分析

通过具体的案例，我们可以更直观地理解理论的应用方式。每个案例都包含了完整的分析过程和结论。

\`\`\`python
# 示例代码
def analyze(data):
    """对数据进行分析处理"""
    result = preprocess(data)
    model = build_model(result)
    return model.predict()
\`\`\`

### 3.2 实验设计

良好的实验设计是获得可靠结果的前提。在设计实验时，需要考虑以下因素：

- **变量控制**：明确自变量和因变量
- **样本选择**：确保样本的代表性
- **重复性**：保证实验结果可重复

### 3.3 结果评估

对实验结果的评估需要采用科学的方法，避免主观偏见的影响。常用的评估指标包括准确率、召回率、F1 分数等。

## 总结与展望

本课程涵盖了从基础概念到实践应用的完整知识体系。通过系统的学习，相信你已经对这个学科有了全面的了解。

未来的学习方向包括：

- 深入研究特定领域的前沿问题
- 参与实际项目，积累实践经验
- 关注学科的最新发展动态
`;

/* ------------------------------------------------------------------ */
/*  Helpers                                                            */
/* ------------------------------------------------------------------ */

function textToId(text: string): string {
  return text
    .toLowerCase()
    .replace(/[^\w\u4e00-\u9fff]+/g, "-")
    .replace(/^-|-$/g, "");
}

function extractToc(md: string): TocItem[] {
  const items: TocItem[] = [];
  for (const line of md.split("\n")) {
    const match = line.match(/^(#{1,4})\s+(.+)$/);
    if (match) {
      const level = match[1].length;
      const text = match[2].trim();
      items.push({ id: textToId(text), text, level });
    }
  }
  return items;
}

function formatTime(ts: number): string {
  const d = new Date(ts);
  const pad = (n: number) => String(n).padStart(2, "0");
  return `${d.getMonth() + 1}/${d.getDate()} ${pad(d.getHours())}:${pad(d.getMinutes())}`;
}

/** Recursively extract plain text from React children */
function extractText(node: React.ReactNode): string {
  if (typeof node === "string") return node;
  if (typeof node === "number") return String(node);
  if (!node) return "";
  if (Array.isArray(node)) return node.map(extractText).join("");
  if (typeof node === "object" && "props" in node) {
    return extractText((node as React.ReactElement).props.children);
  }
  return "";
}

/* ------------------------------------------------------------------ */
/*  DocMarkdown                                                        */
/* ------------------------------------------------------------------ */

function DocMarkdown({ content }: { content: string }) {
  const makeHeading = (level: 1 | 2 | 3 | 4) => {
    const Tag = `h${level}` as const;
    const styles: Record<number, string> = {
      1: "text-[26px] font-bold text-slate-900 mt-8 mb-4 pb-3 border-b border-slate-200",
      2: "text-[22px] font-semibold text-slate-800 mt-7 mb-3",
      3: "text-[18px] font-semibold text-slate-800 mt-5 mb-2",
      4: "text-base font-semibold text-slate-700 mt-4 mb-2",
    };
    return ({ children }: { children?: React.ReactNode }) => {
      const text = extractText(children);
      const id = textToId(text);
      return (
        <Tag id={id} data-heading-id={id} className={styles[level]}>
          {children}
        </Tag>
      );
    };
  };

  return (
    <ReactMarkdown
      remarkPlugins={[remarkMath]}
      rehypePlugins={[rehypeKatex]}
      components={{
        h1: makeHeading(1),
        h2: makeHeading(2),
        h3: makeHeading(3),
        h4: makeHeading(4),
        p: ({ children }) => (
          <p className="text-[15px] text-slate-700 leading-[1.8] mb-4">{children}</p>
        ),
        ul: ({ children }) => (
          <ul className="list-disc text-[15px] text-slate-700 mb-4 space-y-1.5 pl-6">{children}</ul>
        ),
        ol: ({ children }) => (
          <ol className="list-decimal text-[15px] text-slate-700 mb-4 space-y-1.5 pl-6">{children}</ol>
        ),
        li: ({ children }) => (
          <li className="leading-[1.8] [&>p]:inline [&>p]:mb-0">{children}</li>
        ),
        blockquote: ({ children }) => (
          <blockquote className="border-l-4 border-blue-200 bg-blue-50/40 pl-4 pr-3 py-2 text-slate-600 my-4 rounded-r-lg">
            {children}
          </blockquote>
        ),
        code: ({ className, children }) => {
          const isBlock = className?.includes("language-");
          if (isBlock) {
            return (
              <pre className="bg-slate-900 text-slate-100 rounded-lg p-4 overflow-x-auto text-sm my-4 leading-relaxed">
                <code>{children}</code>
              </pre>
            );
          }
          return (
            <code className="bg-slate-100 text-slate-800 rounded px-1.5 py-0.5 text-sm font-mono">
              {children}
            </code>
          );
        },
        pre: ({ children }) => <>{children}</>,
        table: ({ children }) => (
          <div className="overflow-x-auto my-4">
            <table className="min-w-full text-sm border border-slate-200 rounded-lg">{children}</table>
          </div>
        ),
        thead: ({ children }) => (
          <thead className="bg-slate-50 border-b border-slate-200">{children}</thead>
        ),
        th: ({ children }) => (
          <th className="px-4 py-2.5 text-left font-semibold text-slate-700">{children}</th>
        ),
        td: ({ children }) => (
          <td className="px-4 py-2.5 text-slate-600 border-t border-slate-100">{children}</td>
        ),
        hr: () => <hr className="my-6 border-slate-200" />,
        a: ({ href, children }) => (
          <a href={href} className="text-blue-600 hover:underline" target="_blank" rel="noopener noreferrer">
            {children}
          </a>
        ),
        strong: ({ children }) => <strong className="font-semibold text-slate-900">{children}</strong>,
        em: ({ children }) => <em className="italic text-slate-600">{children}</em>,
      }}
    >
      {content}
    </ReactMarkdown>
  );
}

/* ------------------------------------------------------------------ */
/*  CommentBubbles                                                     */
/* ------------------------------------------------------------------ */

function CommentBubbles({
  anchorId,
  comments,
  scrollRef,
  menuOpenId,
  setMenuOpenId,
  onResolve,
  onDelete,
}: {
  anchorId: string;
  comments: Comment[];
  scrollRef: React.RefObject<HTMLDivElement | null>;
  menuOpenId: string | null;
  setMenuOpenId: (id: string | null) => void;
  onResolve: (id: string) => void;
  onDelete: (id: string) => void;
}) {
  const [top, setTop] = useState(0);

  useEffect(() => {
    const container = scrollRef.current;
    if (!container) return;
    const heading = container.querySelector(`[data-heading-id="${anchorId}"]`);
    if (!heading) return;

    const update = () => {
      setTop((heading as HTMLElement).offsetTop);
    };

    update();
    // Recalculate on resize
    const ro = new ResizeObserver(update);
    ro.observe(container);
    return () => ro.disconnect();
  }, [anchorId, scrollRef]);

  if (top <= 0) return null;

  return (
    <div className="absolute left-2" style={{ top }}>
      {comments.map((comment) => (
        <div
          key={comment.id}
          className={cn(
            "mb-2 w-56 bg-white border border-slate-200 rounded-lg shadow-sm group hover:shadow-md transition-shadow",
            comment.resolved && "opacity-50"
          )}
        >
          <div className="px-3 py-2">
            <div className="flex items-center justify-between mb-1">
              <div className="flex items-center gap-1.5">
                <div className="w-5 h-5 rounded-full bg-blue-500 text-white text-[10px] flex items-center justify-center font-medium">
                  {comment.author[0]}
                </div>
                <span className="text-xs font-medium text-slate-700">{comment.author}</span>
                <span className="text-[10px] text-slate-400 flex items-center gap-0.5">
                  <Clock className="w-2.5 h-2.5" />
                  {formatTime(comment.createdAt)}
                </span>
              </div>
              <div className="relative">
                <button
                  onClick={() => setMenuOpenId(menuOpenId === comment.id ? null : comment.id)}
                  className="p-0.5 rounded hover:bg-slate-100 opacity-0 group-hover:opacity-100 transition-opacity"
                >
                  <MoreHorizontal className="w-3.5 h-3.5 text-slate-400" />
                </button>
                {menuOpenId === comment.id && (
                  <div className="absolute right-0 top-6 bg-white border border-slate-200 rounded-lg shadow-lg py-1 z-20 min-w-[90px]">
                    <button
                      onClick={() => onResolve(comment.id)}
                      className="w-full text-left px-3 py-1.5 text-xs text-slate-600 hover:bg-slate-50"
                    >
                      {comment.resolved ? "重新打开" : "标记解决"}
                    </button>
                    <button
                      onClick={() => onDelete(comment.id)}
                      className="w-full text-left px-3 py-1.5 text-xs text-red-500 hover:bg-red-50 flex items-center gap-1"
                    >
                      <Trash2 className="w-3 h-3" />
                      删除
                    </button>
                  </div>
                )}
              </div>
            </div>
            {comment.selectedText && (
              <p className="text-[11px] text-blue-500 mb-1 truncate">&ldquo;{comment.selectedText}&rdquo;</p>
            )}
            <p className={cn(
              "text-xs text-slate-600 leading-relaxed",
              comment.resolved && "line-through"
            )}>
              {comment.content}
            </p>
          </div>
        </div>
      ))}
    </div>
  );
}

/* ------------------------------------------------------------------ */
/*  DocPage                                                            */
/* ------------------------------------------------------------------ */

export function DocPage() {
  const { subjectId = "" } = useParams();

  // 获取真实的 markdown
  const { data: contentData } = useQuery({
    queryKey: ["docgen-content", subjectId],
    queryFn: () => fetchDocGenContent(subjectId),
    enabled: !!subjectId,
  });

  const markdown = contentData?.markdown || "";
  const isDemo = !markdown;
  const displayMarkdown = markdown || DEMO_MARKDOWN;

  const [activeHeading, setActiveHeading] = useState("");
  const [comments, setComments] = useState<Comment[]>([]);
  const [menuOpenId, setMenuOpenId] = useState<string | null>(null);
  const [isTocCollapsed, setIsTocCollapsed] = useState(false);
  const [pageWidth, setPageWidth] = useState<"narrow" | "wide">("narrow");

  // Floating comment popup state
  const [floatingComment, setFloatingComment] = useState<FloatingComment | null>(null);
  const [floatingInput, setFloatingInput] = useState("");

  const scrollRef = useRef<HTMLDivElement>(null);
  const contentAreaRef = useRef<HTMLDivElement>(null);
  const floatingRef = useRef<HTMLDivElement>(null);

  const toc = useMemo(() => extractToc(displayMarkdown), [displayMarkdown]);

  // Track active heading on scroll — uses the single scroll container
  useEffect(() => {
    const container = scrollRef.current;
    if (!container) return;

    let timeout: ReturnType<typeof setTimeout> | null = null;
    let localActive = "";

    const handleScroll = () => {
      if (timeout) return;
      timeout = setTimeout(() => {
        timeout = null;
        const headings = container.querySelectorAll("[data-heading-id]");
        let current = "";
        for (const el of headings) {
          const rect = el.getBoundingClientRect();
          if (rect.top <= 120) {
            current = el.getAttribute("data-heading-id") ?? "";
          } else {
            // Because they appear in DOM order, once we see one below our threshold, we can stop
            break;
          }
        }
        if (current !== localActive) {
          localActive = current;
          setActiveHeading(current);
        }
      }, 60);
    };

    container.addEventListener("scroll", handleScroll, { passive: true });
    handleScroll();
    return () => {
      container.removeEventListener("scroll", handleScroll);
      if (timeout) clearTimeout(timeout);
    };
  }, [displayMarkdown]);

  const scrollToHeading = useCallback((id: string) => {
    const container = scrollRef.current;
    if (!container) return;
    const el = container.querySelector(`[data-heading-id="${id}"]`);
    if (el) {
      const containerRect = container.getBoundingClientRect();
      const elRect = el.getBoundingClientRect();
      container.scrollTop += elRect.top - containerRect.top - 16;
    }
  }, []);

  // Close floating comment when clicking outside
  useEffect(() => {
    const handleClickOutside = (e: MouseEvent) => {
      if (floatingRef.current && !floatingRef.current.contains(e.target as Node)) {
        setFloatingComment(null);
        setFloatingInput("");
      }
    };
    if (floatingComment) {
      document.addEventListener("mousedown", handleClickOutside);
      return () => document.removeEventListener("mousedown", handleClickOutside);
    }
  }, [floatingComment]);

  const addComment = useCallback(() => {
    if (!floatingInput.trim() || !floatingComment) return;
    setComments((prev) => [
      ...prev,
      {
        id: Date.now().toString(),
        anchorId: floatingComment.anchorId,
        selectedText: floatingComment.selectedText,
        author: "我",
        content: floatingInput.trim(),
        createdAt: Date.now(),
        resolved: false,
      },
    ]);
    setFloatingInput("");
    setFloatingComment(null);
    window.getSelection()?.removeAllRanges();
  }, [floatingInput, floatingComment]);

  const deleteComment = useCallback((id: string) => {
    setComments((prev) => prev.filter((c) => c.id !== id));
    setMenuOpenId(null);
  }, []);

  const resolveComment = useCallback((id: string) => {
    setComments((prev) =>
      prev.map((c) => (c.id === id ? { ...c, resolved: !c.resolved } : c))
    );
    setMenuOpenId(null);
  }, []);

  // Feishu-style: detect text selection and show floating comment near selection
  const handleTextSelect = useCallback(() => {
    const sel = window.getSelection();
    if (!sel || sel.isCollapsed || !sel.toString().trim()) return;

    const selectedText = sel.toString().trim();
    const range = sel.getRangeAt(0);
    const rect = range.getBoundingClientRect();
    const container = scrollRef.current;
    if (!container) return;
    const containerRect = container.getBoundingClientRect();

    // Find nearest heading above the selection
    let node: Node | null = sel.anchorNode;
    let headingId = "";
    while (node && node !== container) {
      if (node instanceof HTMLElement) {
        const hid = node.getAttribute("data-heading-id");
        if (hid) { headingId = hid; break; }
      }
      node = node.parentNode;
    }
    if (!headingId) {
      const allHeadings = container.querySelectorAll("[data-heading-id]");
      for (const h of allHeadings) {
        const hRange = document.createRange();
        hRange.selectNode(h);
        if (hRange.compareBoundaryPoints(Range.START_TO_START, range) <= 0) {
          headingId = h.getAttribute("data-heading-id") ?? "";
        }
      }
    }

    if (headingId) {
      const top = rect.top - containerRect.top + container.scrollTop;
      setFloatingComment({
        anchorId: headingId,
        selectedText: selectedText.slice(0, 60),
        top,
      });
      setFloatingInput("");
    }
  }, []);

  const unresolvedComments = comments.filter((c) => !c.resolved);
  const showCommentLane = unresolvedComments.length > 0;

  // Group comments by anchor for inline display
  const commentsByAnchor = useMemo(() => {
    const map = new Map<string, Comment[]>();
    for (const c of unresolvedComments) {
      const list = map.get(c.anchorId) ?? [];
      list.push(c);
      map.set(c.anchorId, list);
    }
    return map;
  }, [unresolvedComments]);

  const commentsForAnchor = useCallback(
    (anchorId: string) => commentsByAnchor.get(anchorId)?.length ?? 0,
    [commentsByAnchor]
  );

  return (
    <DocGenBuildProvider subject={subjectId}>
    <div className="relative h-screen overflow-hidden bg-slate-100/60">
      <div className="absolute top-3 right-4 z-40">
        <TopBar />
      </div>

      <div className="hidden lg:block absolute left-4 top-1/2 -translate-y-1/2 z-30">
        {isTocCollapsed ? (
          <button
            onClick={() => setIsTocCollapsed(false)}
            className="h-11 w-11 rounded-xl border border-slate-200 bg-white shadow-sm text-slate-500 hover:text-slate-700 hover:bg-slate-50 transition-colors flex items-center justify-center"
            aria-label="展开目录"
          >
            <ChevronRight className="w-4 h-4" />
          </button>
        ) : (
          <aside className="w-64 h-[78vh] max-h-[760px] rounded-2xl border border-slate-200 bg-white/95 backdrop-blur-sm shadow-lg flex flex-col overflow-hidden">
            <div className="px-3 h-11 border-b border-slate-200/70 flex items-center justify-between">
              <div className="flex items-center gap-2 text-slate-900">
                <FileText className="w-4 h-4" />
                <span className="text-sm font-semibold">目录</span>
              </div>
              <button
                onClick={() => setIsTocCollapsed(true)}
                className="w-7 h-7 rounded-lg hover:bg-slate-100 transition-colors flex items-center justify-center text-slate-500 hover:text-slate-700"
                aria-label="收起目录"
              >
                <ChevronRight className="w-4 h-4 rotate-180" />
              </button>
            </div>
            <nav className="flex-1 overflow-y-auto py-2 px-2">
              {toc.map((item) => {
                const count = commentsForAnchor(item.id);
                return (
                  <button
                    key={item.id}
                    onClick={() => scrollToHeading(item.id)}
                    className={cn(
                      "group w-full text-left px-2 py-1.5 rounded-md text-[13px] transition-all duration-150 flex items-center gap-1",
                      item.level === 1 && "font-semibold text-slate-900 mt-2 first:mt-0",
                      item.level === 2 && "pl-4 text-slate-700",
                      item.level === 3 && "pl-7 text-slate-500",
                      item.level === 4 && "pl-9 text-slate-400",
                      activeHeading === item.id
                        ? "bg-blue-50 text-blue-700 font-medium"
                        : "hover:bg-slate-100"
                    )}
                  >
                    {item.level > 1 && (
                      <ChevronRight
                        className={cn(
                          "w-3 h-3 shrink-0",
                          activeHeading === item.id ? "text-blue-400" : "text-slate-300"
                        )}
                      />
                    )}
                    <span className="truncate flex-1">{item.text}</span>
                    {count > 0 && (
                      <span className="shrink-0 w-4 h-4 rounded-full bg-blue-100 text-blue-600 text-[10px] flex items-center justify-center font-medium">
                        {count}
                      </span>
                    )}
                  </button>
                );
              })}
            </nav>
          </aside>
        )}
      </div>

      <div className="hidden lg:flex absolute right-4 top-16 z-30 flex-col gap-2 pointer-events-none">
        <div className="pointer-events-auto">
          <DocGenBuildButton />
        </div>
        <div className="pointer-events-auto w-[280px]">
          <DocGenBuildProgress />
        </div>
      </div>

      <div className="hidden lg:block absolute right-4 top-1/2 -translate-y-1/2 z-30">
        <div className="rounded-xl border border-slate-200 bg-white/95 backdrop-blur-sm shadow-sm p-1.5 flex flex-col gap-1">
          <button
            onClick={() => setPageWidth("narrow")}
            className={cn(
              "px-3 py-1.5 rounded-lg text-xs font-medium transition-colors",
              pageWidth === "narrow"
                ? "bg-slate-900 text-white"
                : "text-slate-600 hover:bg-slate-100"
            )}
          >
            窄页
          </button>
          <button
            onClick={() => setPageWidth("wide")}
            className={cn(
              "px-3 py-1.5 rounded-lg text-xs font-medium transition-colors",
              pageWidth === "wide"
                ? "bg-slate-900 text-white"
                : "text-slate-600 hover:bg-slate-100"
            )}
          >
            宽页
          </button>
        </div>
      </div>

      <div
        ref={scrollRef}
        className="h-full overflow-y-auto relative"
        onMouseUp={handleTextSelect}
      >
        <div
          className={cn(
            "min-h-full pr-4 lg:pr-20 transition-[padding-left] duration-300 pl-4 md:pl-6",
            isTocCollapsed ? "lg:pl-16" : "lg:pl-[18.5rem]"
          )}
        >
          <div className="mx-auto max-w-[1500px] px-6 py-8">
            <div
              ref={contentAreaRef}
              className={cn(
                "mx-auto flex min-h-full transition-[max-width] duration-300",
                pageWidth === "wide" ? "max-w-[1260px]" : "max-w-[980px]"
              )}
            >
              <article
                className={cn(
                  "min-w-0 flex-1 rounded-2xl border border-slate-200 bg-white shadow-sm px-8 py-8 md:px-12 md:py-10 transition-[max-width] duration-300 relative",
                  pageWidth === "wide" ? "max-w-[980px]" : "max-w-[760px]"
                )}
              >
                {isDemo && (
                  <div className="absolute top-4 right-4 bg-amber-50 text-amber-600 text-xs px-2 py-1 rounded border border-amber-200">
                    此为示例数据，请点击右上角「构建知识文档」生成真实数据
                  </div>
                )}
                <DocMarkdown content={displayMarkdown} />
              </article>

              <div
                className={cn(
                  "relative shrink-0 transition-all duration-300",
                  showCommentLane ? "w-64 pl-4" : "w-0"
                )}
              >
                {showCommentLane &&
                  Array.from(commentsByAnchor.entries()).map(([anchorId, anchorComments]) => (
                    <CommentBubbles
                      key={anchorId}
                      anchorId={anchorId}
                      comments={anchorComments}
                      scrollRef={scrollRef}
                      menuOpenId={menuOpenId}
                      setMenuOpenId={setMenuOpenId}
                      onResolve={resolveComment}
                      onDelete={deleteComment}
                    />
                  ))}
              </div>
            </div>
          </div>

          {floatingComment && (
            <div
              ref={floatingRef}
              className="absolute z-50 bg-white rounded-lg shadow-lg border border-slate-200 w-72"
              style={{
                top: floatingComment.top + 24,
                right: showCommentLane ? 24 : 40,
              }}
            >
              <div className="px-3 py-2 border-b border-slate-100 bg-slate-50/80 rounded-t-lg">
                <p className="text-xs text-slate-500 truncate">&ldquo;{floatingComment.selectedText}&rdquo;</p>
              </div>
              <div className="p-3">
                <textarea
                  value={floatingInput}
                  onChange={(e) => setFloatingInput(e.target.value)}
                  onKeyDown={(e) => {
                    if (e.key === "Enter" && !e.shiftKey) {
                      e.preventDefault();
                      addComment();
                    }
                    if (e.key === "Escape") {
                      setFloatingComment(null);
                      setFloatingInput("");
                    }
                  }}
                  placeholder="添加评论..."
                  rows={2}
                  className="w-full text-sm border border-slate-200 rounded-lg px-3 py-2 focus:outline-none focus:ring-2 focus:ring-blue-200 focus:border-blue-300 resize-none"
                  autoFocus
                />
                <div className="flex items-center justify-between mt-2">
                  <button
                    onClick={() => { setFloatingComment(null); setFloatingInput(""); }}
                    className="text-xs text-slate-400 hover:text-slate-600"
                  >
                    取消
                  </button>
                  <button
                    onClick={addComment}
                    disabled={!floatingInput.trim()}
                    className={cn(
                      "flex items-center gap-1 px-3 py-1.5 rounded-lg text-xs font-medium transition-colors",
                      floatingInput.trim()
                        ? "bg-blue-500 text-white hover:bg-blue-600"
                        : "bg-slate-100 text-slate-300"
                    )}
                  >
                    <Send className="w-3 h-3" />
                    评论
                  </button>
                </div>
              </div>
            </div>
          )}
        </div>
      </div>
    </div>
    </DocGenBuildProvider>
  );
}
