import { motion } from "framer-motion";

import { cn } from "../../lib/utils";

interface Props {
  title: string;
  summary: string;
  digestModeLabel: string;
  docViewLabel: string;
  updatedLabel: string | null;
  llmCalls: number | null;
  chapterHighlights: string[];
  className?: string;
}

export function DocHeader({
  title,
  summary,
  digestModeLabel,
  docViewLabel,
  updatedLabel,
  llmCalls,
  chapterHighlights,
  className,
}: Props) {
  return (
    <motion.div
      initial={{ opacity: 0, y: 8 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.35, ease: "easeOut" }}
      className={cn(
        "border-b border-[#DEE0E3] bg-white px-6 py-5 md:px-10 md:py-6 dark:border-slate-800 dark:bg-slate-950/95",
        className,
      )}
    >
      <div className="flex flex-wrap items-center gap-1.5 text-[12px]">
        <span className="rounded-md bg-[#F5F6F7] px-2 py-0.5 font-medium text-[#1F2329] dark:bg-slate-800 dark:text-slate-100">
          {docViewLabel}
        </span>
        <span className="rounded-md bg-[#F5F6F7] px-2 py-0.5 text-[#646A73] dark:bg-slate-800 dark:text-slate-300">
          {digestModeLabel}
        </span>
        {updatedLabel ? (
          <span className="rounded-md bg-[#F5F6F7] px-2 py-0.5 text-[#8F959E] dark:bg-slate-800 dark:text-slate-400">
            更新于 {updatedLabel}
          </span>
        ) : null}
        {llmCalls && llmCalls > 0 ? (
          <span className="rounded-md bg-[#F5F6F7] px-2 py-0.5 text-[#8F959E] dark:bg-slate-800 dark:text-slate-400">
            {llmCalls} 次模型调用
          </span>
        ) : null}
      </div>

      <motion.h1
        initial={{ opacity: 0 }}
        animate={{ opacity: 1 }}
        transition={{ delay: 0.08, duration: 0.3 }}
        className="mt-3 text-[26px] font-semibold leading-[1.35] tracking-[-0.02em] text-[#1F2329] dark:text-slate-100"
      >
        {title}
      </motion.h1>

      {summary ? (
        <motion.p
          initial={{ opacity: 0 }}
          animate={{ opacity: 1 }}
          transition={{ delay: 0.15, duration: 0.3 }}
          className="mt-2 max-w-3xl text-[14px] leading-[1.7] text-[#646A73] dark:text-slate-400"
        >
          {summary}
        </motion.p>
      ) : null}

      {chapterHighlights.length > 0 ? (
        <motion.div
          initial={{ opacity: 0 }}
          animate={{ opacity: 1 }}
          transition={{ delay: 0.22, duration: 0.25 }}
          className="mt-3 flex flex-wrap gap-1.5"
        >
          {chapterHighlights.map((titleItem) => (
            <span
              key={titleItem}
              className="rounded-md bg-[#F5F6F7] px-2 py-0.5 text-[12px] text-[#646A73] dark:bg-slate-800 dark:text-slate-300"
            >
              {titleItem}
            </span>
          ))}
        </motion.div>
      ) : null}
    </motion.div>
  );
}
