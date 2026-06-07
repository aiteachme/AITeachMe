import { MarkdownViewer } from "../ui/MarkdownViewer";

interface KnowledgeDocViewerProps {
  content: string;
}

export function KnowledgeDocViewer({ content }: KnowledgeDocViewerProps) {
  return (
    <div className="gemini-document-viewer feishu-doc-content mx-auto w-full max-w-[900px] px-5 pb-32 pt-8 sm:px-8 lg:px-10">
      <article className="bg-white px-0 py-2 dark:bg-slate-950/80">
        <MarkdownViewer content={content} variant="document" headingAnchors />
      </article>
    </div>
  );
}
