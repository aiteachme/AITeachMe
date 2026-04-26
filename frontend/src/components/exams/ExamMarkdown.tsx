import { MarkdownViewer } from "../ui/MarkdownViewer";

export function ExamMarkdown({
  content,
  className,
}: {
  content: string;
  className?: string;
}) {
  return (
    <div className={className} style={{ overflowWrap: "anywhere" }}>
      <MarkdownViewer content={content} variant="default" />
    </div>
  );
}
