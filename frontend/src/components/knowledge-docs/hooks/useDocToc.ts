/* ------------------------------------------------------------------ */
/*  useDocToc — TOC parsing, active heading tracking, scroll-to        */
/* ------------------------------------------------------------------ */

import { useState, useEffect, useCallback, useLayoutEffect, useMemo, useRef } from "react";
import type { TocItem, TocTreeNode } from "../types";
import { tocEqual, buildTocTree, findAncestorIds } from "../utils";

export interface DocTocState {
  toc: TocItem[];
  tocTree: TocTreeNode[];
  activeHeading: string;
  setActiveHeading: (id: string) => void;
  activeTocItem: TocItem | null;
  collapsedTocIds: Set<string>;
  toggleTocCollapse: (id: string) => void;
  scrollToHeading: (id: string) => void;
  tocNavRef: React.RefObject<HTMLElement | null>;
}

export function useDocToc(
  renderedMarkdown: string,
  scrollRef: React.RefObject<HTMLDivElement | null>,
  scrollElement?: HTMLDivElement | null,
): DocTocState {
  const [toc, setToc] = useState<TocItem[]>([]);
  const [activeHeading, setActiveHeading] = useState("");
  const [collapsedTocIds, setCollapsedTocIds] = useState<Set<string>>(new Set());
  const tocNavRef = useRef<HTMLElement>(null);
  const headingFlashTimersRef = useRef(new Map<string, number>());

  const tocTree = useMemo(() => buildTocTree(toc), [toc]);

  const activeTocItem = useMemo(
    () => toc.find((item) => item.id === activeHeading) ?? null,
    [activeHeading, toc],
  );

  /* Parse headings from rendered markdown */
  useLayoutEffect(() => {
    let rafId = 0;
    let disposed = false;
    const retryTimerIds: number[] = [];
    const observers: MutationObserver[] = [];

    const resolveScrollContainer = () => (
      scrollElement ?? scrollRef.current ?? document.querySelector<HTMLDivElement>(".doc-scroll-container")
    );

    const collectHeadings = () => {
      if (disposed) return;
      const container = resolveScrollContainer();
      if (!container) return;
      const headingNodes = container.querySelectorAll<HTMLElement>(
        "h1[data-heading-id], h2[data-heading-id], h3[data-heading-id], h4[data-heading-id], h5[data-heading-id], h6[data-heading-id]",
      );
      const nextToc: TocItem[] = Array.from(headingNodes)
        .map((node) => {
          const id = node.getAttribute("data-heading-id") ?? node.id;
          if (!id) return null;
          const level = Number(node.tagName.replace("H", ""));
          if (!Number.isInteger(level) || level < 1 || level > 6) return null;
          const text = node.textContent?.trim() || id;
          return { id, text, level };
        })
        .filter((item): item is TocItem => item !== null);
      setToc((prev) => (tocEqual(prev, nextToc) ? prev : nextToc));
    };
    const scheduleCollect = () => {
      window.cancelAnimationFrame(rafId);
      rafId = window.requestAnimationFrame(collectHeadings);
    };

    scheduleCollect();
    for (const delay of [80, 180, 360, 720, 1200]) {
      retryTimerIds.push(window.setTimeout(scheduleCollect, delay));
    }

    const observe = (target: HTMLElement | null) => {
      if (!target) return;
      const observer = new MutationObserver(scheduleCollect);
      observer.observe(target, {
        childList: true,
        subtree: true,
        attributes: true,
        attributeFilter: ["data-heading-id", "id"],
      });
      observers.push(observer);
    };

    const container = resolveScrollContainer();
    observe(container);
    if (!container) observe(document.body);

    return () => {
      disposed = true;
      window.cancelAnimationFrame(rafId);
      retryTimerIds.forEach((timerId) => window.clearTimeout(timerId));
      observers.forEach((observer) => observer.disconnect());
    };
  }, [renderedMarkdown, scrollElement, scrollRef]);

  /* Auto-expand ancestors of active heading */
  useEffect(() => {
    if (!activeHeading || tocTree.length === 0) return;
    const ancestors = findAncestorIds(tocTree, activeHeading);
    if (ancestors.length === 0) return;
    setCollapsedTocIds((prev) => {
      let changed = false;
      const next = new Set(prev);
      for (const id of ancestors) {
        if (next.has(id)) {
          next.delete(id);
          changed = true;
        }
      }
      return changed ? next : prev;
    });
  }, [activeHeading, tocTree]);

  /* Auto-scroll TOC sidebar to keep active item visible */
  useEffect(() => {
    if (!activeHeading || !tocNavRef.current) return;
    const activeBtn = tocNavRef.current.querySelector(`[data-toc-id="${activeHeading}"]`) as HTMLElement | null;
    if (!activeBtn) return;
    const nav = tocNavRef.current;
    const navRect = nav.getBoundingClientRect();
    const btnRect = activeBtn.getBoundingClientRect();
    if (btnRect.top < navRect.top + 8 || btnRect.bottom > navRect.bottom - 8) {
      activeBtn.scrollIntoView({ behavior: "smooth", block: "center" });
    }
  }, [activeHeading]);

  /* Track active heading on scroll */
  useEffect(() => {
    const container = scrollElement ?? scrollRef.current;
    if (!container) return;
    let rafPending = false;
    const handleScroll = () => {
      if (rafPending) return;
      rafPending = true;
      window.requestAnimationFrame(() => {
        rafPending = false;
        const headings = container.querySelectorAll("[data-heading-id]");
        let current = "";
        for (const el of headings) {
          const rect = el.getBoundingClientRect();
          if (rect.top <= 120) {
            current = el.getAttribute("data-heading-id") ?? "";
          }
        }
        setActiveHeading(current);
      });
    };
    container.addEventListener("scroll", handleScroll, { passive: true });
    handleScroll();
    return () => container.removeEventListener("scroll", handleScroll);
  }, [renderedMarkdown, scrollElement, scrollRef]);

  /* Flash heading animation */
  const flashHeading = useCallback((node: HTMLElement) => {
    const headingId = node.getAttribute("data-heading-id") ?? node.id;
    const existingTimer = headingFlashTimersRef.current.get(headingId);
    if (existingTimer) window.clearTimeout(existingTimer);
    node.classList.remove("heading-flash");
    void node.offsetWidth;
    node.classList.add("heading-flash");
    const timer = window.setTimeout(() => {
      node.classList.remove("heading-flash");
      headingFlashTimersRef.current.delete(headingId);
    }, 950);
    headingFlashTimersRef.current.set(headingId, timer);
  }, []);

  const scrollToHeading = useCallback(
    (id: string) => {
      const container = scrollElement ?? scrollRef.current;
      if (!container) return;
      const el = container.querySelector(`[data-heading-id="${id}"]`) as HTMLElement | null;
      if (!el) return;

      // Ensure the element has scroll-margin-top so it doesn't stick directly to the very top edge
      if (!el.style.scrollMarginTop) {
        el.style.scrollMarginTop = "24px";
      }

      el.scrollIntoView({ behavior: "smooth", block: "start" });
      flashHeading(el);
    },
    [flashHeading, scrollElement, scrollRef],
  );

  const toggleTocCollapse = useCallback((id: string) => {
    setCollapsedTocIds((prev) => {
      const next = new Set(prev);
      if (next.has(id)) { next.delete(id); } else { next.add(id); }
      return next;
    });
  }, []);

  /* Cleanup flash timers */
  useEffect(() => {
    return () => {
      for (const timer of headingFlashTimersRef.current.values()) {
        window.clearTimeout(timer);
      }
      headingFlashTimersRef.current.clear();
    };
  }, []);

  return {
    toc,
    tocTree,
    activeHeading,
    setActiveHeading,
    activeTocItem,
    collapsedTocIds,
    toggleTocCollapse,
    scrollToHeading,
    tocNavRef,
  };
}
