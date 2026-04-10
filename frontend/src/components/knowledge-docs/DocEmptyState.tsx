/* ------------------------------------------------------------------ */
/*  DocEmptyState — Displayed when no document exists yet              */
/* ------------------------------------------------------------------ */

import { motion } from "framer-motion";
import { BookOpen, Upload } from "lucide-react";
import { cn } from "../../lib/utils";

interface Props {
  className?: string;
}

export function DocEmptyState({ className }: Props) {
  return (
    <motion.div
      initial={{ opacity: 0, y: 16 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.5, ease: "easeOut" }}
      className={cn(
        "flex flex-col items-center justify-center py-20 text-center",
        className,
      )}
    >
      <div className="w-20 h-20 rounded-2xl bg-gradient-to-br from-stone-100 to-stone-50 border border-stone-200/60 flex items-center justify-center mb-6 shadow-sm">
        <BookOpen className="w-8 h-8 text-stone-400" />
      </div>

      <h3 className="text-lg font-semibold text-stone-700 tracking-tight">
        还没有知识文档
      </h3>
      <p className="mt-2 max-w-sm text-sm leading-6 text-stone-500">
        上传你的学习资料后，AI 会自动分析并生成结构化的知识文档，帮助你系统掌握每一个知识点。
      </p>

      <div className="mt-8 flex items-center gap-2 text-xs text-stone-400">
        <Upload className="w-3.5 h-3.5" />
        <span>上传课件、PPT、PDF 开始使用</span>
      </div>
    </motion.div>
  );
}
