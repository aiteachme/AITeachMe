/**
 * 资料库 Markdown 渲染组件。
 *
 * 专门处理 ingest 解析后的 Markdown：
 * - 原始 HTML 标签（<div>, <img>, <table> 等）
 * - LaTeX 数学公式，包括 HTML 标签内嵌的公式
 * - 图片路径自动拼接 assetBaseUrl
 */

import {
  memo,
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
  type ComponentPropsWithoutRef,
} from "react";
import ReactMarkdown from "react-markdown";
import { AlertCircle, RefreshCw } from "lucide-react";
import remarkGfm from "remark-gfm";
import remarkMath from "remark-math";
import rehypeKatex from "rehype-katex";
import rehypeRaw from "rehype-raw";
import type { Components } from "react-markdown";
import { rehypeMarkdownSanitize } from "../../lib/markdownSanitize";
import { preprocessMarkdownForRender } from "../ui/MarkdownViewer";
import {
  escapeMathHtmlCharactersForRender,
  resolveLibraryAssetSrc,
  splitLibraryMarkdownForRender,
} from "./libraryMarkdown";

interface LibraryMarkdownViewerProps {
  content: string;
  assetBaseUrl?: string;
  hasMore?: boolean;
  isFetchingMore?: boolean;
  loadMoreError?: string | null;
  onRequestMore?: () => void;
  onRetryMore?: () => void;
  onRenderProgressChange?: (renderedChars: number, complete: boolean) => void;
}

const INITIAL_VISIBLE_CHUNKS = 2;
const CHUNKS_PER_REVEAL = 2;

/**
 * rehype 插件：rehype-raw 解析 HTML 后，把文本节点中的 $...$ 转成
 * rehype-katex 能识别的 math/inlineMath 节点。
 */
function rehypeExtractInlineMath() {
  const DISPLAY_RE = /\$\$([\s\S]+?)\$\$/g;
  const INLINE_RE = /(?<!\$)\$(?!\$)((?:\\[\s\S]|[^$])+?)\$(?!\$)/g;

  return (tree: any) => {
    visit(tree, (node: any) => {
      if (!node.children) return;
      const newChildren: any[] = [];
      let changed = false;

      for (const child of node.children) {
        if (child.type !== "text" || typeof child.value !== "string" || !child.value.includes("$")) {
          newChildren.push(child);
          continue;
        }

        const parts = splitMathParts(child.value);
        if (parts.length === 1 && parts[0].type === "text") {
          newChildren.push(child);
          continue;
        }

        changed = true;
        for (const part of parts) {
          if (part.type === "text") {
            newChildren.push({ type: "text", value: part.value });
          } else if (part.type === "displayMath") {
            newChildren.push({ type: "math", value: part.value, meta: true });
          } else if (part.type === "inlineMath") {
            newChildren.push({ type: "inlineMath", value: part.value });
          }
        }
      }

      if (changed) node.children = newChildren;
    });
  };

  function splitMathParts(text: string): Array<{ type: string; value: string }> {
    const parts: Array<{ type: string; value: string }> = [];
    let lastIdx = 0;

    DISPLAY_RE.lastIndex = 0;
    let m: RegExpExecArray | null;
    while ((m = DISPLAY_RE.exec(text)) !== null) {
      if (m.index > lastIdx) parts.push({ type: "text", value: text.slice(lastIdx, m.index) });
      parts.push({ type: "displayMath", value: m[1] });
      lastIdx = m.index + m[0].length;
    }

    const remainder = text.slice(lastIdx);
    INLINE_RE.lastIndex = 0;
    lastIdx = 0;
    while ((m = INLINE_RE.exec(remainder)) !== null) {
      if (m.index > lastIdx) parts.push({ type: "text", value: remainder.slice(lastIdx, m.index) });
      parts.push({ type: "inlineMath", value: m[1] });
      lastIdx = m.index + m[0].length;
    }
    if (lastIdx < remainder.length) parts.push({ type: "text", value: remainder.slice(lastIdx) });

    if (parts.length === 0) parts.push({ type: "text", value: text });
    return parts;
  }
}

type MarkdownAstNode = {
  type?: string;
  value?: string;
  children?: MarkdownAstNode[];
};

/** 与 MinerU 的 line_breaks=True 对齐，只转换普通段落里的软换行。 */
function remarkLibrarySoftBreaks() {
  const splitTextNode = (node: MarkdownAstNode): MarkdownAstNode[] => {
    const value = String(node.value ?? "");
    if (!value.includes("\n")) return [node];

    return value.split("\n").flatMap((part, index) => [
      ...(index > 0 ? [{ type: "break" }] : []),
      ...(part ? [{ ...node, value: part }] : []),
    ]);
  };

  return (tree: MarkdownAstNode) => {
    const visitNode = (node: MarkdownAstNode) => {
      if (!Array.isArray(node.children)) return;
      if (node.type === "paragraph") {
        node.children = node.children.flatMap((child) => (
          child.type === "text" ? splitTextNode(child) : [child]
        ));
        return;
      }
      node.children.forEach((child) => {
        if (child.type !== "math" && child.type !== "inlineMath") visitNode(child);
      });
    };
    visitNode(tree);
  };
}

interface LibraryMarkdownChunkProps {
  content: string;
  components: Components;
  rehypePlugins: any[];
}

const LibraryMarkdownChunk = memo(function LibraryMarkdownChunk({
  content,
  components,
  rehypePlugins,
}: LibraryMarkdownChunkProps) {
  const processedContent = useMemo(
    () => escapeMathHtmlCharactersForRender(preprocessMarkdownForRender(content)),
    [content],
  );

  return (
    <div className="library-markdown-chunk">
      <ReactMarkdown
        remarkPlugins={[remarkGfm, remarkMath, remarkLibrarySoftBreaks]}
        rehypePlugins={rehypePlugins}
        components={components}
      >
        {processedContent}
      </ReactMarkdown>
    </div>
  );
});

export function LibraryMarkdownViewer({
  content,
  assetBaseUrl,
  hasMore = false,
  isFetchingMore = false,
  loadMoreError = null,
  onRequestMore,
  onRetryMore,
  onRenderProgressChange,
}: LibraryMarkdownViewerProps) {
  const chunks = useMemo(() => splitLibraryMarkdownForRender(content), [content]);
  const [visibleChunkCount, setVisibleChunkCount] = useState(INITIAL_VISIBLE_CHUNKS);
  const loadSentinelRef = useRef<HTMLDivElement>(null);

  const components = useMemo<Components>(() => {
    const next: Components = {
      table: ({ children }: ComponentPropsWithoutRef<"table">) => (
        <div className="library-markdown-table-shell">
          <table>{children}</table>
        </div>
      ),
    };

    if (assetBaseUrl) {
      next.img = ({ src, alt, title, width, height }: ComponentPropsWithoutRef<"img">) => {
        const resolvedSrc = resolveLibraryAssetSrc(src ?? undefined, assetBaseUrl);
        if (!resolvedSrc) return null;
        return (
          <span className="library-markdown-figure">
            <img
              src={resolvedSrc}
              alt={alt ?? ""}
              title={title}
              width={width}
              height={height}
              loading="lazy"
              decoding="async"
            />
            {alt ? <span className="library-markdown-figure__caption">{alt}</span> : null}
          </span>
        );
      };
    }
    return next;
  }, [assetBaseUrl]);

  const rehypePlugins = useMemo(() => {
    const plugins = [
      rehypeRaw,
      rehypeExtractInlineMath,
      rehypeMarkdownSanitize,
      [rehypeKatex, { throwOnError: false, strict: false, trust: false, errorColor: "#c2410c" }],
      ...(assetBaseUrl ? [rehypeRewriteAssetUrls(assetBaseUrl)] : []),
    ] as any[];

    return plugins;
  }, [assetBaseUrl]);

  const revealMore = useCallback(() => {
    if (visibleChunkCount < chunks.length) {
      setVisibleChunkCount((current) => Math.min(current + CHUNKS_PER_REVEAL, chunks.length));
      return;
    }
    if (hasMore && !isFetchingMore && !loadMoreError) {
      onRequestMore?.();
    }
  }, [chunks.length, hasMore, isFetchingMore, loadMoreError, onRequestMore, visibleChunkCount]);

  useEffect(() => {
    const sentinel = loadSentinelRef.current;
    if (!sentinel || typeof IntersectionObserver === "undefined") return;
    const observer = new IntersectionObserver((entries) => {
      if (entries.some((entry) => entry.isIntersecting)) revealMore();
    }, { rootMargin: "900px 0px" });
    observer.observe(sentinel);
    return () => observer.disconnect();
  }, [revealMore]);

  const renderComplete = visibleChunkCount >= chunks.length && !hasMore;
  const visibleChunks = useMemo(
    () => chunks.slice(0, visibleChunkCount),
    [chunks, visibleChunkCount],
  );
  const renderedChars = useMemo(
    () => visibleChunks.reduce((total, chunk) => total + chunk.length, 0),
    [visibleChunks],
  );
  useEffect(() => {
    onRenderProgressChange?.(renderedChars, renderComplete);
  }, [onRenderProgressChange, renderComplete, renderedChars]);

  return (
    <div className="library-markdown prose prose-slate max-w-none break-words dark:prose-invert">
      {visibleChunks.map((chunk, index) => (
        <LibraryMarkdownChunk
          key={index}
          content={chunk}
          components={components}
          rehypePlugins={rehypePlugins}
        />
      ))}
      {loadMoreError && visibleChunkCount >= chunks.length ? (
        <div
          className="library-markdown-progress not-prose flex-wrap text-red-600 dark:text-red-300"
          role="alert"
        >
          <span className="inline-flex items-center gap-2">
            <AlertCircle className="h-4 w-4 shrink-0" aria-hidden="true" />
            <span>{loadMoreError}</span>
          </span>
          <button
            type="button"
            onClick={onRetryMore}
            disabled={isFetchingMore}
            className="inline-flex h-8 items-center gap-1.5 rounded-md border border-red-200 bg-white px-3 text-xs font-medium text-red-700 transition hover:bg-red-50 disabled:cursor-not-allowed disabled:opacity-60 dark:border-red-900 dark:bg-slate-900 dark:text-red-200 dark:hover:bg-red-950/30"
          >
            <RefreshCw className={isFetchingMore ? "h-3.5 w-3.5 animate-spin" : "h-3.5 w-3.5"} />
            重试
          </button>
        </div>
      ) : visibleChunkCount < chunks.length || hasMore || isFetchingMore ? (
        <div ref={loadSentinelRef} className="library-markdown-progress not-prose" aria-live="polite">
          <span className="library-markdown-progress__spinner" aria-hidden="true" />
          <span>{isFetchingMore ? "正在读取后续内容…" : "继续向下滚动以加载后续内容"}</span>
        </div>
      ) : null}
    </div>
  );
}

function rehypeRewriteAssetUrls(assetBaseUrl: string) {
  return () => (tree: any) => {
    visit(tree, (node: any) => {
      if (node.tagName === "img" && node.properties?.src) {
        const src = node.properties.src;
        if (!src.startsWith("http") && !src.startsWith("/") && !src.startsWith("data:")) {
          node.properties.src = resolveLibraryAssetSrc(src, assetBaseUrl);
        }
      }
    });
  };
}

function visit(node: any, handler: (node: any) => void | boolean) {
  if (!node) return;
  const shouldVisitChildren = handler(node);
  if (shouldVisitChildren === false) return;
  if (Array.isArray(node.children)) {
    node.children.forEach((child: any) => visit(child, handler));
  }
}
