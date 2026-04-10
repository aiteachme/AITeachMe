/* ------------------------------------------------------------------ */
/*  BuildMetricsBadges — LLM metrics display as pill badges            */
/* ------------------------------------------------------------------ */

import { Activity, Cpu, Zap, Clock } from "lucide-react";
import { motion } from "framer-motion";
import { cn } from "../../lib/utils";
import type { KnowledgeBuildMetrics, KnowledgeBuildPreview } from "./types";

interface Props {
  metrics: KnowledgeBuildMetrics | null;
  preview: KnowledgeBuildPreview | null;
  className?: string;
}

function formatLatency(ms: number | undefined): string | null {
  if (!ms || ms <= 0) return null;
  return ms < 1000 ? `${Math.round(ms)}ms` : `${(ms / 1000).toFixed(1)}s`;
}

export function BuildMetricsBadges({ metrics, preview, className }: Props) {
  if (!metrics && !preview) return null;

  const items: Array<{ icon: typeof Activity; label: string; value: string }> = [];

  const throughput = (preview?.total_chunks ?? 0) > 0
    ? `${preview?.processed_chunks ?? 0}/${preview?.total_chunks ?? 0}`
    : null;
  if (throughput) {
    items.push({ icon: Activity, label: "分片", value: throughput });
  }

  const nodeCount = preview?.discovered_node_count;
  if (nodeCount && nodeCount > 0) {
    items.push({ icon: Zap, label: "节点", value: String(nodeCount) });
  }

  const llmCalls = metrics?.llm_total_calls;
  if (llmCalls && llmCalls > 0) {
    items.push({ icon: Cpu, label: "模型调用", value: String(llmCalls) });
  }

  const latency = formatLatency(metrics?.llm_avg_latency_ms);
  if (latency) {
    items.push({ icon: Clock, label: "平均延迟", value: latency });
  }

  if (items.length === 0) return null;

  return (
    <div className={cn("flex flex-wrap gap-2", className)}>
      {items.map((item, index) => (
        <motion.div
          key={item.label}
          initial={{ opacity: 0, scale: 0.9 }}
          animate={{ opacity: 1, scale: 1 }}
          transition={{ delay: index * 0.06, duration: 0.25 }}
          className="inline-flex items-center gap-1.5 rounded-lg border border-stone-200/80 bg-white/80 px-2.5 py-1.5 text-[11px] text-stone-600 backdrop-blur-sm"
        >
          <item.icon className="w-3 h-3 text-stone-400" />
          <span className="text-stone-400">{item.label}</span>
          <span className="font-medium text-stone-700">{item.value}</span>
        </motion.div>
      ))}
    </div>
  );
}
