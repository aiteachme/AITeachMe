import ReactMarkdown from "react-markdown";

interface MarkdownViewerProps {
  content: string;
}

export function MarkdownViewer({ content }: MarkdownViewerProps) {
  return (
    <ReactMarkdown
      components={{
        h1: ({ children }) => (
          <h1 className="text-2xl font-bold text-slate-900 mt-6 mb-3 pb-2 border-b border-slate-200">
            {children}
          </h1>
        ),
        h2: ({ children }) => (
          <h2 className="text-xl font-semibold text-slate-800 mt-5 mb-2">{children}</h2>
        ),
        h3: ({ children }) => (
          <h3 className="text-lg font-semibold text-slate-800 mt-4 mb-2">{children}</h3>
        ),
        h4: ({ children }) => (
          <h4 className="text-base font-semibold text-slate-700 mt-3 mb-1">{children}</h4>
        ),
        p: ({ children }) => (
          <p className="text-sm text-slate-700 leading-relaxed mb-3">{children}</p>
        ),
        ul: ({ children }) => (
          <ul className="list-disc list-inside text-sm text-slate-700 mb-3 space-y-1 pl-2">
            {children}
          </ul>
        ),
        ol: ({ children }) => (
          <ol className="list-decimal list-inside text-sm text-slate-700 mb-3 space-y-1 pl-2">
            {children}
          </ol>
        ),
        li: ({ children }) => (
          <li className="leading-relaxed [&>p]:inline [&>p]:mb-0">{children}</li>
        ),
        blockquote: ({ children }) => (
          <blockquote className="border-l-4 border-slate-300 pl-4 italic text-slate-600 my-3">
            {children}
          </blockquote>
        ),
        code: ({ className, children }) => {
          const isBlock = className?.includes("language-");
          if (isBlock) {
            return (
              <pre className="bg-slate-900 text-slate-100 rounded-lg p-4 overflow-x-auto text-sm my-3">
                <code>{children}</code>
              </pre>
            );
          }
          return (
            <code className="bg-slate-100 text-slate-800 rounded px-1.5 py-0.5 text-sm font-mono">
              {children}
            </code>
          );
        },
        pre: ({ children }) => <>{children}</>,
        table: ({ children }) => (
          <div className="overflow-x-auto my-3">
            <table className="min-w-full text-sm border border-slate-200 rounded-lg">
              {children}
            </table>
          </div>
        ),
        thead: ({ children }) => (
          <thead className="bg-slate-50 border-b border-slate-200">{children}</thead>
        ),
        th: ({ children }) => (
          <th className="px-3 py-2 text-left font-semibold text-slate-700">{children}</th>
        ),
        td: ({ children }) => (
          <td className="px-3 py-2 text-slate-600 border-t border-slate-100">{children}</td>
        ),
        hr: () => <hr className="my-4 border-slate-200" />,
        a: ({ href, children }) => (
          <a href={href} className="text-blue-600 hover:underline" target="_blank" rel="noopener noreferrer">
            {children}
          </a>
        ),
        strong: ({ children }) => (
          <strong className="font-semibold text-slate-900">{children}</strong>
        ),
        em: ({ children }) => <em className="italic text-slate-600">{children}</em>,
      }}
    >
      {content}
    </ReactMarkdown>
  );
}
