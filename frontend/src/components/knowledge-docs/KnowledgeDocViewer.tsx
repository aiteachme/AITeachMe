import { MarkdownViewer } from "../ui/MarkdownViewer";

interface KnowledgeDocViewerProps {
  content: string;
}

export function KnowledgeDocViewer({ content }: KnowledgeDocViewerProps) {
  return (
    <div className="gemini-document-viewer mx-auto w-full max-w-[860px] px-8 pb-32 pt-8">
      <div className="rounded-[28px] border border-slate-200/80 bg-white/90 p-8 shadow-[0_28px_60px_-48px_rgba(15,23,42,0.25)] dark:border-slate-800 dark:bg-slate-950/80 dark:shadow-[0_28px_60px_-48px_rgba(0,0,0,0.72)]">
        <MarkdownViewer content={content} variant="document" headingAnchors />
      </div>
    </div>
  );
}
