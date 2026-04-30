/* ------------------------------------------------------------------ */
/*  BuildLiveDraft — Live draft preview with typewriter effect         */
/* ------------------------------------------------------------------ */

import { motion } from "framer-motion";
import { FileEdit } from "lucide-react";
import { cn } from "../../lib/utils";

interface Props {
  excerpt: string;
  chapterTitles: string[];
  className?: string;
}

export function BuildLiveDraft({ excerpt, chapterTitles, className }: Props) {
  if (!excerpt && chapterTitles.length === 0) return null;

  return (
    <div className={cn("space-y-3", className)}>
      <div className="flex items-center gap-2">
        <FileEdit className="w-4 h-4 text-stone-400" />
        <h3 className="text-xs font-semibold uppercase tracking-wider text-stone-500">
          实时草稿
        </h3>
      </div>

      {/* Chapter outline pills */}
      {chapterTitles.length > 0 && (
        <div className="flex flex-wrap gap-1.5">
          {chapterTitles.map((title, index) => (
            <motion.span
              key={title}
              initial={{ opacity: 0, scale: 0.9 }}
              animate={{ opacity: 1, scale: 1 }}
              transition={{ delay: index * 0.06, duration: 0.25 }}
              className="rounded-lg border border-stone-200/70 bg-stone-50/60 px-2.5 py-1 text-xs text-stone-600"
            >
              {title}
            </motion.span>
          ))}
        </div>
      )}

      {/* Draft excerpt */}
      {excerpt && (
        <motion.div
          initial={{ opacity: 0, y: 6 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ duration: 0.4 }}
          className="rounded-xl border border-stone-200/60 bg-gradient-to-br from-stone-50/80 to-white/60 p-4 overflow-hidden"
        >
          <pre className="whitespace-pre-wrap text-[12.5px] leading-[1.8] text-stone-600 font-[var(--font-serif,'Georgia',serif)] max-h-48 overflow-y-auto">
            {excerpt}
            <span className="inline-block w-[2px] h-[14px] bg-indigo-500 ml-0.5 align-middle animate-blink" />
          </pre>
        </motion.div>
      )}
    </div>
  );
}
