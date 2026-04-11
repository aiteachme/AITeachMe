import { MarkdownViewer } from "../../ui/MarkdownViewer";

interface GeminiDocumentViewerProps {
  content: string;
}

export function GeminiDocumentViewer({ content }: GeminiDocumentViewerProps) {
  return (
    <div className="mx-auto w-full max-w-[860px] px-8 pt-8 pb-32">
      <div className="prose prose-slate prose-lg font-sans max-w-none 
        [&>h1:first-child]:hidden
        prose-headings:font-bold prose-headings:tracking-tight prose-headings:text-slate-900
        prose-h1:text-[2.5rem] prose-h1:leading-tight prose-h1:mb-10
        prose-h2:text-[1.75rem] prose-h2:mt-14 prose-h2:mb-6 prose-h2:pb-2 prose-h2:border-b prose-h2:border-slate-100
        prose-h3:text-xl prose-h3:mt-10 prose-h3:mb-4
        prose-p:text-slate-700 prose-p:leading-[1.8] prose-p:mb-5 prose-p:text-[1.05rem]
        prose-a:text-blue-600 prose-a:font-medium prose-a:underline-offset-2 hover:prose-a:text-blue-700
        prose-strong:font-semibold prose-strong:text-slate-900
        prose-code:text-indigo-600 prose-code:bg-indigo-50/50 prose-code:px-1.5 prose-code:py-0.5 prose-code:rounded-md prose-code:font-medium prose-code:before:content-none prose-code:after:content-none
        prose-pre:bg-[#1E1E1E] prose-pre:text-slate-50 prose-pre:rounded-xl prose-pre:shadow-sm prose-pre:border prose-pre:border-slate-800
        prose-blockquote:border-l-4 prose-blockquote:border-blue-500 prose-blockquote:bg-blue-50/30 prose-blockquote:py-3 prose-blockquote:px-5 prose-blockquote:not-italic prose-blockquote:text-slate-700 prose-blockquote:rounded-r-xl
        prose-img:rounded-xl prose-img:shadow-md prose-img:border prose-img:border-slate-100 prose-img:mx-auto
        prose-ul:text-slate-700 prose-ul:leading-[1.8] prose-ul:text-[1.05rem] prose-li:marker:text-slate-400
        prose-ol:text-slate-700 prose-ol:leading-[1.8] prose-ol:text-[1.05rem]
        prose-table:w-full prose-table:border-collapse prose-table:text-sm prose-table:rounded-xl prose-table:overflow-hidden prose-table:shadow-sm prose-table:border prose-table:border-slate-200
        prose-th:border-b prose-th:border-slate-200 prose-th:bg-slate-50/80 prose-th:px-5 prose-th:py-3.5 prose-th:font-semibold prose-th:text-slate-900 prose-th:text-left
        prose-td:border-b prose-td:border-slate-100 prose-td:px-5 prose-td:py-3.5 prose-td:text-slate-700
        [&_tbody_tr:last-child_td]:border-b-0
        transition-all duration-300 ease-in-out
      ">
        <MarkdownViewer content={content} variant="document" headingAnchors />
      </div>
    </div>
  );
}
