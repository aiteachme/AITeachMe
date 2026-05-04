import { Fragment, useMemo, useState } from "react";

import type { GraphInsightModel, SankeyLink } from "./insightsCore";
import {
  LEARNING_LAYERS,
  buildSankeyLayout,
  percentText,
} from "./insightsCore";
import { ChartPanel, CategoryBar } from "./sharedPrimitives";

function sankeyLinkPath(link: SankeyLink, sourceX: number, targetX: number): string {
  const curvature = 0.45;
  const x0 = sourceX;
  const x1 = targetX;
  const cx0 = x0 + (x1 - x0) * curvature;
  const cx1 = x1 - (x1 - x0) * curvature;
  return `M ${x0.toFixed(1)} ${link.sourceY.toFixed(1)} C ${cx0.toFixed(1)} ${link.sourceY.toFixed(1)} ${cx1.toFixed(1)} ${link.targetY.toFixed(1)} ${x1.toFixed(1)} ${link.targetY.toFixed(1)}`;
}

export function FlowSankeyView({ model }: { model: GraphInsightModel }) {
  const width = 1180;
  const height = 520;
  const layout = useMemo(() => buildSankeyLayout(model, width, height), [model]);
  const [hoveredLink, setHoveredLink] = useState<SankeyLink | null>(null);
  const [hoveredLayer, setHoveredLayer] = useState<number | null>(null);

  const totalCrossLayer = useMemo(
    () => layout.links.reduce((sum, link) => sum + link.count, 0),
    [layout.links],
  );
  const selfLoopTotal = useMemo(() => layout.nodes.reduce((sum, node) => sum + node.selfLoop, 0), [layout.nodes]);

  // Forward flow heuristics: links where source < target.
  const forwardCount = useMemo(
    () => layout.links.reduce((sum, link) => sum + (link.targetLayer > link.sourceLayer ? link.count : 0), 0),
    [layout.links],
  );
  const backwardCount = useMemo(
    () => layout.links.reduce((sum, link) => sum + (link.targetLayer < link.sourceLayer ? link.count : 0), 0),
    [layout.links],
  );

  const dominantLink = useMemo(() => {
    if (!layout.links.length) return null;
    return [...layout.links].sort((left, right) => right.count - left.count)[0];
  }, [layout.links]);

  // Path completeness: how many ordered (n -> n+1) transitions exist with > 0 count.
  const consecutivePresence = useMemo(() => {
    const present: boolean[] = LEARNING_LAYERS.slice(0, -1).map((_, idx) => {
      return layout.links.some((link) => link.sourceLayer === idx && link.targetLayer === idx + 1 && link.count > 0);
    });
    return present;
  }, [layout.links]);

  const completedPath = consecutivePresence.every(Boolean);
  const completedCount = consecutivePresence.filter(Boolean).length;

  const relationLegend = useMemo(() => model.relationItems.slice(0, 8), [model.relationItems]);

  return (
    <div className="grid gap-4">
      <ChartPanel
        title="学习路径桑基图"
        meta={`跨层 ${totalCrossLayer} · 自环 ${selfLoopTotal}`}
        description="知识从「组织 → 知识 → 原理 → 方法 → 训练」流动的真实数量。流越粗、教学路径越通畅；颜色代表主导关系类型。"
      >
        <div className="relative h-[540px] bg-gradient-to-b from-slate-50 to-white dark:from-slate-950 dark:to-slate-900">
          <svg viewBox={`0 0 ${width} ${height}`} className="h-full w-full" role="img" aria-label="学习路径桑基图">
            <defs>
              {layout.links.map((link, idx) => (
                <linearGradient
                  key={`grad-${idx}`}
                  id={`sankey-grad-${idx}`}
                  gradientUnits="userSpaceOnUse"
                  x1={layout.nodes[link.sourceLayer].x + layout.nodes[link.sourceLayer].width}
                  x2={layout.nodes[link.targetLayer].x}
                  y1="0"
                  y2="0"
                >
                  <stop offset="0%" stopColor={layout.nodes[link.sourceLayer].color} stopOpacity="0.85" />
                  <stop offset="100%" stopColor={layout.nodes[link.targetLayer].color} stopOpacity="0.85" />
                </linearGradient>
              ))}
            </defs>

            {/* Layer guidelines */}
            {layout.nodes.map((node) => (
              <line
                key={`guide-${node.layer}`}
                x1={node.x + node.width / 2}
                x2={node.x + node.width / 2}
                y1="20"
                y2={height - 20}
                stroke="#e2e8f0"
                strokeWidth="1"
                strokeDasharray="2 4"
                opacity="0.5"
              />
            ))}

            {/* Links - render largest first so smaller layer */}
            <g>
              {[...layout.links]
                .sort((left, right) => right.count - left.count)
                .map((link) => {
                  const sourceNode = layout.nodes[link.sourceLayer];
                  const targetNode = layout.nodes[link.targetLayer];
                  if (!sourceNode || !targetNode) return null;
                  const linkIdx = layout.links.indexOf(link);
                  const sourceX = sourceNode.x + sourceNode.width;
                  const targetX = targetNode.x;
                  const isHovered = hoveredLink === link;
                  const isLayerHovered =
                    hoveredLayer !== null &&
                    (link.sourceLayer === hoveredLayer || link.targetLayer === hoveredLayer);
                  const dimmed = (hoveredLink && !isHovered) || (hoveredLayer !== null && !isLayerHovered);
                  return (
                    <path
                      key={`link-${link.sourceLayer}-${link.targetLayer}`}
                      d={sankeyLinkPath(link, sourceX, targetX)}
                      fill="none"
                      stroke={`url(#sankey-grad-${linkIdx})`}
                      strokeWidth={Math.max(2, link.width)}
                      strokeOpacity={dimmed ? 0.08 : isHovered ? 0.95 : 0.55}
                      onMouseEnter={() => setHoveredLink(link)}
                      onMouseLeave={() => setHoveredLink(null)}
                      style={{ cursor: "pointer" }}
                    />
                  );
                })}
            </g>

            {/* Self-loops as small arcs above the node bar */}
            <g>
              {layout.nodes.map((node) => {
                if (!node.selfLoop) return null;
                const cx = node.x + node.width / 2;
                const arcSize = 24 + Math.min(50, node.selfLoop * 1.2);
                return (
                  <g key={`self-${node.layer}`}>
                    <path
                      d={`M ${cx - 16} ${node.y - 4} Q ${cx} ${node.y - arcSize} ${cx + 16} ${node.y - 4}`}
                      fill="none"
                      stroke={node.color}
                      strokeWidth={Math.min(8, 2 + node.selfLoop / 4)}
                      strokeOpacity="0.55"
                      strokeLinecap="round"
                    />
                    <text
                      x={cx}
                      y={node.y - arcSize - 4}
                      textAnchor="middle"
                      fontSize="11"
                      fontWeight="700"
                      fill={node.color}
                    >
                      ↻ {node.selfLoop}
                    </text>
                  </g>
                );
              })}
            </g>

            {/* Layer node bars */}
            <g>
              {layout.nodes.map((node) => {
                const isHovered = hoveredLayer === node.layer;
                return (
                  <g
                    key={`node-${node.layer}`}
                    onMouseEnter={() => setHoveredLayer(node.layer)}
                    onMouseLeave={() => setHoveredLayer(null)}
                    style={{ cursor: "pointer" }}
                  >
                    <rect
                      x={node.x}
                      y={node.y}
                      width={node.width}
                      height={node.height}
                      rx={4}
                      fill={node.color}
                      opacity={isHovered ? 1 : 0.92}
                    />
                    <text
                      x={node.x + node.width / 2}
                      y={node.y + node.height + 22}
                      textAnchor="middle"
                      fontSize="14"
                      fontWeight="800"
                      fill={node.color}
                    >
                      {node.label}
                    </text>
                    <text
                      x={node.x + node.width / 2}
                      y={node.y + node.height + 38}
                      textAnchor="middle"
                      fontSize="10.5"
                      fill="#64748b"
                    >
                      {node.nodeCount} 节点 · 入 {node.inflow} · 出 {node.outflow}
                    </text>
                    <text
                      x={node.x + node.width / 2}
                      y={node.y - 12}
                      textAnchor="middle"
                      fontSize="9.5"
                      fill="#94a3b8"
                    >
                      {node.description}
                    </text>
                  </g>
                );
              })}
            </g>

            {/* Hover tooltip for link */}
            {hoveredLink ? (
              <g pointerEvents="none">
                <rect
                  x={(layout.nodes[hoveredLink.sourceLayer].x + layout.nodes[hoveredLink.targetLayer].x) / 2 - 90}
                  y={Math.min(hoveredLink.sourceY, hoveredLink.targetY) - 50}
                  width="180"
                  height="40"
                  rx="6"
                  fill="rgba(15, 23, 42, 0.92)"
                />
                <text
                  x={(layout.nodes[hoveredLink.sourceLayer].x + layout.nodes[hoveredLink.targetLayer].x) / 2}
                  y={Math.min(hoveredLink.sourceY, hoveredLink.targetY) - 32}
                  textAnchor="middle"
                  fontSize="11"
                  fontWeight="700"
                  fill="#ffffff"
                >
                  {LEARNING_LAYERS[hoveredLink.sourceLayer].label} → {LEARNING_LAYERS[hoveredLink.targetLayer].label}
                </text>
                <text
                  x={(layout.nodes[hoveredLink.sourceLayer].x + layout.nodes[hoveredLink.targetLayer].x) / 2}
                  y={Math.min(hoveredLink.sourceY, hoveredLink.targetY) - 16}
                  textAnchor="middle"
                  fontSize="10.5"
                  fill="#cbd5e1"
                >
                  {hoveredLink.count} 条 · 主导 {hoveredLink.dominantRelationLabel}
                </text>
              </g>
            ) : null}
          </svg>

          {/* Path completion overlay */}
          <div className="absolute right-4 top-4 max-w-[280px] rounded-lg border border-slate-200 bg-white/95 px-3 py-2.5 shadow-md backdrop-blur dark:border-slate-700 dark:bg-slate-950/80">
            <p className="text-[11px] font-semibold uppercase tracking-wide text-slate-500 dark:text-slate-400">
              路径完成度
            </p>
            <div className="mt-1.5 flex items-center gap-1">
              {LEARNING_LAYERS.map((layer, idx) => (
                <Fragment key={layer.label}>
                  <span
                    className="rounded-md px-1.5 py-0.5 text-[10px] font-semibold text-white"
                    style={{ backgroundColor: layer.color }}
                  >
                    {layer.label}
                  </span>
                  {idx < LEARNING_LAYERS.length - 1 ? (
                    <span
                      className={`text-base ${
                        consecutivePresence[idx] ? "text-emerald-500" : "text-rose-400"
                      }`}
                    >
                      {consecutivePresence[idx] ? "→" : "✕"}
                    </span>
                  ) : null}
                </Fragment>
              ))}
            </div>
            <p className="mt-2 text-[11px] leading-4 text-slate-600 dark:text-slate-300">
              {completedPath
                ? "5 段学习链全部贯通，可以从组织顺到训练。"
                : `贯通 ${completedCount}/4 段，缺失环节会让用户在中间断档。`}
            </p>
          </div>
        </div>
      </ChartPanel>

      <div className="grid gap-4 xl:grid-cols-[minmax(0,1.05fr)_minmax(0,0.95fr)]">
        <ChartPanel
          title="关系类型分布"
          description="不同关系决定学习功能：前置/包含搭路径，推理/应用做迁移，训练做闭环。"
        >
          <div className="grid gap-3 p-4">
            <CategoryBar
              segments={relationLegend.map((relation) => ({
                key: relation.type,
                label: relation.label,
                color: relation.color,
                count: relation.count,
                tooltip: `${relation.label} · ${relation.count} 条 · 平均置信 ${percentText(relation.averageConfidence)}`,
              }))}
            />
            <div className="grid gap-2">
              {relationLegend.map((relation) => {
                const max = Math.max(1, ...relationLegend.map((r) => r.count));
                return (
                  <div key={relation.type}>
                    <div className="mb-1 flex items-center justify-between gap-3 text-xs">
                      <span className="flex items-center gap-2 text-slate-700 dark:text-slate-200">
                        <span className="h-2 w-2 rounded-full" style={{ backgroundColor: relation.color }} />
                        <strong>{relation.label}</strong>
                      </span>
                      <span className="font-semibold tabular-nums text-slate-500 dark:text-slate-400">
                        {relation.count} · 置信 {percentText(relation.averageConfidence)}
                      </span>
                    </div>
                    <div className="h-1.5 overflow-hidden rounded-full bg-slate-100 dark:bg-slate-800">
                      <div
                        className="h-full"
                        style={{
                          width: `${(relation.count / max) * 100}%`,
                          backgroundColor: relation.color,
                        }}
                      />
                    </div>
                    <p className="mt-1 text-[10.5px] leading-4 text-slate-500 dark:text-slate-400">
                      {relation.purpose}
                    </p>
                  </div>
                );
              })}
            </div>
          </div>
        </ChartPanel>

        <ChartPanel
          title="流向方向性"
          description="向前流（学习方向）远多于回流，结构才是健康的。"
        >
          <div className="grid gap-4 p-4">
            <div className="rounded-lg border border-slate-200 bg-slate-50 px-3 py-3 dark:border-slate-800 dark:bg-slate-900/60">
              <div className="flex items-center justify-between">
                <p className="text-sm font-semibold text-slate-900 dark:text-slate-100">向前流（顺向学习）</p>
                <p className="text-2xl font-bold tabular-nums text-emerald-600 dark:text-emerald-400">
                  {forwardCount}
                </p>
              </div>
              <div className="mt-2 h-2 overflow-hidden rounded-full bg-emerald-100 dark:bg-emerald-500/15">
                <div
                  className="h-full bg-emerald-500"
                  style={{
                    width: `${(forwardCount / Math.max(1, forwardCount + backwardCount)) * 100}%`,
                  }}
                />
              </div>
            </div>
            <div className="rounded-lg border border-slate-200 bg-slate-50 px-3 py-3 dark:border-slate-800 dark:bg-slate-900/60">
              <div className="flex items-center justify-between">
                <p className="text-sm font-semibold text-slate-900 dark:text-slate-100">逆向流（回到上层）</p>
                <p className="text-2xl font-bold tabular-nums text-amber-600 dark:text-amber-400">
                  {backwardCount}
                </p>
              </div>
              <div className="mt-2 h-2 overflow-hidden rounded-full bg-amber-100 dark:bg-amber-500/15">
                <div
                  className="h-full bg-amber-500"
                  style={{
                    width: `${(backwardCount / Math.max(1, forwardCount + backwardCount)) * 100}%`,
                  }}
                />
              </div>
            </div>
            <div className="rounded-lg border border-slate-200 bg-slate-50 px-3 py-3 dark:border-slate-800 dark:bg-slate-900/60">
              <div className="flex items-center justify-between">
                <p className="text-sm font-semibold text-slate-900 dark:text-slate-100">同层自环</p>
                <p className="text-2xl font-bold tabular-nums text-slate-700 dark:text-slate-200">
                  {selfLoopTotal}
                </p>
              </div>
              <p className="mt-1 text-[11px] leading-4 text-slate-500 dark:text-slate-400">
                同层关系（说明、对比、相似）属于横向辨析，不计入路径主干。
              </p>
            </div>
            <p className="text-[11px] leading-4 text-slate-500 dark:text-slate-400">
              {forwardCount === 0
                ? "没有向前流动，路径无法贯通。"
                : backwardCount > forwardCount * 0.4
                  ? "回流偏多，部分关系方向可能反了，建议在节点详情核对方向。"
                  : "顺向流动占主导，路径方向正确。"}
              {dominantLink ? (
                <>
                  {" "}最粗的一段是
                  <strong className="ml-1 text-slate-700 dark:text-slate-200">
                    {LEARNING_LAYERS[dominantLink.sourceLayer].label} →
                    {LEARNING_LAYERS[dominantLink.targetLayer].label}
                  </strong>
                  （{dominantLink.count} 条 · {dominantLink.dominantRelationLabel}）。
                </>
              ) : null}
            </p>
          </div>
        </ChartPanel>
      </div>
    </div>
  );
}
