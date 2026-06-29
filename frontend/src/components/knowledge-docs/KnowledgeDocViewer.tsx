import { MarkdownViewer } from "../ui/MarkdownViewer";

interface KnowledgeDocViewerProps {
  content: string;
  embedded?: boolean;
}

export function KnowledgeDocViewer({ content, embedded = false }: KnowledgeDocViewerProps) {
  return (
    <div
      className={
        embedded
          ? "gemini-document-viewer feishu-doc-content min-w-0 w-full pb-32"
          : "gemini-document-viewer feishu-doc-content mx-auto w-full max-w-[860px] px-5 pb-32 pt-8 sm:px-8 lg:px-10"
      }
    >
      <article className={embedded ? "bg-white px-0 py-0 dark:bg-slate-950/80" : "bg-white px-0 py-2 dark:bg-slate-950/80"}>
        <MarkdownViewer content={content} variant="document" headingAnchors />
      </article>
    </div>
  );
}
