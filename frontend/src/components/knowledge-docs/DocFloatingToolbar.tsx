/* ------------------------------------------------------------------ */
/*  DocFloatingToolbar — Feishu-style "Ask AI" toolbar on text select  */
/* ------------------------------------------------------------------ */

import { Sparkles } from "lucide-react";
import type { FloatingToolbar } from "./types";

interface Props {
  toolbar: FloatingToolbar;
  floatingRef: React.RefObject<HTMLDivElement | null>;
  onAskAi: () => void;
}

export function DocFloatingToolbar({ toolbar, floatingRef, onAskAi }: Props) {
  return (
    <div
      ref={floatingRef as React.RefObject<HTMLDivElement>}
      className="absolute z-50 -translate-x-1/2"
      style={{
        top: toolbar.top,
        left: toolbar.left,
      }}
      onMouseUp={(e) => e.stopPropagation()}
    >
      <div className="inline-flex items-center gap-2 rounded-lg border border-[#DEE0E3] bg-white px-2 py-1.5 shadow-[0_4px_16px_rgba(0,0,0,0.08)]">
        <span className="max-w-40 truncate px-1 text-[11px] text-[#8F959E]">
          &ldquo;{toolbar.selectedText.slice(0, 60)}&rdquo;
        </span>
        <button
          onMouseDown={(e) => e.preventDefault()}
          onClick={onAskAi}
          className="inline-flex h-7 items-center gap-1.5 rounded-md bg-[#3370FF] px-3 text-[12px] font-medium text-white shadow-sm transition hover:bg-[#245BDB] active:scale-[0.97]"
        >
          <Sparkles className="h-3 w-3" />
          问问AI
        </button>
      </div>
    </div>
  );
}
