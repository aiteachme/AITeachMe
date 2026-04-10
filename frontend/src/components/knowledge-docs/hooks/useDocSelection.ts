/* ------------------------------------------------------------------ */
/*  useDocSelection — Text selection, range capture, highlight overlay */
/* ------------------------------------------------------------------ */

import { useState, useCallback, useEffect, useRef } from "react";
import type { FloatingToolbar, FloatingComment, HighlightSegment, SelectionHighlight } from "../types";

export interface DocSelectionState {
  floatingToolbar: FloatingToolbar | null;
  setFloatingToolbar: (v: FloatingToolbar | null) => void;
  floatingComment: FloatingComment | null;
  setFloatingComment: (v: FloatingComment | null) => void;
  floatingInput: string;
  setFloatingInput: (v: string) => void;
  selectionHighlights: SelectionHighlight[];
  setSelectionHighlights: React.Dispatch<React.SetStateAction<SelectionHighlight[]>>;
  selectedRangeRef: React.RefObject<Range | null>;
  floatingRef: React.RefObject<HTMLDivElement | null>;
  handleTextSelect: () => void;
  captureSelectionSegments: () => HighlightSegment[];
  captureRangeSegments: (range: Range) => HighlightSegment[];
  buildSelectionSegmentsFromText: (anchorId: string, selectedText: string) => HighlightSegment[];
  addSelectionHighlight: (threadId: string, anchorId: string, selectedText: string, preferred?: HighlightSegment[]) => void;
  clearSelectionHighlight: () => void;
  dismissCommentComposer: () => void;
  computeCommentComposerTop: (selectionViewportTop: number) => number;
}

export function useDocSelection(
  scrollRef: React.RefObject<HTMLDivElement | null>,
  contentAreaRef: React.RefObject<HTMLDivElement | null>,
  commentPanelRef: React.RefObject<HTMLDivElement | null>,
): DocSelectionState {
  const [floatingToolbar, setFloatingToolbar] = useState<FloatingToolbar | null>(null);
  const [floatingComment, setFloatingComment] = useState<FloatingComment | null>(null);
  const [floatingInput, setFloatingInput] = useState("");
  const [selectionHighlights, setSelectionHighlights] = useState<SelectionHighlight[]>([]);
  const selectedRangeRef = useRef<Range | null>(null);
  const floatingRef = useRef<HTMLDivElement>(null);

  const captureRangeSegments = useCallback((range: Range): HighlightSegment[] => {
    const container = scrollRef.current;
    if (!container) return [];
    const containerRect = container.getBoundingClientRect();
    const rects = Array.from(range.getClientRects()).filter(
      (rect) => rect.width > 1 || rect.height > 1,
    );
    const toSegment = (rect: DOMRect): HighlightSegment => ({
      top: rect.top - containerRect.top + container.scrollTop,
      left: rect.left - containerRect.left + container.scrollLeft,
      width: Math.max(16, rect.width),
      height: Math.max(18, rect.height),
    });
    if (rects.length === 0) {
      const rect = range.getBoundingClientRect();
      if (rect.width < 1 && rect.height < 1) return [];
      return [toSegment(rect)];
    }
    return rects.map(toSegment);
  }, [scrollRef]);

  const captureSelectionSegments = useCallback((): HighlightSegment[] => {
    const range = selectedRangeRef.current;
    if (!range) return [];
    return captureRangeSegments(range);
  }, [captureRangeSegments]);

  const buildSelectionSegmentsFromText = useCallback((anchorId: string, selectedText: string): HighlightSegment[] => {
    const contentRoot = contentAreaRef.current;
    if (!contentRoot) return [];
    const target = selectedText.trim();
    if (!target) return [];
    const heading = contentRoot.querySelector(`[data-heading-id="${anchorId}"]`) as HTMLElement | null;
    if (!heading) return [];
    const allHeadings = Array.from(contentRoot.querySelectorAll<HTMLElement>("[data-heading-id]"));
    const headingIndex = allHeadings.findIndex((node) => node === heading);
    const nextHeading = headingIndex >= 0 ? allHeadings[headingIndex + 1] ?? null : null;
    const sectionRoots: Node[] = [];
    let node: Node | null = heading;
    while (node && node !== nextHeading) {
      sectionRoots.push(node);
      node = node.nextSibling;
    }
    if (sectionRoots.length === 0) return [];

    const textEntries: Array<{ node: Text; start: number; end: number }> = [];
    let rawText = "";
    for (const rootNode of sectionRoots) {
      const walker = document.createTreeWalker(rootNode, NodeFilter.SHOW_TEXT);
      let current = walker.nextNode();
      while (current) {
        const textNode = current as Text;
        const value = textNode.nodeValue ?? "";
        if (value.length > 0) {
          const start = rawText.length;
          rawText += value;
          textEntries.push({ node: textNode, start, end: rawText.length });
        }
        current = walker.nextNode();
      }
    }
    if (!rawText || textEntries.length === 0) return [];

    let matchStart = rawText.indexOf(target);
    let matchEnd = matchStart >= 0 ? matchStart + target.length : -1;
    if (matchStart < 0) {
      const condensedRawChars: string[] = [];
      const rawIndexByCondensed: number[] = [];
      for (let i = 0; i < rawText.length; i += 1) {
        const char = rawText[i];
        if (!/\s/u.test(char)) {
          condensedRawChars.push(char);
          rawIndexByCondensed.push(i);
        }
      }
      const condensedRaw = condensedRawChars.join("");
      const condensedTarget = target.replace(/\s+/gu, "");
      const condensedStart = condensedTarget ? condensedRaw.indexOf(condensedTarget) : -1;
      if (condensedStart < 0) return [];
      const rawStart = rawIndexByCondensed[condensedStart];
      const rawEnd = rawIndexByCondensed[condensedStart + condensedTarget.length - 1];
      if (rawStart === undefined || rawEnd === undefined) return [];
      matchStart = rawStart;
      matchEnd = rawEnd + 1;
    }
    if (matchStart < 0 || matchEnd <= matchStart) return [];

    const startEntry = textEntries.find((entry) => matchStart >= entry.start && matchStart < entry.end);
    const endBoundary = Math.max(matchStart, matchEnd - 1);
    const endEntry = textEntries.find((entry) => endBoundary >= entry.start && endBoundary < entry.end);
    if (!startEntry || !endEntry) return [];

    const range = document.createRange();
    range.setStart(startEntry.node, matchStart - startEntry.start);
    range.setEnd(endEntry.node, matchEnd - endEntry.start);
    return captureRangeSegments(range);
  }, [captureRangeSegments, contentAreaRef]);

  const addSelectionHighlight = useCallback((threadId: string, anchorId: string, selectedText: string, preferred?: HighlightSegment[]) => {
    const segments = preferred ?? captureSelectionSegments();
    if (segments.length === 0) return;
    const next: SelectionHighlight = {
      id: `highlight-${threadId}`,
      threadId,
      anchorId,
      selectedText,
      segments,
    };
    setSelectionHighlights((prev) => {
      const kept = prev.filter((item) => item.threadId !== threadId);
      return [next, ...kept].slice(0, 200);
    });
  }, [captureSelectionSegments]);

  const clearSelectionHighlight = useCallback(() => {
    selectedRangeRef.current = null;
    const selection = window.getSelection();
    if (selection && !selection.isCollapsed) {
      selection.removeAllRanges();
    }
  }, []);

  const dismissCommentComposer = useCallback(() => {
    setFloatingComment(null);
    setFloatingInput("");
  }, []);

  const computeCommentComposerTop = useCallback((selectionViewportTop: number) => {
    const panel = commentPanelRef.current;
    if (!panel) return 56;
    const panelRect = panel.getBoundingClientRect();
    const rawTop = selectionViewportTop - panelRect.top - 24;
    const minTop = 56;
    const estimatedComposerHeight = 208;
    const maxTop = Math.max(minTop, panelRect.height - estimatedComposerHeight - 12);
    return Math.min(maxTop, Math.max(minTop, rawTop));
  }, [commentPanelRef]);

  const handleTextSelect = useCallback(() => {
    const sel = window.getSelection();
    if (!sel || sel.isCollapsed || !sel.toString().trim()) {
      setFloatingToolbar(null);
      selectedRangeRef.current = null;
      return;
    }
    const selectedText = sel.toString().trim();
    const range = sel.getRangeAt(0);
    const rect = range.getBoundingClientRect();
    const container = scrollRef.current;
    if (!container) return;
    const contentArea = contentAreaRef.current;
    if (contentArea && !contentArea.contains(range.commonAncestorContainer)) return;
    const containerRect = container.getBoundingClientRect();

    let nodeIter: Node | null = sel.anchorNode;
    let headingId = "";
    while (nodeIter && nodeIter !== container) {
      if (nodeIter instanceof HTMLElement) {
        const hid = nodeIter.getAttribute("data-heading-id");
        if (hid) { headingId = hid; break; }
      }
      nodeIter = nodeIter.parentNode;
    }
    if (!headingId) {
      const allHeadings = container.querySelectorAll("[data-heading-id]");
      for (const h of allHeadings) {
        const hRange = document.createRange();
        hRange.selectNode(h);
        if (hRange.compareBoundaryPoints(Range.START_TO_START, range) <= 0) {
          headingId = h.getAttribute("data-heading-id") ?? "";
        }
      }
    }

    if (headingId) {
      selectedRangeRef.current = range.cloneRange();
      const contentTop = rect.top - containerRect.top + container.scrollTop;
      const contentLeft = rect.left - containerRect.left + container.scrollLeft + rect.width / 2;
      const top = Math.max(container.scrollTop + 8, contentTop - 46);
      const left = Math.min(
        container.scrollLeft + container.clientWidth - 170,
        Math.max(container.scrollLeft + 170, contentLeft),
      );
      setFloatingToolbar({
        anchorId: headingId,
        selectedText,
        top,
        left,
        selectionViewportTop: rect.top + rect.height / 2,
      });
      setFloatingComment(null);
      setFloatingInput("");
    }
  }, [scrollRef, contentAreaRef]);

  /* Clear on click outside */
  useEffect(() => {
    const handlePointerDown = (e: MouseEvent) => {
      if (floatingRef.current?.contains(e.target as Node)) return;
      clearSelectionHighlight();
      setFloatingToolbar(null);
    };
    document.addEventListener("mousedown", handlePointerDown);
    return () => document.removeEventListener("mousedown", handlePointerDown);
  }, [clearSelectionHighlight]);

  /* Restore selection after toolbar render */
  useEffect(() => {
    if (!floatingToolbar) return;
    const raf = window.requestAnimationFrame(() => {
      const range = selectedRangeRef.current;
      if (!range) return;
      const selection = window.getSelection();
      if (!selection || !selection.isCollapsed) return;
      try {
        selection.removeAllRanges();
        selection.addRange(range);
      } catch {
        selectedRangeRef.current = null;
      }
    });
    return () => window.cancelAnimationFrame(raf);
  }, [floatingToolbar]);

  return {
    floatingToolbar,
    setFloatingToolbar,
    floatingComment,
    setFloatingComment,
    floatingInput,
    setFloatingInput,
    selectionHighlights,
    setSelectionHighlights,
    selectedRangeRef,
    floatingRef,
    handleTextSelect,
    captureSelectionSegments,
    captureRangeSegments,
    buildSelectionSegmentsFromText,
    addSelectionHighlight,
    clearSelectionHighlight,
    dismissCommentComposer,
    computeCommentComposerTop,
  };
}
