import { useEffect, useState } from "react";
import { createPortal } from "react-dom";
import { AnimatePresence, motion } from "framer-motion";
import { FileUp, FileText, FileImage, FileSpreadsheet } from "lucide-react";

interface FullPageDropOverlayProps {
  /** 接受的 MIME 类型或扩展名（仅做视觉提示） */
  acceptHint?: string;
  /** 文件拖放回调 */
  onDrop: (files: File[]) => void;
  /** 是否禁用 */
  disabled?: boolean;
}

/**
 * 全页面拖拽上传浮层
 *
 * 恢复最初的精美动态样式，同时保留了彻底解决性能卡顿和覆盖层级问题的底层修复。
 */
export function FullPageDropOverlay({
  acceptHint = "PDF / DOCX / PPT / Markdown / 图片",
  onDrop,
  disabled = false,
}: FullPageDropOverlayProps) {
  const [isDragging, setIsDragging] = useState(false);

  useEffect(() => {
    if (disabled) return;

    let dragCounter = 0;

    const handleDragEnter = (e: globalThis.DragEvent) => {
      e.preventDefault();
      if (e.dataTransfer?.types.includes("Files")) {
        dragCounter++;
        setIsDragging(true);
      }
    };

    const handleDragLeave = (e: globalThis.DragEvent) => {
      e.preventDefault();
      dragCounter--;
      if (dragCounter <= 0) {
        dragCounter = 0;
        setIsDragging(false);
      }
    };

    const handleDragOver = (e: globalThis.DragEvent) => {
      e.preventDefault();
      if (e.dataTransfer) {
        e.dataTransfer.dropEffect = "copy";
      }
    };

    const handleDrop = (e: globalThis.DragEvent) => {
      e.preventDefault();
      e.stopPropagation();
      dragCounter = 0;
      setIsDragging(false);

      if (e.dataTransfer?.files && e.dataTransfer.files.length > 0) {
        const files = Array.from(e.dataTransfer.files);
        onDrop(files);
      }
    };

    window.addEventListener("dragenter", handleDragEnter);
    window.addEventListener("dragleave", handleDragLeave);
    window.addEventListener("dragover", handleDragOver);
    window.addEventListener("drop", handleDrop);

    return () => {
      window.removeEventListener("dragenter", handleDragEnter);
      window.removeEventListener("dragleave", handleDragLeave);
      window.removeEventListener("dragover", handleDragOver);
      window.removeEventListener("drop", handleDrop);
    };
  }, [disabled, onDrop]);

  /* 四个浮动小图标的配置 */
  const floatingIcons = [
    { Icon: FileText, delay: 0, x: -90, y: -70, rotate: -12, color: "text-blue-300" },
    { Icon: FileImage, delay: 0.08, x: 85, y: -60, rotate: 10, color: "text-emerald-300" },
    { Icon: FileSpreadsheet, delay: 0.12, x: -80, y: 55, rotate: 8, color: "text-amber-300" },
    { Icon: FileUp, delay: 0.16, x: 90, y: 65, rotate: -6, color: "text-violet-300" },
  ];

  const overlayContent = (
    <AnimatePresence>
      {isDragging && (
        <motion.div
          key="full-page-drop-overlay"
          initial={{ opacity: 0 }}
          animate={{ opacity: 1 }}
          exit={{ opacity: 0 }}
          transition={{ duration: 0.12, ease: "easeOut" }}
          // 关键：pointer-events-none 彻底防止事件闪烁和卡顿
          className="fixed inset-0 z-[99999] flex items-center justify-center pointer-events-none"
        >
          {/* 毛玻璃背景（修复了之前无效的 Tailwind class 导致透明的问题） */}
          <div className="absolute inset-0 bg-slate-900/70 backdrop-blur-md" />

          {/* 中心卡片 */}
          <motion.div
            initial={{ y: 8, opacity: 0 }}
            animate={{ y: 0, opacity: 1 }}
            exit={{ y: 4, opacity: 0 }}
            transition={{ duration: 0.16, ease: [0.16, 1, 0.3, 1] }}
            className="relative flex flex-col items-center gap-5 rounded-3xl border-2 border-dashed border-white/40 bg-white/10 px-20 py-16 shadow-[0_20px_48px_-24px_rgba(15,23,42,0.45)]"
          >
            {/* 浮动文件类型图标 */}
            {floatingIcons.map(({ Icon, delay, x, y, rotate, color }, i) => (
              <motion.div
                key={i}
                initial={{ opacity: 0, scale: 0, x: 0, y: 0, rotate: 0 }}
                animate={{ opacity: 0.8, scale: 1, x, y, rotate }}
                exit={{ opacity: 0, scale: 0 }}
                transition={{ delay, duration: 0.4, ease: [0.16, 1, 0.3, 1] }}
                className="absolute"
              >
                <Icon className={`h-8 w-8 ${color} drop-shadow-lg`} strokeWidth={1.5} />
              </motion.div>
            ))}

            {/* 主图标 */}
            <motion.div
              animate={{ y: [0, -4, 0] }}
              transition={{ repeat: Infinity, duration: 2.4, ease: "easeInOut" }}
              className="flex h-24 w-24 items-center justify-center rounded-full bg-gradient-to-br from-white/30 to-white/12 ring-1 ring-white/20"
            >
              <FileUp className="h-12 w-12 text-white drop-shadow-md" strokeWidth={1.5} />
            </motion.div>

            {/* 文字 */}
            <div className="text-center">
              <p className="text-2xl font-bold text-white drop-shadow-sm">
                松开即可上传
              </p>
              <p className="mt-2 text-sm text-white/60">
                支持 {acceptHint}
              </p>
            </div>

            {/* 外层脉冲光圈 */}
            <motion.div
              animate={{ opacity: [0.22, 0.4, 0.22] }}
              transition={{ repeat: Infinity, duration: 2.8, ease: "easeInOut" }}
              className="absolute -inset-4 rounded-[2rem] border border-white/20"
            />
          </motion.div>
        </motion.div>
      )}
    </AnimatePresence>
  );

  // 使用 Portal 将蒙版挂载到 document.body，确保不受任何父元素的 stacking context 影响
  return createPortal(overlayContent, document.body);
}
