import { useEffect, useRef } from "react";
import { useQuery } from "@tanstack/react-query";
import { Loader2, FileText, MapPin } from "lucide-react";
import { fetchEvidenceContext } from "../../api/graphApi";
import { Modal } from "../ui/Modal";
import { MarkdownViewer } from "../ui/MarkdownViewer";

/**
 * 证据原文上下文弹窗：显示 chunk 的完整 markdown，
 * 并高亮引用段落，自动滚动到高亮位置。
 */
export function EvidenceContextModal({
  open,
  onClose,
  subject,
  evidenceId,
}: {
  open: boolean;
  onClose: () => void;
  subject: string;
  evidenceId: number | null;
}) {
  const highlightRef = useRef<HTMLDivElement>(null);

  const { data, isLoading, isError } = useQuery({
    queryKey: ["evidence-context", subject, evidenceId],
    queryFn: () => fetchEvidenceContext(subject, evidenceId!),
    enabled: open && !!evidenceId,
  });

  // 自动滚动到高亮位置
  useEffect(() => {
    if (data && highlightRef.current) {
      const timer = setTimeout(() => {
        highlightRef.current?.scrollIntoView({ behavior: "smooth", block: "center" });
      }, 150);
      return () => clearTimeout(timer);
    }
  }, [data]);

  // 将 chunk_content 拆分为：高亮前 / 高亮部分 / 高亮后
  const renderContent = () => {
    if (!data) return null;

    const { chunk_content, highlight_start, highlight_end, quote_text } = data;

    // 如果有高亮位置，拆分内容
    if (highlight_start !== null && highlight_end !== null && highlight_start < highlight_end) {
      const before = chunk_content.slice(0, highlight_start);
      const highlighted = chunk_content.slice(highlight_start, highlight_end);
      const after = chunk_content.slice(highlight_end);

      return (
        <div className="text-sm leading-relaxed">
          {before && (
            <div className="mb-2 opacity-70">
              <MarkdownViewer content={before} />
            </div>
          )}
          <div
            ref={highlightRef}
            className="bg-amber-50 border-l-4 border-amber-400 px-4 py-3 rounded-r-lg my-3 relative"
          >
            <div className="absolute -left-0.5 top-2 w-5 h-5 bg-amber-400 rounded-full flex items-center justify-center">
              <MapPin className="w-3 h-3 text-white" />
            </div>
            <MarkdownViewer content={highlighted} />
          </div>
          {after && (
            <div className="mt-2 opacity-70">
              <MarkdownViewer content={after} />
            </div>
          )}
        </div>
      );
    }

    // 没有精确位置，尝试文本匹配高亮
    if (quote_text && chunk_content.includes(quote_text)) {
      const idx = chunk_content.indexOf(quote_text);
      const before = chunk_content.slice(0, idx);
      const after = chunk_content.slice(idx + quote_text.length);

      return (
        <div className="text-sm leading-relaxed">
          {before && (
            <div className="mb-2 opacity-70">
              <MarkdownViewer content={before} />
            </div>
          )}
          <div
            ref={highlightRef}
            className="bg-amber-50 border-l-4 border-amber-400 px-4 py-3 rounded-r-lg my-3 relative"
          >
            <div className="absolute -left-0.5 top-2 w-5 h-5 bg-amber-400 rounded-full flex items-center justify-center">
              <MapPin className="w-3 h-3 text-white" />
            </div>
            <MarkdownViewer content={quote_text} />
          </div>
          {after && (
            <div className="mt-2 opacity-70">
              <MarkdownViewer content={after} />
            </div>
          )}
        </div>
      );
    }

    // 无法定位，直接渲染全部内容
    return (
      <div className="text-sm leading-relaxed">
        <MarkdownViewer content={chunk_content} />
      </div>
    );
  };

  const title = data
    ? `${data.document_title} › ${data.chunk_header_path || data.chunk_title}`
    : "加载证据上下文...";

  return (
    <Modal open={open} onClose={onClose} title={title}>
      <div className="space-y-3">
        {isLoading && (
          <div className="flex items-center justify-center py-8 text-slate-400">
            <Loader2 className="w-5 h-5 animate-spin mr-2" />加载原文...
          </div>
        )}

        {isError && (
          <div className="text-sm text-red-500 py-4 text-center">
            加载失败，该证据对应的原文可能已被删除
          </div>
        )}

        {data && (
          <>
            {/* 面包屑路径 */}
            <div className="flex items-center gap-2 text-xs text-slate-400 pb-2 border-b border-slate-100">
              <FileText className="w-3.5 h-3.5" />
              <span>{data.document_title}</span>
              <span>›</span>
              <span className="text-slate-600">{data.chunk_header_path || data.chunk_title}</span>
            </div>

            {/* 原文内容 */}
            <div className="max-h-[60vh] overflow-y-auto pr-1">
              {renderContent()}
            </div>
          </>
        )}
      </div>
    </Modal>
  );
}
