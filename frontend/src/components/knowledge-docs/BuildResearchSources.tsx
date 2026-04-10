/* ------------------------------------------------------------------ */
/*  BuildResearchSources — Compact research event list                 */
/* ------------------------------------------------------------------ */

import { motion, AnimatePresence } from "framer-motion";
import { Globe } from "lucide-react";
import { cn } from "../../lib/utils";
import type { BuildPreviewRecentEvent } from "./types";
import { normalizeDomainLabel, formatBuildEventTime } from "./utils";

interface Props {
  events: BuildPreviewRecentEvent[];
  className?: string;
}

export function BuildResearchSources({ events, className }: Props) {
  if (events.length === 0) return null;

  return (
    <div className={cn("space-y-2", className)}>
      <p className="text-[10px] font-semibold uppercase tracking-widest text-stone-400">
        检索来源 · {events.length}
      </p>

      <div className="space-y-1">
        <AnimatePresence mode="popLayout">
          {events.slice(0, 10).map((event, index) => {
            const domains = event.domains ?? [];
            const urls = event.source_urls ?? [];
            const time = formatBuildEventTime(event.created_at);

            return (
              <motion.div
                key={`${event.stage}-${event.chapter_index ?? ""}-${index}`}
                initial={{ opacity: 0, y: 4 }}
                animate={{ opacity: 1, y: 0 }}
                exit={{ opacity: 0 }}
                transition={{ delay: index * 0.02, duration: 0.2 }}
                className="flex items-start gap-2 rounded-lg px-2.5 py-1.5 text-[12px] hover:bg-stone-50 transition-colors"
              >
                <Globe className="w-3 h-3 text-stone-300 shrink-0 mt-0.5" />
                <div className="flex-1 min-w-0">
                  <p className="text-stone-600 leading-5 line-clamp-1">{event.summary}</p>
                  {domains.length > 0 && (
                    <div className="flex flex-wrap gap-1 mt-0.5">
                      {domains.slice(0, 3).map((domain: string, di: number) => {
                        const url = urls[di];
                        const label = normalizeDomainLabel(url || domain);
                        const Tag = url ? "a" : "span";
                        return (
                          <Tag
                            key={`${domain}-${di}`}
                            {...(url ? { href: url, target: "_blank", rel: "noopener noreferrer" } : {})}
                            className="text-[10px] text-stone-400 hover:text-sky-600 transition-colors"
                          >
                            {label}
                          </Tag>
                        );
                      })}
                    </div>
                  )}
                </div>
                {time && <span className="text-[10px] text-stone-300 shrink-0">{time}</span>}
              </motion.div>
            );
          })}
        </AnimatePresence>
      </div>
    </div>
  );
}
