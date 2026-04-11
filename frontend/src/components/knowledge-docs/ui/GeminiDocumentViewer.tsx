import { MarkdownViewer } from "../../ui/MarkdownViewer";

interface GeminiDocumentViewerProps {
  content: string;
}

export function GeminiDocumentViewer({ content }: GeminiDocumentViewerProps) {
  return (
    <div className="mx-auto w-full max-w-[800px] px-8 pt-4 pb-32">
      <div className="prose prose-slate prose-lg md:prose-xl font-sans max-w-none 
        [&>h1:first-child]:hidden
        prose-headings:font-bold prose-headings:tracking-tight prose-headings:text-slate-900
        prose-h1:text-4xl prose-h1:mb-8
        prose-h2:text-2xl prose-h2:mt-12 prose-h2:mb-6
        prose-h3:text-xl prose-h3:mt-8 prose-h3:mb-4
        prose-p:text-slate-700 prose-p:leading-relaxed prose-p:mb-6
        prose-a:text-blue-600 prose-a:no-underline hover:prose-a:underline
        prose-strong:font-semibold prose-strong:text-slate-900
        prose-code:text-violet-600 prose-code:bg-violet-50 prose-code:px-1.5 prose-code:py-0.5 prose-code:rounded-md prose-code:before:content-none prose-code:after:content-none
        prose-pre:bg-slate-50 prose-pre:text-slate-800 prose-pre:border prose-pre:border-slate-200
        prose-blockquote:border-l-4 prose-blockquote:border-slate-300 prose-blockquote:bg-slate-50 prose-blockquote:py-2 prose-blockquote:px-4 prose-blockquote:not-italic prose-blockquote:text-slate-700
        prose-img:rounded-2xl prose-img:shadow-lg prose-img:mx-auto
        prose-li:marker:text-slate-400
        prose-table:w-full prose-table:border-collapse prose-table:text-sm
        prose-th:border prose-th:border-slate-200 prose-th:bg-slate-50 prose-th:px-4 prose-th:py-3 prose-th:font-semibold prose-th:text-slate-800
        prose-td:border prose-td:border-slate-200 prose-td:px-4 prose-td:py-3 prose-td:text-slate-700
      ">
        <MarkdownViewer content={content} variant="document" headingAnchors />
      </div>
    </div>
  );
}
