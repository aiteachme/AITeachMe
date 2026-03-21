import { memo, useState, useRef, useEffect, useMemo, useCallback } from "react";

import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import remarkMath from "remark-math";
import rehypeHighlight from "rehype-highlight";
import rehypeKatex from "rehype-katex";
import "katex/dist/katex.min.css";
import {
  FileText,
  ChevronRight,
  ChevronDown,
  ChevronUp,
  Send,
  MessageSquarePlus,
  MoreHorizontal,
  Trash2,
  Clock,
  Bot,
} from "lucide-react";
import { useNavigate, useParams } from "react-router-dom";
import { cn } from "../lib/utils";
import { TopBar } from "../components/layout/TopBar";

/* ------------------------------------------------------------------ */
/*  Types                                                              */
/* ------------------------------------------------------------------ */

interface TocItem {
  id: string;
  text: string;
  level: number;
}

type HeadingLevel = 1 | 2 | 3 | 4 | 5 | 6;

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
  selectionViewportTop: number;
  top: number;
}

interface FloatingToolbar {
  anchorId: string;
  selectedText: string;
  top: number;
  left: number;
  selectionViewportTop: number;
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

function createHeadingIdFactory() {
  const counts = new Map<string, number>();
  return (text: string) => {
    const base = textToId(text) || "section";
    const next = (counts.get(base) ?? 0) + 1;
    counts.set(base, next);
    return next === 1 ? base : `${base}-${next}`;
  };
}

function formatTime(ts: number): string {
  const d = new Date(ts);
  const pad = (n: number) => String(n).padStart(2, "0");
  return `${d.getMonth() + 1}/${d.getDate()} ${pad(d.getHours())}:${pad(d.getMinutes())}`;
}

const COMMENT_THREAD_GAP = 12;
const COMMENT_THREAD_DEFAULT_HEIGHT = 140;
const COMMENT_THREAD_TOP_PADDING = 8;
const COMMENT_THREAD_BOTTOM_PADDING = 10;
const COMMENT_THREAD_EDGE_FADE = 68;
const COMMENT_THREAD_HIDE_OFFSET = 28;
const COMPACT_PANEL_BREAKPOINT = 1536;

function numberRecordEqual(a: Record<string, number>, b: Record<string, number>): boolean {
  const aKeys = Object.keys(a);
  const bKeys = Object.keys(b);
  if (aKeys.length !== bKeys.length) return false;
  for (const key of aKeys) {
    if (Math.abs((a[key] ?? 0) - (b[key] ?? 0)) > 0.5) return false;
  }
  return true;
}

function tocEqual(a: TocItem[], b: TocItem[]): boolean {
  if (a.length !== b.length) return false;
  for (let i = 0; i < a.length; i += 1) {
    if (
      a[i].id !== b[i].id ||
      a[i].text !== b[i].text ||
      a[i].level !== b[i].level
    ) {
      return false;
    }
  }
  return true;
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

const DocMarkdown = memo(function DocMarkdown({ content }: { content: string }) {
  const nextHeadingId = useMemo(() => createHeadingIdFactory(), [content]);
  const makeHeading = (level: HeadingLevel) => {
    const Tag = `h${level}` as const;
    const styles: Record<number, string> = {
      1: "text-[26px] font-bold text-slate-900 mt-8 mb-4 pb-3 border-b border-slate-200",
      2: "text-[22px] font-semibold text-slate-800 mt-7 mb-3",
      3: "text-[18px] font-semibold text-slate-800 mt-5 mb-2",
      4: "text-base font-semibold text-slate-700 mt-4 mb-2",
      5: "text-[15px] font-semibold text-slate-700 mt-3.5 mb-2",
      6: "text-sm font-semibold uppercase tracking-wide text-slate-500 mt-3 mb-1.5",
    };
    return ({ children }: { children?: React.ReactNode }) => {
      const text = extractText(children);
      const id = nextHeadingId(text);
      return (
        <Tag id={id} data-heading-id={id} className={styles[level]}>
          {children}
        </Tag>
      );
    };
  };

  return (
    <ReactMarkdown
      remarkPlugins={[remarkGfm, remarkMath]}
      rehypePlugins={[rehypeKatex, rehypeHighlight]}
      components={{
        h1: makeHeading(1),
        h2: makeHeading(2),
        h3: makeHeading(3),
        h4: makeHeading(4),
        h5: makeHeading(5),
        h6: makeHeading(6),
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
          const codeText = String(children);
          const isBlock = Boolean(className) || codeText.includes("\n");
          if (isBlock) {
            return <code className={cn("font-mono text-[13px]", className)}>{children}</code>;
          }
          return (
            <code className={cn("bg-slate-100 text-slate-800 rounded px-1.5 py-0.5 text-sm font-mono", className)}>
              {children}
            </code>
          );
        },
        pre: ({ children }) => (
          <pre className="bg-slate-900 text-slate-100 rounded-lg p-4 overflow-x-auto text-sm my-4 leading-relaxed">
            {children}
          </pre>
        ),
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
});

/* ------------------------------------------------------------------ */
/*  CommentList                                                        */
/* ------------------------------------------------------------------ */

function CommentCard({
  comment,
  menuOpenId,
  setMenuOpenId,
  onResolve,
  onDelete,
}: {
  comment: Comment;
  menuOpenId: string | null;
  setMenuOpenId: (id: string | null) => void;
  onResolve: (id: string) => void;
  onDelete: (id: string) => void;
}) {
  return (
    <div
      className={cn(
        "w-full bg-white border border-slate-200 rounded-lg shadow-sm group hover:shadow-md transition-shadow",
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
        <p
          className={cn(
            "text-xs text-slate-600 leading-relaxed",
            comment.resolved && "line-through"
          )}
        >
          {comment.content}
        </p>
      </div>
    </div>
  );
}

function CommentThread({
  anchorId,
  title,
  comments,
  isActive,
  menuOpenId,
  setMenuOpenId,
  onResolve,
  onDelete,
  onJumpToAnchor,
}: {
  anchorId: string;
  title: string;
  comments: Comment[];
  isActive: boolean;
  menuOpenId: string | null;
  setMenuOpenId: (id: string | null) => void;
  onResolve: (id: string) => void;
  onDelete: (id: string) => void;
  onJumpToAnchor: (id: string) => void;
}) {
  return (
    <section
      className={cn(
        "rounded-xl border bg-slate-50/60 shadow-sm overflow-hidden transition-colors",
        isActive ? "border-blue-300 shadow-blue-100/80" : "border-slate-200"
      )}
    >
      <div className="px-3 py-2 border-b border-slate-200 bg-white flex items-center justify-between gap-2">
        <button
          onClick={() => onJumpToAnchor(anchorId)}
          className="text-left text-xs font-semibold text-slate-700 hover:text-blue-600 truncate"
        >
          {title}
        </button>
        <span className="shrink-0 rounded-full bg-blue-100 text-blue-700 text-[10px] px-2 py-0.5 font-medium">
          {comments.length}
        </span>
      </div>
      <div className="p-2 space-y-2">
        {comments.map((comment) => (
          <CommentCard
            key={comment.id}
            comment={comment}
            menuOpenId={menuOpenId}
            setMenuOpenId={setMenuOpenId}
            onResolve={onResolve}
            onDelete={onDelete}
          />
        ))}
      </div>
    </section>
  );
}

/* ------------------------------------------------------------------ */
/*  DocPage                                                            */
/* ------------------------------------------------------------------ */

export function DocPage() {
  const navigate = useNavigate();
  const { subjectId } = useParams<{ subjectId: string }>();
  const [markdown] = useState(DEMO_MARKDOWN);
  const [toc, setToc] = useState<TocItem[]>([]);
  const [activeHeading, setActiveHeading] = useState("");
  const [comments, setComments] = useState<Comment[]>([]);
  const [menuOpenId, setMenuOpenId] = useState<string | null>(null);
  const [isTocCollapsed, setIsTocCollapsed] = useState(false);
  const [isCommentCollapsed, setIsCommentCollapsed] = useState(false);

  // Floating selection toolbar state
  const [floatingToolbar, setFloatingToolbar] = useState<FloatingToolbar | null>(null);
  const [floatingComment, setFloatingComment] = useState<FloatingComment | null>(null);
  const [floatingInput, setFloatingInput] = useState("");
  const [threadHeights, setThreadHeights] = useState<Record<string, number>>({});
  const [threadTops, setThreadTops] = useState<Record<string, number>>({});
  const [threadOpacity, setThreadOpacity] = useState<Record<string, number>>({});
  const [isCompactPanels, setIsCompactPanels] = useState(() =>
    typeof window !== "undefined" ? window.innerWidth < COMPACT_PANEL_BREAKPOINT : false
  );
  const [activeDrawer, setActiveDrawer] = useState<"toc" | "comment" | null>(null);

  const scrollRef = useRef<HTMLDivElement>(null);
  const contentAreaRef = useRef<HTMLDivElement>(null);
  const floatingRef = useRef<HTMLDivElement>(null);
  const commentPanelRef = useRef<HTMLDivElement>(null);
  const commentViewportRef = useRef<HTMLDivElement>(null);
  const selectedRangeRef = useRef<Range | null>(null);
  const threadRefs = useRef(new Map<string, HTMLDivElement>());
  const headingFlashTimersRef = useRef(new Map<string, number>());

  const isTocVisible = isCompactPanels ? activeDrawer === "toc" : !isTocCollapsed;
  const isCommentVisible = isCompactPanels ? activeDrawer === "comment" : !isCommentCollapsed;

  const activeTocItem = useMemo(
    () => toc.find((item) => item.id === activeHeading) ?? null,
    [activeHeading, toc]
  );

  useEffect(() => {
    const rafId = window.requestAnimationFrame(() => {
      const container = scrollRef.current;
      if (!container) return;
      const headingNodes = container.querySelectorAll<HTMLElement>("[data-heading-id]");
      const nextToc: TocItem[] = Array.from(headingNodes)
        .map((node) => {
          const id = node.getAttribute("data-heading-id") ?? node.id;
          if (!id) return null;
          const level = Number(node.tagName.replace("H", ""));
          if (!Number.isInteger(level) || level < 1 || level > 6) return null;
          const text = node.textContent?.trim() || id;
          return { id, text, level };
        })
        .filter((item): item is TocItem => item !== null);
      setToc((prev) => (tocEqual(prev, nextToc) ? prev : nextToc));
    });
    return () => window.cancelAnimationFrame(rafId);
  }, [markdown]);

  useEffect(() => {
    const syncCompactMode = () => {
      setIsCompactPanels(window.innerWidth < COMPACT_PANEL_BREAKPOINT);
    };
    syncCompactMode();
    window.addEventListener("resize", syncCompactMode);
    return () => window.removeEventListener("resize", syncCompactMode);
  }, []);

  useEffect(() => {
    if (!isCompactPanels) {
      setActiveDrawer(null);
    }
  }, [isCompactPanels]);

  useEffect(() => {
    return () => {
      for (const timer of headingFlashTimersRef.current.values()) {
        window.clearTimeout(timer);
      }
      headingFlashTimersRef.current.clear();
    };
  }, []);

  // Track active heading on scroll — uses the single scroll container
  useEffect(() => {
    const container = scrollRef.current;
    if (!container) return;

    const handleScroll = () => {
      const headings = container.querySelectorAll("[data-heading-id]");
      let current = "";
      for (const el of headings) {
        const rect = el.getBoundingClientRect();
        if (rect.top <= 120) {
          current = el.getAttribute("data-heading-id") ?? "";
        }
      }
      setActiveHeading(current);
    };

    container.addEventListener("scroll", handleScroll, { passive: true });
    handleScroll();
    return () => container.removeEventListener("scroll", handleScroll);
  }, [markdown]);

  const flashHeading = useCallback((node: HTMLElement) => {
    const headingId = node.getAttribute("data-heading-id") ?? node.id;
    const existingTimer = headingFlashTimersRef.current.get(headingId);
    if (existingTimer) {
      window.clearTimeout(existingTimer);
    }
    node.classList.remove("heading-flash");
    void node.offsetWidth;
    node.classList.add("heading-flash");
    const timer = window.setTimeout(() => {
      node.classList.remove("heading-flash");
      headingFlashTimersRef.current.delete(headingId);
    }, 950);
    headingFlashTimersRef.current.set(headingId, timer);
  }, []);

  const scrollToHeading = useCallback((id: string) => {
    const container = scrollRef.current;
    if (!container) return;
    const el = container.querySelector(`[data-heading-id="${id}"]`) as HTMLElement | null;
    if (!el) return;

    const containerRect = container.getBoundingClientRect();
    const elRect = el.getBoundingClientRect();
    const headingTop = container.scrollTop + (elRect.top - containerRect.top);
    const centeredTop = headingTop - container.clientHeight / 2 + elRect.height / 2;
    const maxScrollTop = Math.max(0, container.scrollHeight - container.clientHeight);
    const targetTop = Math.max(0, Math.min(maxScrollTop, centeredTop));
    container.scrollTo({ top: targetTop, behavior: "smooth" });
    flashHeading(el);
  }, [flashHeading]);

  const openTocDrawer = useCallback(() => {
    setActiveDrawer((prev) => (prev === "toc" ? null : "toc"));
  }, []);

  const openCommentDrawer = useCallback(() => {
    setActiveDrawer((prev) => (prev === "comment" ? null : "comment"));
  }, []);

  const closeDrawer = useCallback(() => {
    setActiveDrawer(null);
  }, []);

  const handleTocItemClick = useCallback((id: string) => {
    scrollToHeading(id);
    if (isCompactPanels) {
      setActiveDrawer(null);
    }
  }, [isCompactPanels, scrollToHeading]);

  const dismissCommentComposer = useCallback(() => {
    setFloatingComment(null);
    setFloatingInput("");
  }, []);

  const computeCommentComposerTop = useCallback((selectionViewportTop: number) => {
    const panel = commentPanelRef.current;
    if (!panel) return 56;
    const panelRect = panel.getBoundingClientRect();
    const rawTop = selectionViewportTop - panelRect.top - 24;
    const minTop = 56;
    const estimatedComposerHeight = 208;
    const maxTop = Math.max(minTop, panelRect.height - estimatedComposerHeight - 12);
    return Math.min(maxTop, Math.max(minTop, rawTop));
  }, []);

  // Close floating toolbar when clicking outside
  useEffect(() => {
    if (!floatingToolbar) return;
    const handleClickOutside = (e: MouseEvent) => {
      if (floatingRef.current && !floatingRef.current.contains(e.target as Node)) {
        setFloatingToolbar(null);
        selectedRangeRef.current = null;
      }
    };
    document.addEventListener("mousedown", handleClickOutside);
    return () => document.removeEventListener("mousedown", handleClickOutside);
  }, [floatingToolbar]);

  // Keep user text selection highlighted after toolbar render.
  useEffect(() => {
    if (!floatingToolbar) return;
    const raf = window.requestAnimationFrame(() => {
      const range = selectedRangeRef.current;
      if (!range) return;
      const selection = window.getSelection();
      if (!selection || !selection.isCollapsed) return;
      try {
        selection.removeAllRanges();
        selection.addRange(range);
      } catch {
        selectedRangeRef.current = null;
      }
    });
    return () => window.cancelAnimationFrame(raf);
  }, [floatingToolbar]);

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
    dismissCommentComposer();
    setFloatingToolbar(null);
  }, [dismissCommentComposer, floatingInput, floatingComment]);

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

  const openCommentComposer = useCallback(() => {
    if (!floatingToolbar) return;
    if (isCompactPanels) {
      setActiveDrawer("comment");
    } else {
      setIsCommentCollapsed(false);
    }
    setFloatingComment({
      anchorId: floatingToolbar.anchorId,
      selectedText: floatingToolbar.selectedText,
      selectionViewportTop: floatingToolbar.selectionViewportTop,
      top: computeCommentComposerTop(floatingToolbar.selectionViewportTop),
    });
    setFloatingToolbar(null);
    setFloatingInput("");
  }, [computeCommentComposerTop, floatingToolbar, isCompactPanels]);

  // Feishu-style: detect text selection and show action toolbar near selection first
  const handleTextSelect = useCallback(() => {
    const sel = window.getSelection();
    if (!sel || sel.isCollapsed || !sel.toString().trim()) {
      setFloatingToolbar(null);
      selectedRangeRef.current = null;
      return;
    }

    const selectedText = sel.toString().trim();
    const range = sel.getRangeAt(0);
    const rect = range.getBoundingClientRect();
    const container = scrollRef.current;
    if (!container) return;
    const contentArea = contentAreaRef.current;
    if (contentArea && !contentArea.contains(range.commonAncestorContainer)) return;
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
      selectedRangeRef.current = range.cloneRange();
      const contentTop = rect.top - containerRect.top + container.scrollTop;
      const contentLeft = rect.left - containerRect.left + container.scrollLeft + rect.width / 2;
      const top = Math.max(container.scrollTop + 8, contentTop - 46);
      const left = Math.min(
        container.scrollLeft + container.clientWidth - 170,
        Math.max(container.scrollLeft + 170, contentLeft)
      );
      setFloatingToolbar({
        anchorId: headingId,
        selectedText: selectedText.slice(0, 60),
        top,
        left,
        selectionViewportTop: rect.top + rect.height / 2,
      });
      setFloatingComment(null);
      setFloatingInput("");
    }
  }, []);

  useEffect(() => {
    if (!floatingComment) return;
    const container = scrollRef.current;
    let rafId = 0;

    const updateTop = () => {
      window.cancelAnimationFrame(rafId);
      rafId = window.requestAnimationFrame(() => {
        setFloatingComment((prev) => {
          if (!prev) return null;
          let selectionViewportTop = prev.selectionViewportTop;
          const range = selectedRangeRef.current;
          if (range) {
            const rect = range.getBoundingClientRect();
            if (rect.width > 0 || rect.height > 0) {
              selectionViewportTop = rect.top + rect.height / 2;
            }
          }
          const nextTop = computeCommentComposerTop(selectionViewportTop);
          if (
            Math.abs(prev.top - nextTop) < 0.5 &&
            Math.abs(prev.selectionViewportTop - selectionViewportTop) < 0.5
          ) {
            return prev;
          }
          return {
            ...prev,
            selectionViewportTop,
            top: nextTop,
          };
        });
      });
    };

    updateTop();
    window.addEventListener("resize", updateTop);
    container?.addEventListener("scroll", updateTop, { passive: true });
    return () => {
      window.cancelAnimationFrame(rafId);
      window.removeEventListener("resize", updateTop);
      container?.removeEventListener("scroll", updateTop);
    };
  }, [computeCommentComposerTop, floatingComment?.anchorId, isCommentVisible]);

  const unresolvedComments = comments.filter((c) => !c.resolved);

  // Group comments by anchor for right-side threads
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
  const tocOrderMap = useMemo(
    () => new Map(toc.map((item, index) => [item.id, index])),
    [toc]
  );
  const tocTitleMap = useMemo(
    () => new Map(toc.map((item) => [item.id, item.text])),
    [toc]
  );
  const commentThreads = useMemo(
    () =>
      Array.from(commentsByAnchor.entries()).sort(
        ([anchorA], [anchorB]) =>
          (tocOrderMap.get(anchorA) ?? Number.MAX_SAFE_INTEGER) -
          (tocOrderMap.get(anchorB) ?? Number.MAX_SAFE_INTEGER)
      ),
    [commentsByAnchor, tocOrderMap]
  );
  const commentAnchorIds = useMemo(
    () => commentThreads.map(([anchorId]) => anchorId),
    [commentThreads]
  );
  const activeCommentIndex = useMemo(() => {
    if (commentAnchorIds.length === 0) return -1;
    if (!activeHeading) return 0;
    const directMatchIndex = commentAnchorIds.indexOf(activeHeading);
    if (directMatchIndex >= 0) return directMatchIndex;
    const activeOrder = tocOrderMap.get(activeHeading);
    if (activeOrder === undefined) return 0;
    let nearestIndex = 0;
    let nearestDistance = Number.MAX_SAFE_INTEGER;
    for (let i = 0; i < commentAnchorIds.length; i += 1) {
      const order = tocOrderMap.get(commentAnchorIds[i]);
      if (order === undefined) continue;
      const distance = Math.abs(order - activeOrder);
      if (distance < nearestDistance) {
        nearestDistance = distance;
        nearestIndex = i;
      }
    }
    return nearestIndex;
  }, [activeHeading, commentAnchorIds, tocOrderMap]);
  const activeCommentAnchorId = activeCommentIndex >= 0
    ? commentAnchorIds[activeCommentIndex]
    : null;
  const jumpCommentThread = useCallback((direction: -1 | 1) => {
    if (commentAnchorIds.length === 0) return;
    const baseIndex = activeCommentIndex < 0 ? 0 : activeCommentIndex;
    const nextIndex = Math.min(
      commentAnchorIds.length - 1,
      Math.max(0, baseIndex + direction)
    );
    scrollToHeading(commentAnchorIds[nextIndex]);
  }, [activeCommentIndex, commentAnchorIds, scrollToHeading]);
  const openAiAssistant = useCallback(() => {
    if (!subjectId) return;
    navigate(`/subject/${subjectId}/chat`);
  }, [navigate, subjectId]);

  const measureThreadHeights = useCallback(() => {
    const next: Record<string, number> = {};
    for (const [anchorId] of commentThreads) {
      const node = threadRefs.current.get(anchorId);
      if (node) {
        next[anchorId] = Math.ceil(node.getBoundingClientRect().height);
      }
    }
    setThreadHeights((prev) => (numberRecordEqual(prev, next) ? prev : next));
  }, [commentThreads]);

  const updateThreadTops = useCallback(() => {
    if (!isCommentVisible) {
      setThreadTops({});
      setThreadOpacity({});
      return;
    }
    const container = scrollRef.current;
    const viewport = commentViewportRef.current;
    if (!container || !viewport) return;
    const viewportRect = viewport.getBoundingClientRect();
    const maxBottom = viewportRect.height - COMMENT_THREAD_BOTTOM_PADDING;
    let cursorTop = -Infinity;
    const nextTops: Record<string, number> = {};
    const nextOpacity: Record<string, number> = {};

    for (const [anchorId] of commentThreads) {
      const anchor = container.querySelector(`[data-heading-id="${anchorId}"]`) as HTMLElement | null;
      if (!anchor) continue;
      const rect = anchor.getBoundingClientRect();
      const rawTop = rect.top - viewportRect.top;
      const threadHeight = threadHeights[anchorId] ?? COMMENT_THREAD_DEFAULT_HEIGHT;
      if (
        rawTop + threadHeight < -COMMENT_THREAD_HIDE_OFFSET ||
        rawTop > viewportRect.height + COMMENT_THREAD_HIDE_OFFSET
      ) {
        continue;
      }
      const maxTop = Math.max(COMMENT_THREAD_TOP_PADDING, maxBottom - threadHeight);
      const minVisibleTop = -threadHeight + 8;
      const stackedTop = Math.max(rawTop, cursorTop + COMMENT_THREAD_GAP);
      const top = Math.max(minVisibleTop, Math.min(maxTop, stackedTop));
      const topFade = top < COMMENT_THREAD_EDGE_FADE
        ? Math.max(0, top / COMMENT_THREAD_EDGE_FADE)
        : 1;
      const bottomDistance = viewportRect.height - (top + threadHeight);
      const bottomFade = bottomDistance < COMMENT_THREAD_EDGE_FADE
        ? Math.max(0, bottomDistance / COMMENT_THREAD_EDGE_FADE)
        : 1;
      const opacity = Math.min(1, Math.max(0, Math.min(topFade, bottomFade)));
      if (opacity <= 0.01) {
        continue;
      }
      nextTops[anchorId] = top;
      nextOpacity[anchorId] = opacity;
      cursorTop = top + threadHeight;
    }

    setThreadTops((prev) => (numberRecordEqual(prev, nextTops) ? prev : nextTops));
    setThreadOpacity((prev) => (numberRecordEqual(prev, nextOpacity) ? prev : nextOpacity));
  }, [commentThreads, isCommentVisible, threadHeights]);

  useEffect(() => {
    if (!isCommentVisible) return;
    const rafId = window.requestAnimationFrame(measureThreadHeights);
    return () => window.cancelAnimationFrame(rafId);
  }, [commentThreads, floatingComment, measureThreadHeights, menuOpenId, isCommentVisible]);

  useEffect(() => {
    if (!isCommentVisible) return;
    const container = scrollRef.current;
    if (!container) return;
    let rafId = 0;
    const syncPositions = () => {
      window.cancelAnimationFrame(rafId);
      rafId = window.requestAnimationFrame(() => {
        updateThreadTops();
      });
    };
    syncPositions();
    container.addEventListener("scroll", syncPositions, { passive: true });
    window.addEventListener("resize", syncPositions);
    return () => {
      window.cancelAnimationFrame(rafId);
      container.removeEventListener("scroll", syncPositions);
      window.removeEventListener("resize", syncPositions);
    };
  }, [isCommentVisible, updateThreadTops]);

  const closeCommentPanel = useCallback(() => {
    if (isCompactPanels) {
      closeDrawer();
    } else {
      setIsCommentCollapsed(true);
    }
  }, [closeDrawer, isCompactPanels]);

  const tocNav = (
    <nav className="toc-scroll flex-1 overflow-y-auto py-2 pr-2">
      {toc.map((item) => {
        const count = commentsForAnchor(item.id);
        return (
          <button
            key={item.id}
            onClick={() => handleTocItemClick(item.id)}
            className={cn(
              "group w-full text-left px-2 py-1.5 rounded-md text-[13px] transition-all duration-150 flex items-center gap-1",
              item.level === 1 && "font-semibold text-slate-900 mt-2 first:mt-0",
              item.level === 2 && "pl-4 text-slate-700",
              item.level === 3 && "pl-7 text-slate-500",
              item.level >= 4 && "pl-9 text-slate-400",
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
  );

  const commentPanel = (
    <div
      ref={commentPanelRef}
      className={cn(
        "relative w-full flex flex-col overflow-hidden",
        isCompactPanels
          ? "h-full rounded-2xl border border-slate-200 bg-white shadow-2xl"
          : "border-l border-slate-200/90 pl-3 bg-transparent"
      )}
    >
      <div className="px-1 h-11 border-b border-slate-200/80 flex items-center justify-between">
        <div className="flex items-center gap-2 text-slate-900">
          <MessageSquarePlus className="w-4 h-4" />
          <span className="text-sm font-semibold">评论</span>
        </div>
        <div className="flex items-center gap-1.5">
          <span className="text-xs text-slate-500">{unresolvedComments.length} 条待处理</span>
          <button
            onClick={() => jumpCommentThread(-1)}
            disabled={activeCommentIndex <= 0}
            className={cn(
              "w-7 h-7 rounded-lg transition-colors flex items-center justify-center",
              activeCommentIndex <= 0
                ? "text-slate-300 cursor-not-allowed"
                : "text-slate-500 hover:text-slate-700 hover:bg-slate-100"
            )}
            aria-label="定位上一条评论"
            title="定位上一条评论"
          >
            <ChevronUp className="w-4 h-4" />
          </button>
          <button
            onClick={() => jumpCommentThread(1)}
            disabled={activeCommentIndex < 0 || activeCommentIndex >= commentAnchorIds.length - 1}
            className={cn(
              "w-7 h-7 rounded-lg transition-colors flex items-center justify-center",
              activeCommentIndex < 0 || activeCommentIndex >= commentAnchorIds.length - 1
                ? "text-slate-300 cursor-not-allowed"
                : "text-slate-500 hover:text-slate-700 hover:bg-slate-100"
            )}
            aria-label="定位下一条评论"
            title="定位下一条评论"
          >
            <ChevronDown className="w-4 h-4" />
          </button>
          <button
            onClick={closeCommentPanel}
            className="w-7 h-7 rounded-lg hover:bg-slate-100 transition-colors flex items-center justify-center text-slate-500 hover:text-slate-700"
            aria-label="收起评论栏"
          >
            <ChevronRight className={cn("w-4 h-4", isCompactPanels && "rotate-180")} />
          </button>
        </div>
      </div>

      {floatingComment && (
        <div
          className="absolute left-3 right-3 z-30 rounded-xl border border-slate-200 bg-white shadow-lg"
          style={{ top: floatingComment.top }}
        >
          <div className="px-3 py-2 border-b border-slate-100 bg-slate-50/80 rounded-t-xl">
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
                  dismissCommentComposer();
                }
              }}
              placeholder="添加评论..."
              rows={3}
              className="w-full text-sm border border-slate-200 rounded-lg px-3 py-2 focus:outline-none focus:ring-2 focus:ring-blue-200 focus:border-blue-300 resize-none"
              autoFocus
            />
            <div className="flex items-center justify-between mt-2">
              <button
                onClick={dismissCommentComposer}
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

      <div ref={commentViewportRef} className="relative flex-1 overflow-hidden">
        <div className="pointer-events-none absolute inset-x-0 top-0 h-12 z-20 bg-gradient-to-b from-slate-50 via-slate-50/80 to-transparent" />
        <div className="pointer-events-none absolute inset-x-0 bottom-0 h-12 z-20 bg-gradient-to-t from-slate-50 via-slate-50/80 to-transparent" />
        {commentThreads.length === 0 ? (
          <div className="h-full p-3">
            <div className="rounded-xl border border-dashed border-slate-200 bg-slate-50 px-4 py-6 text-center">
              <p className="text-sm text-slate-500">选中文本后点击“评论”即可创建讨论</p>
            </div>
          </div>
        ) : (
          <div className="relative h-full">
            {commentThreads.map(([anchorId, anchorComments]) => {
              const top = threadTops[anchorId];
              const opacity = threadOpacity[anchorId] ?? 0;
              if (top === undefined || opacity <= 0) {
                return null;
              }
              return (
                <div
                  key={anchorId}
                  ref={(node: HTMLDivElement | null) => {
                    if (node) {
                      threadRefs.current.set(anchorId, node);
                    } else {
                      threadRefs.current.delete(anchorId);
                    }
                  }}
                  className="absolute left-1 right-2 transition-[top,opacity] duration-150"
                  style={{ top, opacity }}
                >
                  <CommentThread
                    anchorId={anchorId}
                    title={tocTitleMap.get(anchorId) ?? anchorId}
                    comments={anchorComments}
                    isActive={activeCommentAnchorId === anchorId}
                    menuOpenId={menuOpenId}
                    setMenuOpenId={setMenuOpenId}
                    onResolve={resolveComment}
                    onDelete={deleteComment}
                    onJumpToAnchor={scrollToHeading}
                  />
                </div>
              );
            })}
          </div>
        )}
      </div>
    </div>
  );

  return (
    <div className="relative h-screen overflow-hidden bg-slate-50">
      <div className="fixed top-3 right-4 z-[70]">
        <TopBar />
      </div>

      {!isCompactPanels && (
        <div className="hidden lg:block absolute left-4 top-16 z-30">
          {isTocCollapsed ? (
            <aside className="w-11 h-11">
              <button
                onClick={() => setIsTocCollapsed(false)}
                className="w-11 h-11 rounded-xl border border-slate-200/80 bg-slate-50/95 backdrop-blur-sm shadow-sm text-slate-600 hover:text-slate-900 hover:bg-white transition-colors flex items-center justify-center"
                aria-label="展开目录"
                title={activeTocItem?.text ? `展开目录（当前：${activeTocItem.text}）` : "展开目录"}
              >
                <FileText className="w-4 h-4" />
                <ChevronRight className="w-3.5 h-3.5 -ml-0.5" />
              </button>
            </aside>
          ) : (
            <aside className="w-64 h-[calc(100vh-7rem)] max-h-[780px] flex flex-col overflow-hidden">
              <div className="px-2 h-10 flex items-center justify-between">
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
              {tocNav}
            </aside>
          )}
        </div>
      )}

      {isCompactPanels && (
        <>
          <div className="fixed top-3 left-16 lg:left-[17rem] z-[79] flex items-center gap-2">
            <button
              onClick={openTocDrawer}
              className={cn(
                "h-10 w-10 rounded-xl border border-slate-200 bg-white/95 backdrop-blur-sm shadow-sm transition-colors flex items-center justify-center",
                isTocVisible ? "text-blue-600 bg-blue-50" : "text-slate-600 hover:text-slate-900 hover:bg-white"
              )}
              aria-label="切换目录抽屉"
              title={activeTocItem?.text ? `目录（当前：${activeTocItem.text}）` : "目录"}
            >
              <FileText className="w-4 h-4" />
            </button>
            <button
              onClick={openCommentDrawer}
              className={cn(
                "h-10 w-10 rounded-xl border border-slate-200 bg-white/95 backdrop-blur-sm shadow-sm transition-colors flex items-center justify-center relative",
                isCommentVisible ? "text-blue-600 bg-blue-50" : "text-slate-600 hover:text-slate-900 hover:bg-white"
              )}
              aria-label="切换评论抽屉"
              title="评论"
            >
              <MessageSquarePlus className="w-4 h-4" />
              {unresolvedComments.length > 0 && (
                <span className="absolute -top-1 -right-1 min-w-4 h-4 px-1 rounded-full bg-blue-500 text-white text-[10px] leading-4 text-center">
                  {Math.min(unresolvedComments.length, 99)}
                </span>
              )}
            </button>
          </div>

          {activeDrawer && (
            <button
              onClick={closeDrawer}
              className="fixed inset-0 z-[76] bg-slate-900/25 backdrop-blur-[1px]"
              aria-label="关闭抽屉遮罩"
            />
          )}

          <aside
            className={cn(
              "fixed left-3 top-14 bottom-4 z-[78] w-[min(20rem,calc(100vw-1.5rem))] rounded-2xl border border-slate-200 bg-white/98 shadow-2xl flex flex-col overflow-hidden transition-transform duration-200",
              isTocVisible ? "translate-x-0" : "-translate-x-[110%] pointer-events-none"
            )}
          >
            <div className="px-3 h-11 border-b border-slate-200/80 flex items-center justify-between">
              <div className="flex items-center gap-2 text-slate-900">
                <FileText className="w-4 h-4" />
                <span className="text-sm font-semibold">目录</span>
              </div>
              <button
                onClick={closeDrawer}
                className="w-7 h-7 rounded-lg hover:bg-slate-100 transition-colors flex items-center justify-center text-slate-500 hover:text-slate-700"
                aria-label="收起目录"
              >
                <ChevronRight className="w-4 h-4" />
              </button>
            </div>
            <div className="px-1 pb-2 flex-1 overflow-hidden">{tocNav}</div>
          </aside>
        </>
      )}

      <div className="hidden lg:block absolute bottom-6 right-4 z-30">
        <button
          onClick={openAiAssistant}
          className="h-11 rounded-2xl border border-slate-200 bg-white/95 backdrop-blur-sm shadow-lg px-4 text-slate-700 hover:text-slate-900 hover:bg-white transition-colors inline-flex items-center gap-2"
          aria-label="AI 助手"
          title="AI 助手"
        >
          <Bot className="w-4 h-4" />
          <span className="text-xs font-semibold tracking-wide uppercase">AI</span>
        </button>
      </div>

      {!isCompactPanels && (
        <>
          {isCommentCollapsed ? (
            <aside className="hidden lg:flex absolute right-4 top-16 z-20">
              <button
                onClick={() => setIsCommentCollapsed(false)}
                className="rounded-xl border border-slate-200 bg-white/95 backdrop-blur-sm shadow-sm px-2 py-2.5 text-slate-600 hover:text-slate-900 hover:bg-white transition-colors flex items-center gap-1"
                aria-label="展开评论栏"
              >
                <MessageSquarePlus className="w-4 h-4" />
                <ChevronRight className="w-4 h-4 rotate-180" />
              </button>
            </aside>
          ) : (
            <aside className="hidden lg:flex absolute right-4 top-16 bottom-5 w-80 z-20">
              {commentPanel}
            </aside>
          )}
        </>
      )}

      {isCompactPanels && (
        <aside
          className={cn(
            "fixed right-3 top-14 bottom-4 z-[78] w-[min(24rem,calc(100vw-1.5rem))] transition-transform duration-200",
            isCommentVisible ? "translate-x-0" : "translate-x-[110%] pointer-events-none"
          )}
        >
          {commentPanel}
        </aside>
      )}

      <div
        ref={scrollRef}
        className="h-full overflow-y-auto relative"
        onMouseUp={handleTextSelect}
      >
        <div
          className={cn(
            "min-h-full pr-4 transition-[padding-left,padding-right] duration-300 pl-4 md:pl-6",
            isCompactPanels
              ? "lg:pr-6 lg:pl-6"
              : isCommentCollapsed
                ? "lg:pr-20"
                : "lg:pr-[22rem]",
            isCompactPanels
              ? null
              : isTocCollapsed
                ? "lg:pl-20"
                : "lg:pl-[18.5rem]"
          )}
        >
          <div className="mx-auto max-w-[1800px] px-6 py-8">
            <div
              ref={contentAreaRef}
              className="mx-auto flex min-h-full w-full max-w-[1380px]"
              >
                <article
                  className="min-w-0 flex-1 px-6 py-8 md:px-10 md:py-10"
                >
                  <DocMarkdown content={markdown} />
                </article>
            </div>
          </div>

          {floatingToolbar && (
            <div
              ref={floatingRef}
              className="absolute z-50 -translate-x-1/2"
              style={{
                top: floatingToolbar.top,
                left: floatingToolbar.left,
              }}
              onMouseUp={(e) => e.stopPropagation()}
            >
              <div className="inline-flex items-center gap-2 rounded-lg border border-slate-200 bg-white px-2 py-1 shadow-lg">
                <span className="max-w-36 truncate text-[11px] text-slate-400">
                  &ldquo;{floatingToolbar.selectedText}&rdquo;
                </span>
                <button
                  onMouseDown={(e) => e.preventDefault()}
                  onClick={openCommentComposer}
                  className="inline-flex items-center gap-1 rounded-md px-2 py-1 text-xs font-medium text-slate-700 hover:bg-slate-100"
                >
                  <MessageSquarePlus className="w-3.5 h-3.5" />
                  评论
                </button>
              </div>
            </div>
          )}

        </div>
      </div>
    </div>
  );
}
