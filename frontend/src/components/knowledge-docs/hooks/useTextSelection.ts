import { useState, useEffect, RefObject } from "react";

export interface SelectionState {
  text: string;
  anchorId: string;
  top: number;
  left: number;
}

export function useTextSelection(containerRef: RefObject<HTMLElement>) {
  const [selection, setSelection] = useState<SelectionState | null>(null);

  useEffect(() => {
    function handleSelectionChange() {
      const domSelection = window.getSelection();
      if (!domSelection || domSelection.isCollapsed) {
        setSelection(null);
        return;
      }

      const text = domSelection.toString().trim();
      if (!text) {
        setSelection(null);
        return;
      }

      const range = domSelection.getRangeAt(0);
      const container = containerRef.current;
      if (!container || !container.contains(range.commonAncestorContainer)) {
        setSelection(null);
        return;
      }

      // Find closest anchor ID
      let node: Node | null = range.commonAncestorContainer;
      if (node.nodeType === Node.TEXT_NODE) {
        node = node.parentNode;
      }

      let anchorId = "root";
      while (node && node !== container) {
        if ((node as HTMLElement).hasAttribute?.("data-heading-id")) {
          anchorId = (node as HTMLElement).getAttribute("data-heading-id")!;
          break;
        }
        node = node.parentNode;
      }

      const rect = range.getBoundingClientRect();
      const containerRect = container.getBoundingClientRect();

      setSelection({
        text,
        anchorId,
        top: container.scrollTop + (rect.top - containerRect.top),
        left: rect.left - containerRect.left + rect.width / 2,
      });
    }

    document.addEventListener("selectionchange", handleSelectionChange);
    return () => {
      document.removeEventListener("selectionchange", handleSelectionChange);
    };
  }, [containerRef]);

  return { selection, setSelection };
}
