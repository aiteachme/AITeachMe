/**
 * 资料库 Markdown 渲染组件。
 *
 * 专门处理 ingest 解析后的 Markdown：
 * - 原始 HTML 标签（<div>, <img>, <table> 等）
 * - LaTeX 数学公式，包括 HTML 标签内嵌的公式
 * - 图片路径自动拼接 assetBaseUrl
 */

import { useMemo } from "react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import remarkMath from "remark-math";
import rehypeKatex from "rehype-katex";
import rehypeRaw from "rehype-raw";
import type { Components } from "react-markdown";
import { rehypeMarkdownSanitize } from "../../lib/markdownSanitize";
import { preprocessMarkdownForRender } from "../ui/MarkdownViewer";

interface LibraryMarkdownViewerProps {
  content: string;
  assetBaseUrl?: string;
}

function resolveAssetSrc(src: string | undefined, assetBaseUrl: string): string {
  if (!src) return "";
  if (src.startsWith("http") || src.startsWith("/") || src.startsWith("data:")) {
    return src;
  }
  const filename = src.replace(/^.*[\\/]/, "");
  return `${assetBaseUrl.replace(/\/$/, "")}/${encodeURIComponent(filename)}`;
}

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

export function LibraryMarkdownViewer({ content, assetBaseUrl }: LibraryMarkdownViewerProps) {
  const processedContent = useMemo(() => preprocessMarkdownForRender(content), [content]);

  const components: Components = {};

  if (assetBaseUrl) {
    components.img = ({ src, alt, ...props }) => (
      <img
        src={resolveAssetSrc(src ?? undefined, assetBaseUrl)}
        alt={alt ?? ""}
        className="my-4 max-h-[32rem] w-full rounded-lg object-contain"
        loading="lazy"
        {...props}
      />
    );
  }

  const rehypePlugins = useMemo(() => {
    const plugins = [
      rehypeRaw,
      rehypeExtractInlineMath,
      rehypeMarkdownSanitize,
      rehypeKatex,
      ...(assetBaseUrl ? [rehypeRewriteAssetUrls(assetBaseUrl)] : []),
    ];

    return plugins;
  }, [assetBaseUrl]);

  return (
    <div className="prose prose-slate max-w-none dark:prose-invert">
      <ReactMarkdown
        remarkPlugins={[remarkGfm, remarkMath]}
        rehypePlugins={rehypePlugins}
        components={components}
      >
        {processedContent}
      </ReactMarkdown>
    </div>
  );
}

function rehypeRewriteAssetUrls(assetBaseUrl: string) {
  return () => (tree: any) => {
    visit(tree, (node: any) => {
      if (node.tagName === "img" && node.properties?.src) {
        const src = node.properties.src;
        if (!src.startsWith("http") && !src.startsWith("/") && !src.startsWith("data:")) {
          node.properties.src = resolveAssetSrc(src, assetBaseUrl);
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
