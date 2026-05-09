import { useState, useEffect, useCallback, useRef, type RefObject } from "react";

interface UseResizablePanelProps {
  defaultWidth?: number | string;
  minWidth?: number;
  maxWidth?: number;
  onResize?: (width: number) => void;
  onDragBeyondMin?: () => void;
  onDragBeyondMax?: () => void;
  boundaryActionThreshold?: number;
  direction?: "left" | "right";
  liveResizeRef?: RefObject<HTMLElement | null>;
  liveResizeEnabled?: boolean;
  dragGuideRef?: RefObject<HTMLElement | null>;
  commitResizeOnDragEnd?: boolean;
}

function getPanelWidthBounds(minWidth: number, maxWidth: number) {
  if (typeof window === "undefined") {
    return { minAllowed: minWidth, maxAllowed: maxWidth };
  }

  const viewportWidth = window.innerWidth;
  const maxAllowed = Math.min(maxWidth, viewportWidth);
  const minAllowed = Math.min(minWidth, maxAllowed);

  return { minAllowed, maxAllowed };
}

function clampPanelWidth(width: number, minWidth: number, maxWidth: number) {
  const { minAllowed, maxAllowed } = getPanelWidthBounds(minWidth, maxWidth);
  return Math.max(minAllowed, Math.min(maxAllowed, width));
}

export function useResizablePanel({
  defaultWidth = 420,
  minWidth = 320,
  maxWidth = 800,
  onResize,
  onDragBeyondMin,
  onDragBeyondMax,
  boundaryActionThreshold = 64,
  direction = "right",
  liveResizeRef,
  liveResizeEnabled = true,
  dragGuideRef,
  commitResizeOnDragEnd = false,
}: UseResizablePanelProps = {}) {
  const [width, setWidth] = useState<number | string>(() =>
    typeof defaultWidth === "number"
      ? clampPanelWidth(defaultWidth, minWidth, maxWidth)
      : defaultWidth,
  );
  const [isDragging, setIsDragging] = useState(false);
  const isDraggingRef = useRef(isDragging);
  const widthRef = useRef<number | string>(width);
  const pendingWidthRef = useRef<number | null>(null);
  const frameRef = useRef<number | null>(null);
  const boundaryActionTriggeredRef = useRef(false);

  useEffect(() => {
    isDraggingRef.current = isDragging;
  }, [isDragging]);

  useEffect(() => {
    widthRef.current = width;
  }, [width]);

  const applyLiveWidth = useCallback((nextWidth: number) => {
    if (!liveResizeEnabled) {
      return;
    }

    const element = liveResizeRef?.current;
    if (element) {
      element.style.width = `${nextWidth}px`;
    }
  }, [liveResizeEnabled, liveResizeRef]);

  const positionDragGuide = useCallback((nextWidth: number) => {
    const guide = dragGuideRef?.current;
    if (!guide || typeof window === "undefined") {
      return;
    }

    const positionX = direction === "right"
      ? window.innerWidth - nextWidth
      : nextWidth;
    guide.style.display = "block";
    guide.style.transform = `translate3d(${Math.round(positionX)}px, 0, 0)`;
  }, [direction, dragGuideRef]);

  const hideDragGuide = useCallback(() => {
    const guide = dragGuideRef?.current;
    if (!guide) {
      return;
    }

    guide.style.display = "none";
  }, [dragGuideRef]);

  const handleMouseDown = useCallback((e: React.MouseEvent) => {
    e.preventDefault();
    pendingWidthRef.current = null;
    boundaryActionTriggeredRef.current = false;

    if (liveResizeRef?.current && typeof widthRef.current !== "number") {
      const measuredWidth = liveResizeRef.current.getBoundingClientRect().width;
      widthRef.current = clampPanelWidth(measuredWidth, minWidth, maxWidth);
    }

    if (commitResizeOnDragEnd && typeof widthRef.current === "number") {
      positionDragGuide(widthRef.current);
    }

    setIsDragging(true);
  }, [commitResizeOnDragEnd, liveResizeRef, maxWidth, minWidth, positionDragGuide]);

  const resetWidth = useCallback((newWidth: number | string) => {
    const nextWidth = typeof newWidth === "number"
      ? clampPanelWidth(newWidth, minWidth, maxWidth)
      : newWidth;

    widthRef.current = nextWidth;
    if (typeof nextWidth === "number") {
      applyLiveWidth(nextWidth);
    }
    setWidth(nextWidth);
  }, [applyLiveWidth, maxWidth, minWidth]);

  useEffect(() => {
    if (typeof window === "undefined") return;

    const handleResize = () => {
      setWidth((current) => {
        if (typeof current !== "number") {
          return current;
        }

        const nextWidth = clampPanelWidth(current, minWidth, maxWidth);
        widthRef.current = nextWidth;
        applyLiveWidth(nextWidth);
        return nextWidth;
      });
    };

    window.addEventListener("resize", handleResize);
    return () => window.removeEventListener("resize", handleResize);
  }, [applyLiveWidth, maxWidth, minWidth]);

  useEffect(() => {
    if (!isDragging) return;

    const flushWidth = (nextWidth: number, shouldCommit: boolean) => {
      if (commitResizeOnDragEnd && !shouldCommit) {
        positionDragGuide(nextWidth);
        pendingWidthRef.current = nextWidth;
        return;
      }

      if (liveResizeRef?.current) {
        applyLiveWidth(nextWidth);
        if (shouldCommit) {
          setWidth(nextWidth);
        }
      } else {
        setWidth(nextWidth);
      }
      widthRef.current = nextWidth;
      onResize?.(nextWidth);
    };

    const scheduleWidth = (nextWidth: number) => {
      pendingWidthRef.current = nextWidth;
      if (frameRef.current !== null) {
        return;
      }

      frameRef.current = window.requestAnimationFrame(() => {
        frameRef.current = null;
        const queuedWidth = pendingWidthRef.current;
        if (queuedWidth === null) {
          return;
        }

        flushWidth(queuedWidth, false);
      });
    };

    const handleMouseMove = (e: MouseEvent) => {
      let newWidth;
      
      if (direction === "right") {
        // If the panel is anchored to the right, growing it means moving the left edge to the left
        newWidth = window.innerWidth - e.clientX;
      } else {
        // If anchored to left, growing it means moving the right edge to the right
        newWidth = e.clientX;
      }

      if (!boundaryActionTriggeredRef.current) {
        const { minAllowed, maxAllowed } = getPanelWidthBounds(minWidth, maxWidth);
        const triggerOffset = Math.max(0, boundaryActionThreshold);
        if (newWidth >= maxAllowed + triggerOffset) {
          boundaryActionTriggeredRef.current = true;
          onDragBeyondMax?.();
        } else if (newWidth <= minAllowed - triggerOffset) {
          boundaryActionTriggeredRef.current = true;
          onDragBeyondMin?.();
        }
      }

      newWidth = clampPanelWidth(newWidth, minWidth, maxWidth);
      scheduleWidth(newWidth);
    };

    const handleMouseUp = () => {
      if (frameRef.current !== null) {
        window.cancelAnimationFrame(frameRef.current);
        frameRef.current = null;
      }

      const finalWidth = pendingWidthRef.current;
      if (finalWidth !== null) {
        flushWidth(finalWidth, true);
        pendingWidthRef.current = null;
      }

      hideDragGuide();
      setIsDragging(false);
    };

    // Add styles to prevent selecting text or losing cursor during drag
    document.body.style.userSelect = "none";
    document.body.style.cursor = "col-resize";

    document.addEventListener("mousemove", handleMouseMove);
    document.addEventListener("mouseup", handleMouseUp);

    return () => {
      document.body.style.userSelect = "";
      document.body.style.cursor = "";
      hideDragGuide();
      if (frameRef.current !== null) {
        window.cancelAnimationFrame(frameRef.current);
        frameRef.current = null;
      }
      document.removeEventListener("mousemove", handleMouseMove);
      document.removeEventListener("mouseup", handleMouseUp);
    };
  }, [
    applyLiveWidth,
    commitResizeOnDragEnd,
    direction,
    hideDragGuide,
    isDragging,
    liveResizeRef,
    maxWidth,
    minWidth,
    boundaryActionThreshold,
    onDragBeyondMax,
    onDragBeyondMin,
    onResize,
    positionDragGuide,
  ]);

  return {
    width,
    isDragging,
    handleMouseDown,
    resetWidth,
  };
}
