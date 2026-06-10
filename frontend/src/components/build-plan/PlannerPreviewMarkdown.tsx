import { MarkdownViewer } from "../ui/MarkdownViewer";

interface PlannerPreviewMarkdownProps {
  markdown: string;
}

export function PlannerPreviewMarkdown({ markdown }: PlannerPreviewMarkdownProps) {
  if (!markdown.trim()) {
    return null;
  }

  return (
    <div className="space-y-3">
      <MarkdownViewer content={markdown} variant="planner" />
    </div>
  );
}
