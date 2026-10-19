import { useId } from "react";
import { ScanEye } from "lucide-react";

import { cn } from "../../lib/utils";
import type { FileRecord } from "../../types/files";

export function haveNoDocumentImages(files: FileRecord[]): boolean {
  return files.length > 0 && files.every((file) => file.markdown_ready && file.image_count === 0);
}

interface Props {
  checked: boolean;
  onChange: (enabled: boolean) => void;
  disabled?: boolean;
  noImages?: boolean;
  statusText?: string;
}

export function ImageUnderstandingToggle({ checked, onChange, disabled, noImages, statusText }: Props) {
  const descriptionId = useId();
  const enabled = checked && !noImages;

  return (
    <div className="flex min-w-0 flex-wrap items-center gap-x-3 gap-y-0.5 border-t border-zinc-100 px-1 pt-2 dark:border-slate-800">
      <button
        type="button"
        role="switch"
        aria-label="图片理解"
        aria-checked={enabled}
        aria-describedby={descriptionId}
        disabled={disabled || noImages}
        onClick={() => onChange(!enabled)}
        className="inline-flex min-h-10 shrink-0 items-center gap-2 rounded-md text-xs font-medium text-zinc-700 transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-indigo-400/50 disabled:cursor-not-allowed disabled:opacity-50 dark:text-slate-200"
      >
        <ScanEye className="h-4 w-4 text-zinc-500 dark:text-slate-400" aria-hidden="true" />
        <span>图片理解</span>
        <span
          aria-hidden="true"
          className={cn("relative h-5 w-8 rounded-full transition-colors", enabled ? "bg-indigo-600" : "bg-zinc-300 dark:bg-slate-600")}
        >
          <span className={cn("absolute left-0 top-0.5 h-4 w-4 rounded-full bg-white shadow-sm transition-transform", enabled ? "translate-x-3.5" : "translate-x-0.5")} />
        </span>
      </button>
      <p id={descriptionId} className="min-w-0 flex-1 basis-52 text-[11px] leading-5 text-zinc-500 dark:text-slate-400">
        关闭只分析文本；开启会分析图片，但会增加耗时。
        {(noImages || statusText) && <span className="block">{noImages ? "资料中未发现图片，将只分析文本。" : statusText}</span>}
      </p>
    </div>
  );
}
