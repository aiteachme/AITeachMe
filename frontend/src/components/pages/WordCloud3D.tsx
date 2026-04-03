import { useEffect, useMemo, useRef, useState, useCallback } from "react";

// ────────────────────────── Types ──────────────────────────

interface WordCloudNode {
  name: string;
  nodeType: string;
  confidence: number;
}

interface WordCloud3DProps {
  subjectLabel: string;
  nodes: WordCloudNode[];
  height?: number | string;
}

interface FloatingWord {
  name: string;
  displayName: string;
  fullName: string;
  nodeType: string;
  confidence: number;
  color: string;
  fontSize: number;
  x: number;
  y: number;
  baseX: number;
  baseY: number;
  driftSpeedX: number;
  driftSpeedY: number;
  phaseX: number;
  phaseY: number;
  amplitudeX: number;
  amplitudeY: number;
  opacity: number;
  tier: "accent" | "medium" | "faint"; // algo.qq.com has 3 visual tiers
}

// ────────────────────────── algo.qq.com Color Scheme ──────────────────────────
// Purple accents for top words, dark gray for medium, very light gray for depth filler

const TYPE_ACCENT: Record<string, string> = {
  Topic:      "#9333ea",
  topic:      "#9333ea",
  Concept:    "#7c3aed",
  concept:    "#7c3aed",
  Method:     "#a855f7",
  method:     "#a855f7",
  Definition: "#6d28d9",
  definition: "#6d28d9",
  Example:    "#8b5cf6",
  example:    "#8b5cf6",
  Theorem:    "#7e22ce",
  theorem:    "#7e22ce",
  Formula:    "#6366f1",
  formula:    "#6366f1",
};

const DEFAULT_ACCENT = "#9333ea";

// ────────────────────────── Helpers ──────────────────────────

function truncate(s: string, max: number): string {
  return s.length <= max ? s : s.slice(0, max - 1) + "…";
}

function seededRandom(seed: number): () => number {
  let s = seed;
  return () => {
    s = (s * 16807 + 0) % 2147483647;
    return s / 2147483647;
  };
}

// ────────────────────────── Layout: algo.qq.com dense field ──────────────────────────

const MAX_DISPLAY_WORDS = 120; // algo.qq.com shows 100+ words

function buildAlgoLayout(nodes: WordCloudNode[]): FloatingWord[] {
  const sorted = [...nodes].sort((a, b) => b.confidence - a.confidence);
  const rand = seededRandom(42);

  // If we have fewer nodes than MAX, duplicate some faint ones for density
  const visible: WordCloudNode[] = [];
  for (let i = 0; i < MAX_DISPLAY_WORDS; i++) {
    if (i < sorted.length) {
      visible.push(sorted[i]);
    } else {
      // Duplicate random nodes as faint background fillers
      visible.push(sorted[Math.floor(rand() * sorted.length)]);
    }
  }

  return visible.map((node, i) => {
    const rank = i / Math.max(visible.length - 1, 1); // 0=best, 1=worst
    const accent = TYPE_ACCENT[node.nodeType] ?? DEFAULT_ACCENT;

    // Tier system: top 8% = accent (purple), next 25% = medium (dark), rest = faint
    let tier: "accent" | "medium" | "faint";
    let color: string;
    let opacity: number;
    let fontSize: number;

    if (rank < 0.08) {
      // Top tier: large, purple, fully visible
      tier = "accent";
      color = accent;
      opacity = 0.9;
      fontSize = 22 + (1 - rank / 0.08) * 20; // 22-42px
    } else if (rank < 0.33) {
      // Medium tier: medium size, dark gray
      tier = "medium";
      color = "#1f2937";
      opacity = 0.55 + (1 - (rank - 0.08) / 0.25) * 0.3;
      fontSize = 12 + (1 - (rank - 0.08) / 0.25) * 12; // 12-24px
    } else {
      // Faint tier: small, light gray, creates depth texture
      tier = "faint";
      color = "#d1d5db";
      opacity = 0.2 + rand() * 0.2;
      fontSize = 7 + rand() * 8; // 7-15px
    }

    // Scatter across full canvas
    const baseX = 0.02 + rand() * 0.96;
    const baseY = 0.02 + rand() * 0.96;

    return {
      name: node.name,
      displayName: truncate(node.name, tier === "faint" ? 18 : 14),
      fullName: node.name,
      nodeType: node.nodeType,
      confidence: node.confidence,
      color,
      fontSize,
      x: baseX,
      y: baseY,
      baseX,
      baseY,
      // Slow sinusoidal drift (algo.qq.com has subtle floating)
      driftSpeedX: 0.05 + rand() * 0.15,
      driftSpeedY: 0.04 + rand() * 0.12,
      phaseX: rand() * Math.PI * 2,
      phaseY: rand() * Math.PI * 2,
      amplitudeX: 0.003 + rand() * 0.01,
      amplitudeY: 0.002 + rand() * 0.008,
      opacity,
      tier,
    };
  });
}

// ────────────────────────── Main Component ──────────────────────────

export function WordCloud3D({ subjectLabel, nodes, height }: WordCloud3DProps) {
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const containerRef = useRef<HTMLDivElement>(null);
  const [size, setSize] = useState({ w: 800, h: 600 });
  const [hoveredWord, setHoveredWord] = useState<FloatingWord | null>(null);
  const mouseRef = useRef({ x: -1, y: -1 });

  const words = useMemo(() => buildAlgoLayout(nodes), [nodes]);

  const topTypes = useMemo(() => {
    return Object.entries(
      nodes.reduce<Record<string, number>>((acc, n) => {
        acc[n.nodeType] = (acc[n.nodeType] || 0) + 1;
        return acc;
      }, {}),
    )
      .sort((a, b) => b[1] - a[1])
      .slice(0, 5);
  }, [nodes]);

  // Measure container
  useEffect(() => {
    const el = containerRef.current;
    if (!el) return;
    const measure = () => {
      const w = el.clientWidth;
      const h = el.clientHeight;
      if (w > 0 && h > 0) setSize({ w, h });
    };
    measure();
    const obs = new ResizeObserver(measure);
    obs.observe(el);
    return () => obs.disconnect();
  }, []);

  // Animation loop
  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas || words.length === 0) return;
    const ctx = canvas.getContext("2d");
    if (!ctx) return;

    let rafId = 0;

    const render = (timestamp: number) => {
      const dt = timestamp * 0.001;

      const dpr = Math.min(window.devicePixelRatio || 1, 2);
      const cw = size.w;
      const ch = size.h;
      canvas.width = cw * dpr;
      canvas.height = ch * dpr;
      ctx.setTransform(dpr, 0, 0, dpr, 0, 0);

      // ── Background: pure white (algo.qq.com style) ──
      ctx.fillStyle = "#ffffff";
      ctx.fillRect(0, 0, cw, ch);

      // ── Subtle center glow (very faint purple radial) ──
      const glow = ctx.createRadialGradient(cw * 0.45, ch * 0.4, 0, cw * 0.45, ch * 0.4, Math.min(cw, ch) * 0.5);
      glow.addColorStop(0, "rgba(147, 51, 234, 0.03)");
      glow.addColorStop(1, "rgba(255, 255, 255, 0)");
      ctx.fillStyle = glow;
      ctx.fillRect(0, 0, cw, ch);

      // ── Draw words (faint first, accent last) ──
      const mx = mouseRef.current.x;
      const my = mouseRef.current.y;
      let newHovered: FloatingWord | null = null;

      // Sort: faint → medium → accent (draw accent on top)
      const sortOrder = { faint: 0, medium: 1, accent: 2 };
      const sorted = [...words].sort((a, b) => sortOrder[a.tier] - sortOrder[b.tier]);

      for (const w of sorted) {
        // Sinusoidal floating
        const fx = w.baseX + Math.sin(dt * w.driftSpeedX + w.phaseX) * w.amplitudeX;
        const fy = w.baseY + Math.sin(dt * w.driftSpeedY + w.phaseY) * w.amplitudeY;
        const sx = fx * cw;
        const sy = fy * ch;
        w.x = fx;
        w.y = fy;

        const fs = w.fontSize;

        // Hover detection
        const textW = w.displayName.length * fs * 0.52;
        const textH = fs * 1.2;
        const isHovered =
          mx >= 0 &&
          mx >= sx - textW / 2 - 4 &&
          mx <= sx + textW / 2 + 4 &&
          my >= sy - textH / 2 - 4 &&
          my <= sy + textH / 2 + 4;

        if (isHovered && w.tier !== "faint") newHovered = w;

        ctx.save();
        ctx.globalAlpha = isHovered ? 1 : w.opacity;

        // Font weight: accent=bold, medium=medium, faint=light
        const weight = isHovered ? 700 : w.tier === "accent" ? 600 : w.tier === "medium" ? 500 : 300;
        const scale = isHovered ? 1.1 : 1;

        ctx.font = `${weight} ${fs * scale}px "Inter", system-ui, -apple-system, "Noto Sans SC", "Microsoft YaHei", sans-serif`;
        ctx.textAlign = "center";
        ctx.textBaseline = "middle";

        // Color: hover = purple accent, otherwise use tier color
        if (isHovered) {
          ctx.fillStyle = TYPE_ACCENT[w.nodeType] ?? DEFAULT_ACCENT;
          // Subtle glow on hover
          ctx.shadowColor = TYPE_ACCENT[w.nodeType] ?? DEFAULT_ACCENT;
          ctx.shadowBlur = 12;
        } else {
          ctx.fillStyle = w.color;
        }

        ctx.fillText(w.displayName, sx, sy);

        ctx.shadowBlur = 0;
        ctx.restore();
      }

      setHoveredWord(newHovered);
      rafId = requestAnimationFrame(render);
    };

    rafId = requestAnimationFrame(render);
    return () => cancelAnimationFrame(rafId);
  }, [words, size]);

  // Mouse tracking
  const handleMouseMove = useCallback((e: React.MouseEvent) => {
    const rect = e.currentTarget.getBoundingClientRect();
    mouseRef.current = { x: e.clientX - rect.left, y: e.clientY - rect.top };
  }, []);

  const handleMouseLeave = useCallback(() => {
    mouseRef.current = { x: -1, y: -1 };
    setHoveredWord(null);
  }, []);

  const containerHeight = height ?? "100%";

  // ── Empty state ──
  if (nodes.length === 0) {
    return (
      <div
        ref={containerRef}
        className="flex items-center justify-center rounded-xl bg-white"
        style={{ height: containerHeight, minHeight: 300 }}
      >
        <div className="text-center">
          <div className="mx-auto mb-3 flex h-12 w-12 items-center justify-center rounded-full bg-slate-50 ring-1 ring-slate-200">
            <svg className="h-6 w-6 text-slate-400" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5">
              <circle cx="12" cy="12" r="10" />
              <path d="M8 12h8M12 8v8" />
            </svg>
          </div>
          <p className="text-sm font-medium text-slate-500">暂无图谱数据</p>
          <p className="mt-1 text-xs text-slate-400">构建知识资产后自动生成词云</p>
        </div>
      </div>
    );
  }

  return (
    <div
      ref={containerRef}
      className="relative overflow-hidden rounded-xl bg-white"
      style={{
        height: containerHeight,
        minHeight: 400,
        cursor: hoveredWord ? "pointer" : "default",
      }}
      onMouseMove={handleMouseMove}
      onMouseLeave={handleMouseLeave}
    >
      {/* Canvas */}
      <canvas
        ref={canvasRef}
        className="absolute inset-0 h-full w-full"
        style={{ width: "100%", height: "100%" }}
      />

      {/* Hover tooltip */}
      {hoveredWord && (
        <div
          className="pointer-events-none absolute z-20 animate-in fade-in-0 duration-150"
          style={{
            left: Math.min(hoveredWord.x * size.w + 12, size.w - 200),
            top: Math.max(hoveredWord.y * size.h - 48, 8),
          }}
        >
          <div
            className="rounded-lg border border-purple-200/60 bg-white px-3 py-2 shadow-lg"
          >
            <p className="text-xs font-bold text-slate-800 max-w-[180px] leading-tight">{hoveredWord.fullName}</p>
            <div className="flex items-center gap-1.5 mt-1">
              <span
                className="rounded px-1 py-0.5 text-[9px] font-medium text-purple-700 bg-purple-50"
              >
                {hoveredWord.nodeType}
              </span>
              <span className="text-[9px] text-slate-400">
                {Math.round(hoveredWord.confidence * 100)}%
              </span>
            </div>
          </div>
        </div>
      )}

      {/* Bottom info strip */}
      <div className="pointer-events-none absolute bottom-0 left-0 right-0 px-3 pb-3 pt-8 z-10"
        style={{ background: "linear-gradient(to top, rgba(255,255,255,0.95) 0%, transparent 100%)" }}
      >
        <div className="flex items-end justify-between gap-3">
          <div>
            <p className="text-sm font-bold text-slate-800">{subjectLabel}</p>
            <p className="text-[9px] text-slate-400 mt-0.5">
              {nodes.length} 个知识节点 · 悬停查看详情
            </p>
          </div>
          <div className="flex flex-wrap gap-1.5 justify-end">
            {topTypes.map(([type, count]) => {
              const accent = TYPE_ACCENT[type] ?? DEFAULT_ACCENT;
              return (
                <div
                  key={type}
                  className="flex items-center gap-1 rounded-full px-2 py-0.5 text-[9px] font-medium"
                  style={{
                    backgroundColor: `${accent}10`,
                    border: `1px solid ${accent}25`,
                    color: accent,
                  }}
                >
                  <span
                    className="inline-block h-1.5 w-1.5 rounded-full"
                    style={{ backgroundColor: accent }}
                  />
                  {type} {count}
                </div>
              );
            })}
          </div>
        </div>
      </div>
    </div>
  );
}

export default WordCloud3D;
