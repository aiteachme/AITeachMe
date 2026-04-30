import { cn } from "../../lib/utils";

interface AiConversationSelectionTextPreviewProps {
  prefix: string;
  text: string;
  className?: string;
  placement?: "above" | "below";
}

export function AiConversationSelectionTextPreview({
  prefix,
  text,
  className,
  placement = "below",
}: AiConversationSelectionTextPreviewProps) {
  const normalizedText = text.replace(/\s+/g, " ").trim();
  if (!normalizedText) {
    return null;
  }

  return (
    <div className={cn("group relative min-w-0 max-w-full", className)} aria-label={`${prefix}${normalizedText}`}>
      <p className="block min-w-0 max-w-full truncate whitespace-nowrap">
        {prefix}{normalizedText}
      </p>
      <div
        className={cn(
          "absolute left-0 z-[70] hidden max-h-44 w-max max-w-[min(34rem,calc(100vw-2rem))] overflow-y-auto whitespace-normal break-words rounded-lg border border-slate-200 bg-white px-3 py-2 text-[12px] leading-5 text-slate-700 shadow-xl shadow-slate-900/10 [overflow-wrap:anywhere] group-hover:block dark:border-slate-700 dark:bg-slate-900 dark:text-slate-100",
          placement === "above" ? "bottom-full mb-2" : "top-full mt-2",
        )}
      >
        <span className="font-semibold text-slate-500 dark:text-slate-300">{prefix}</span>
        {normalizedText}
      </div>
    </div>
  );
}
