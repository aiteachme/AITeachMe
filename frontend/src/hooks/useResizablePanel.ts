import { useState, useEffect, useCallback, useRef } from "react";

interface UseResizablePanelProps {
  defaultWidth?: number | string;
  minWidth?: number;
  maxWidth?: number;
  onResize?: (width: number) => void;
  direction?: "left" | "right";
}

function clampPanelWidth(width: number, minWidth: number, maxWidth: number) {
  if (typeof window === "undefined") {
    return Math.max(minWidth, Math.min(maxWidth, width));
  }

  const viewportWidth = window.innerWidth;
  const maxAllowed = Math.min(maxWidth, viewportWidth);
  const minAllowed = Math.min(minWidth, maxAllowed);

  return Math.max(minAllowed, Math.min(maxAllowed, width));
}

export function useResizablePanel({
  defaultWidth = 420,
  minWidth = 320,
  maxWidth = 800,
  onResize,
  direction = "right",
}: UseResizablePanelProps = {}) {
  const [width, setWidth] = useState<number | string>(() =>
    typeof defaultWidth === "number"
      ? clampPanelWidth(defaultWidth, minWidth, maxWidth)
      : defaultWidth,
  );
  const [isDragging, setIsDragging] = useState(false);
  const isDraggingRef = useRef(isDragging);

  useEffect(() => {
    isDraggingRef.current = isDragging;
  }, [isDragging]);

  const handleMouseDown = useCallback((e: React.MouseEvent) => {
    e.preventDefault();
    setIsDragging(true);
  }, []);

  const resetWidth = useCallback((newWidth: number | string) => {
    setWidth(
      typeof newWidth === "number"
        ? clampPanelWidth(newWidth, minWidth, maxWidth)
        : newWidth,
    );
  }, [maxWidth, minWidth]);

  useEffect(() => {
    if (typeof window === "undefined") return;

    const handleResize = () => {
      setWidth((current) =>
        typeof current === "number"
          ? clampPanelWidth(current, minWidth, maxWidth)
          : current,
      );
    };

    window.addEventListener("resize", handleResize);
    return () => window.removeEventListener("resize", handleResize);
  }, [maxWidth, minWidth]);

  useEffect(() => {
    if (!isDragging) return;

    const handleMouseMove = (e: MouseEvent) => {
      let newWidth;
      
      if (direction === "right") {
        // If the panel is anchored to the right, growing it means moving the left edge to the left
        newWidth = window.innerWidth - e.clientX;
      } else {
        // If anchored to left, growing it means moving the right edge to the right
        newWidth = e.clientX;
      }

      newWidth = clampPanelWidth(newWidth, minWidth, maxWidth);
      
      setWidth(newWidth);
      onResize?.(newWidth);
    };

    const handleMouseUp = () => {
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
      document.removeEventListener("mousemove", handleMouseMove);
      document.removeEventListener("mouseup", handleMouseUp);
    };
  }, [isDragging, minWidth, maxWidth, onResize, direction]);

  return {
    width,
    isDragging,
    handleMouseDown,
    resetWidth,
  };
}
