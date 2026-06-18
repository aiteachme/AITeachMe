import { MarkdownViewer } from "../ui/MarkdownViewer";

export const EXAM_QUESTION_TEXT_CLASS =
  "break-words font-serif text-base font-semibold leading-8 text-slate-950 dark:text-slate-100 sm:text-lg [&_p]:mb-0 [&_p]:text-base [&_p]:leading-8 sm:[&_p]:text-lg sm:[&_p]:leading-8 [&_.katex-display]:my-4 [&_.katex]:text-inherit";

export const EXAM_OPTION_BUTTON_TEXT_CLASS =
  "font-serif text-[15px] leading-7 sm:text-base";

export const EXAM_OPTION_MARKDOWN_CLASS =
  "min-w-0 flex-1 [&_p]:mb-0 [&_p]:text-[15px] [&_p]:leading-7 sm:[&_p]:text-base sm:[&_p]:leading-7 [&_.katex-display]:my-3 [&_.katex]:text-inherit";

export const EXAM_ANSWER_TEXT_CLASS =
  "font-serif text-[15px] leading-7 text-slate-700 dark:text-slate-300 sm:text-base [&_p]:mb-2 [&_p]:text-[15px] [&_p]:leading-7 sm:[&_p]:text-base sm:[&_p]:leading-7 [&_.katex-display]:my-3 [&_.katex]:text-inherit";

export const EXAM_TEXTAREA_TEXT_CLASS =
  "font-serif text-base leading-8 sm:text-lg";

export const EXAM_CANVAS_TEXT_CLASS =
  "text-[14px] leading-6 [&_p]:mb-0 [&_p]:text-[14px] [&_p]:leading-6 [&_.katex-display]:my-1 [&_.katex]:font-normal";

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
