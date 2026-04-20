import { useState, useEffect, useCallback, useRef } from "react";

interface UseResizablePanelProps {
  defaultWidth?: number | string;
  minWidth?: number;
  maxWidth?: number;
  onResize?: (width: number) => void;
  direction?: "left" | "right";
}

export function useResizablePanel({
  defaultWidth = 420,
  minWidth = 320,
  maxWidth = 800,
  onResize,
  direction = "right",
}: UseResizablePanelProps = {}) {
  const [width, setWidth] = useState<number | string>(defaultWidth);
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
    setWidth(newWidth);
  }, []);

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

      // If maxWidth is a huge number or percentage isn't handled here, we should clamp to max screen
      const maxAllowed = Math.min(maxWidth, window.innerWidth * 0.9);
      newWidth = Math.max(minWidth, Math.min(maxAllowed, newWidth));
      
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
