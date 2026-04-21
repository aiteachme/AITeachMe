/* ------------------------------------------------------------------ */
/*  BuildResearchSources — Source signals distilled from live events    */
/* ------------------------------------------------------------------ */

import { motion } from "framer-motion";
import { Globe } from "lucide-react";

import { cn } from "../../lib/utils";
import type { BuildPreviewRecentEvent } from "./types";
import { normalizeDomainLabel } from "./utils";

interface Props {
  events: BuildPreviewRecentEvent[];
  className?: string;
}

function uniqueCompact(items: string[]): string[] {
  const seen = new Set<string>();
  const normalized: string[] = [];

  for (const item of items) {
    const value = item.trim();
    if (!value) continue;
    const key = value.toLowerCase();
    if (seen.has(key)) continue;
    seen.add(key);
    normalized.push(value);
  }

  return normalized;
}

export function BuildResearchSources({ events, className }: Props) {
  if (events.length === 0) return null;

  const domainPairs = uniqueCompact(
    events.flatMap((event) => {
      const fromUrls = (event.source_urls ?? []).map((url) => normalizeDomainLabel(url));
      const fromDomains = (event.domains ?? []).map((domain) => normalizeDomainLabel(domain));
      return [...fromUrls, ...fromDomains];
    }),
  ).slice(0, 8);

  const sourceTitles = uniqueCompact(
    events.flatMap((event) => (event.source_titles ?? []).map((title) => String(title ?? "").trim())),
  ).slice(0, 8);

  const fallbackSummaries = uniqueCompact(events.map((event) => event.summary)).slice(0, 6);

  return (
    <section
      className={cn(
        "overflow-hidden rounded-[28px] border border-stone-200/80 bg-white/92 p-4 shadow-[0_20px_60px_-48px_rgba(28,25,23,0.35)] backdrop-blur-sm md:p-5",
        className,
      )}
    >
      <div className="flex items-center justify-between gap-3 border-b border-stone-200/70 pb-3">
        <div>
          <p className="text-[11px] font-semibold uppercase tracking-[0.24em] text-stone-400">Source Signals</p>
          <h3 className="mt-1 text-sm font-semibold text-stone-900">来源信号</h3>
        </div>
        <span className="rounded-full border border-stone-200 bg-stone-50 px-2.5 py-1 text-[11px] text-stone-500">
          {domainPairs.length || sourceTitles.length || fallbackSummaries.length} 条线索
        </span>
      </div>

      <div className="mt-4 space-y-4">
        {domainPairs.length > 0 ? (
          <div>
            <p className="text-[11px] font-medium uppercase tracking-[0.18em] text-stone-400">主要站点</p>
            <div className="mt-2 flex flex-wrap gap-2">
              {domainPairs.map((domain, index) => (
                <motion.span
                  key={domain}
                  initial={{ opacity: 0, scale: 0.92 }}
                  animate={{ opacity: 1, scale: 1 }}
                  transition={{ delay: index * 0.04, duration: 0.22 }}
                  className="inline-flex items-center gap-1.5 rounded-full border border-sky-200/80 bg-sky-50 px-2.5 py-1 text-[11px] text-sky-700"
                >
                  <Globe className="h-3 w-3" />
                  {domain}
                </motion.span>
              ))}
            </div>
          </div>
        ) : null}

        {sourceTitles.length > 0 ? (
          <div>
            <p className="text-[11px] font-medium uppercase tracking-[0.18em] text-stone-400">资料线索</p>
            <div className="mt-2 space-y-2">
              {sourceTitles.map((title, index) => (
                <motion.div
                  key={title}
                  initial={{ opacity: 0, y: 6 }}
                  animate={{ opacity: 1, y: 0 }}
                  transition={{ delay: index * 0.03, duration: 0.2 }}
                  className="rounded-2xl border border-stone-200/80 bg-stone-50/70 px-3 py-2 text-[12px] leading-5 text-stone-600"
                >
                  {title}
                </motion.div>
              ))}
            </div>
          </div>
        ) : null}

        {domainPairs.length === 0 && sourceTitles.length === 0 ? (
          <div>
            <p className="text-[11px] font-medium uppercase tracking-[0.18em] text-stone-400">阶段摘要</p>
            <div className="mt-2 space-y-2">
              {fallbackSummaries.map((summary, index) => (
                <motion.div
                  key={summary}
                  initial={{ opacity: 0, y: 6 }}
                  animate={{ opacity: 1, y: 0 }}
                  transition={{ delay: index * 0.03, duration: 0.2 }}
                  className="rounded-2xl border border-stone-200/80 bg-stone-50/70 px-3 py-2 text-[12px] leading-5 text-stone-600"
                >
                  {summary}
                </motion.div>
              ))}
            </div>
          </div>
        ) : null}

        <p className="text-[11px] leading-5 text-stone-400">
          这里只展示最近事件里已经暴露出来的来源信号，不代表本轮构建使用到的全部证据。
        </p>
      </div>
    </section>
  );
}
