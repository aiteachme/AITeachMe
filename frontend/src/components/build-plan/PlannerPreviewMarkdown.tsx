import { MarkdownViewer } from "../ui/MarkdownViewer";

interface PlannerPreviewMarkdownProps {
  markdown: string;
}

export function PlannerPreviewMarkdown({ markdown }: PlannerPreviewMarkdownProps) {
  if (!markdown.trim()) {
    return null;
  }

  return (
    <div className="rounded-xl border border-zinc-200 bg-zinc-50/70 px-3 py-3">
      <MarkdownViewer content={markdown} variant="planner" />
    </div>
  );
}
