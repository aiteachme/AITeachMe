import { BookOpenText, ChevronRight, LibraryBig } from "lucide-react";
import { type ChatContextItem } from "../../api/chatApi";

interface ChatCitationListProps {
  contexts: ChatContextItem[];
  onOpenContext: (chunkId: number) => void;
}

export function ChatCitationList({ contexts, onOpenContext }: ChatCitationListProps) {
  return (
    <div className="mt-4 space-y-2">
      <div className="flex items-center gap-2 text-xs font-medium uppercase tracking-[0.18em] text-slate-400">
        <LibraryBig className="h-3.5 w-3.5" />
        引用来源
      </div>
      <div className="grid gap-2">
        {contexts.map((context) => (
          <button
            key={`${context.chunkId}-${context.documentId}`}
            type="button"
            onClick={() => onOpenContext(context.chunkId)}
            className="group rounded-2xl border border-slate-200 bg-white px-4 py-3 text-left shadow-sm transition hover:border-slate-300 hover:shadow-md"
          >
            <div className="flex items-start justify-between gap-3">
              <div className="min-w-0">
                <div className="flex items-center gap-2 text-sm font-semibold text-slate-800">
                  <BookOpenText className="h-4 w-4 text-sky-600" />
                  <span className="truncate">{context.title || "未命名切块"}</span>
                </div>
                <p className="mt-1 line-clamp-2 text-xs leading-5 text-slate-500">
                  {context.headerPath || "未提供标题路径"}
                </p>
              </div>
              <div className="flex shrink-0 items-center gap-2 text-xs text-slate-400">
                <span className="rounded-full bg-slate-100 px-2 py-1 font-medium text-slate-500">
                  相关度 {Math.round(context.score * 100)}%
                </span>
                <ChevronRight className="h-4 w-4 transition group-hover:translate-x-0.5" />
              </div>
            </div>
          </button>
        ))}
      </div>
    </div>
  );
}
