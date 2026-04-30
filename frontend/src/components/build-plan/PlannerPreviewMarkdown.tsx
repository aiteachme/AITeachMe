import { MarkdownViewer } from "../ui/MarkdownViewer";

interface PlannerPreviewMarkdownProps {
  markdown: string;
  streaming?: boolean;
}

export function PlannerPreviewMarkdown({
  markdown,
  streaming = false,
}: PlannerPreviewMarkdownProps) {
  if (!markdown.trim()) {
    return null;
  }

  return (
    <div className="space-y-3">
      <MarkdownViewer content={markdown} variant="planner" />
      {streaming ? (
        <div
          aria-live="polite"
          className="flex items-center gap-2 text-xs text-zinc-400 dark:text-slate-500"
        >
          <span className="relative flex h-2 w-2">
            <span className="build-live-dot h-2 w-2 text-indigo-500" />
          </span>
          <span>正在继续规划...</span>
        </div>
      ) : null}
    </div>
  );
}
