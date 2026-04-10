/* ------------------------------------------------------------------ */
/*  DocErrorState — Displayed when document loading or build fails     */
/* ------------------------------------------------------------------ */

import { motion } from "framer-motion";
import { AlertTriangle, RefreshCw } from "lucide-react";
import { cn } from "../../lib/utils";

interface Props {
  message: string;
  onRetry?: () => void;
  className?: string;
}

export function DocErrorState({ message, onRetry, className }: Props) {
  return (
    <motion.div
      initial={{ opacity: 0, y: 12 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.4 }}
      className={cn(
        "flex flex-col items-center justify-center py-16 text-center",
        className,
      )}
    >
      <div className="w-16 h-16 rounded-2xl bg-rose-50 border border-rose-200/60 flex items-center justify-center mb-5">
        <AlertTriangle className="w-7 h-7 text-rose-400" />
      </div>

      <h3 className="text-base font-semibold text-stone-700">
        文档加载失败
      </h3>
      <p className="mt-2 max-w-md text-sm leading-6 text-stone-500">
        {message}
      </p>

      {onRetry && (
        <button
          onClick={onRetry}
          className="mt-6 inline-flex items-center gap-2 rounded-xl border border-stone-200 bg-white px-4 py-2.5 text-sm font-medium text-stone-700 shadow-sm transition-all hover:bg-stone-50 hover:shadow-md active:scale-[0.98]"
        >
          <RefreshCw className="w-4 h-4" />
          重试
        </button>
      )}
    </motion.div>
  );
}
