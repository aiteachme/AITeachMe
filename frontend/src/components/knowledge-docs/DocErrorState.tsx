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
      className={cn("flex flex-col items-center justify-center py-16 text-center", className)}
    >
      <div className="mb-5 flex h-16 w-16 items-center justify-center rounded-2xl border border-rose-200/60 bg-rose-50 dark:border-rose-500/20 dark:bg-rose-500/10">
        <AlertTriangle className="h-7 w-7 text-rose-400 dark:text-rose-300" />
      </div>

      <h3 className="text-base font-semibold text-stone-700 dark:text-slate-100">文档加载失败</h3>
      <p className="mt-2 max-w-md text-sm leading-6 text-stone-500 dark:text-slate-400">
        {message}
      </p>

      {onRetry ? (
        <button
          type="button"
          onClick={onRetry}
          className="mt-6 inline-flex items-center gap-2 rounded-xl border border-stone-200 bg-white px-4 py-2.5 text-sm font-medium text-stone-700 shadow-sm transition-all hover:bg-stone-50 hover:shadow-md active:scale-[0.98] dark:border-slate-700 dark:bg-slate-900 dark:text-slate-200 dark:hover:bg-slate-800"
        >
          <RefreshCw className="h-4 w-4" />
          重试
        </button>
      ) : null}
    </motion.div>
  );
}
