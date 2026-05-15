import { MarkdownViewer } from "../ui/MarkdownViewer";

interface KnowledgeDocViewerProps {
  content: string;
}

export function KnowledgeDocViewer({ content }: KnowledgeDocViewerProps) {
  return (
    <div className="gemini-document-viewer mx-auto w-full max-w-[860px] px-8 pb-32 pt-8">
      <div className="rounded-2xl border border-slate-200/80 bg-white p-8 dark:border-slate-800 dark:bg-slate-950/80">
        <MarkdownViewer content={content} variant="document" headingAnchors />
      </div>
    </div>
  );
}
