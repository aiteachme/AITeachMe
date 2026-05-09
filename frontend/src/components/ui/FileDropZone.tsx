import { useRef, useState, type DragEvent } from "react";
import { FileUp } from "lucide-react";

interface FileDropOverlayProps {
  title?: string;
  description?: string;
}

export function FileDropOverlay({
  title = "松手添加资料",
  description = "会上传到资料库并加入当前草稿",
}: FileDropOverlayProps) {
  return (
    <div className="pointer-events-none absolute inset-0 z-20 flex items-center justify-center bg-white/90 backdrop-blur-[2px] dark:bg-slate-950/86">
      <div className="flex flex-col items-center rounded-2xl border border-dashed border-zinc-300 bg-white px-7 py-5 text-center shadow-[0_18px_48px_-24px_rgba(24,24,27,0.38),0_6px_18px_-10px_rgba(24,24,27,0.22)] dark:border-slate-700 dark:bg-slate-900 dark:shadow-black/35">
        <FileUp className="h-7 w-7 text-zinc-700 dark:text-slate-200" />
        <p className="mt-2 text-sm font-semibold text-zinc-900 dark:text-slate-100">{title}</p>
        <p className="mt-1 text-xs text-zinc-500 dark:text-slate-400">{description}</p>
      </div>
    </div>
  );
}

interface UseFileDropZoneOptions {
  disabled?: boolean;
  onDropFiles?: (files: File[]) => void;
}

export function useFileDropZone<TElement extends HTMLElement = HTMLElement>({
  disabled = false,
  onDropFiles,
}: UseFileDropZoneOptions) {
  const dragDepthRef = useRef(0);
  const [isDragActive, setIsDragActive] = useState(false);

  const eventHasFiles = (event: DragEvent<TElement>) =>
    Array.from(event.dataTransfer.types ?? []).includes("Files");

  const handleDragEnter = (event: DragEvent<TElement>) => {
    if (!onDropFiles || !eventHasFiles(event)) return;
    event.preventDefault();
    dragDepthRef.current += 1;
    event.dataTransfer.dropEffect = disabled ? "none" : "copy";
    if (!disabled) {
      setIsDragActive(true);
    }
  };

  const handleDragOver = (event: DragEvent<TElement>) => {
    if (!onDropFiles || !eventHasFiles(event)) return;
    event.preventDefault();
    event.dataTransfer.dropEffect = disabled ? "none" : "copy";
  };

  const handleDragLeave = (event: DragEvent<TElement>) => {
    if (!onDropFiles || !eventHasFiles(event)) return;
    event.preventDefault();
    dragDepthRef.current = Math.max(0, dragDepthRef.current - 1);
    if (dragDepthRef.current === 0) {
      setIsDragActive(false);
    }
  };

  const handleDrop = (event: DragEvent<TElement>) => {
    if (!onDropFiles || !eventHasFiles(event)) return;
    event.preventDefault();
    dragDepthRef.current = 0;
    setIsDragActive(false);
    if (disabled) return;
    const droppedFiles = Array.from(event.dataTransfer.files ?? []);
    if (droppedFiles.length > 0) {
      onDropFiles(droppedFiles);
    }
  };

  return {
    isDragActive,
    dropZoneHandlers: onDropFiles
      ? {
          onDragEnter: handleDragEnter,
          onDragOver: handleDragOver,
          onDragLeave: handleDragLeave,
          onDrop: handleDrop,
        }
      : {},
  };
}
