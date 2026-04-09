/* ------------------------------------------------------------------ */
/*  DocHighlightOverlay — Selection highlight overlays for threads     */
/* ------------------------------------------------------------------ */

import { cn } from "../../lib/utils";
import type { SelectionHighlight } from "./types";

interface Props {
  highlights: SelectionHighlight[];
  highlightedThreadId: string | null;
  onLocateThread: (threadId: string) => void;
}

export function DocHighlightOverlay({ highlights, highlightedThreadId, onLocateThread }: Props) {
  return (
    <>
      {highlights.map((highlight) => (
        <div key={highlight.id}>
          {highlight.segments.map((segment, index) => (
            <button
              key={`${highlight.id}-${index}`}
              type="button"
              onClick={() => onLocateThread(highlight.threadId)}
              data-highlight-thread-id={highlight.threadId}
              className={cn(
                "group absolute z-30 rounded-[2px] transition-colors focus-visible:outline-none",
                highlightedThreadId === highlight.threadId
                  ? "bg-[#3370FF]/10 ring-1 ring-[#3370FF]/30"
                  : "bg-transparent hover:bg-[#FFAA00]/10 focus-visible:ring-2 focus-visible:ring-[#FFAA00]/30",
              )}
              style={{
                top: segment.top,
                left: segment.left,
                width: segment.width,
                height: segment.height,
              }}
              title={`定位问答：${highlight.selectedText}`}
              aria-label="定位划词问答"
            >
              <span
                className={cn(
                  "pointer-events-none absolute inset-x-0 bottom-0 rounded-full transition-all",
                  highlightedThreadId === highlight.threadId
                    ? "h-[2px] bg-[#3370FF]"
                    : "h-[1.5px] bg-[#FFAA00]/70 group-hover:h-[2px] group-hover:bg-[#FFAA00]",
                )}
              />
            </button>
          ))}
        </div>
      ))}
    </>
  );
}
