import { useEffect, useMemo, useRef, useState, useCallback } from "react";
import cloud from "d3-cloud";

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
  onNodeClick?: (name: string) => void;
}

interface LayoutWord {
  text: string;
  fullName: string;
  nodeType: string;
  confidence: number;
  size: number;
  x?: number;
  y?: number;
  rotate?: number;
  color: string;
}

// ────────────────────────── Color Palette ──────────────────────────

const TYPE_COLORS: Record<string, string> = {
  Topic: "#f39c12",
  topic: "#f39c12",
  Concept: "#5dade2",
  concept: "#5dade2",
  Method: "#ec7063",
  method: "#ec7063",
  Definition: "#58d68d",
  definition: "#58d68d",
  Example: "#af7ac5",
  example: "#af7ac5",
  Theorem: "#48c9b0",
  theorem: "#48c9b0",
  Formula: "#5d6d7e",
  formula: "#5d6d7e",
};

const TYPE_LABELS: Record<string, string> = {
  Topic: "主题",
  Concept: "概念",
  Method: "方法",
  Definition: "定义",
  Example: "示例",
  Theorem: "定理",
  Formula: "公式",
};

const DEFAULT_COLOR = "#94a3b8";

function getColor(nodeType: string): string {
  return TYPE_COLORS[nodeType] ?? DEFAULT_COLOR;
}

// ────────────────────────── Helpers ──────────────────────────

function truncate(s: string, max: number): string {
  return s.length <= max ? s : s.slice(0, max - 1) + "…";
}

const MAX_WORDS = 100;

// ────────────────────────── Main Component ──────────────────────────

export function WordCloud3D({ subjectLabel, nodes, height, onNodeClick }: WordCloud3DProps) {
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const containerRef = useRef<HTMLDivElement>(null);
  const [size, setSize] = useState({ w: 800, h: 500 });
  const [layoutWords, setLayoutWords] = useState<LayoutWord[]>([]);
  const [hoveredWord, setHoveredWord] = useState<LayoutWord | null>(null);
  const [transform, setTransform] = useState({ x: 0, y: 0, scale: 1 });
  const dragRef = useRef<{ dragging: boolean; lastX: number; lastY: number }>({
    dragging: false,
    lastX: 0,
    lastY: 0,
  });

  // Prepare sorted + deduplicated word list
  const wordInput = useMemo(() => {
    const seen = new Set<string>();
    const sorted = [...nodes].sort((a, b) => b.confidence - a.confidence);
    const result: WordCloudNode[] = [];
    for (const n of sorted) {
      const key = n.name.toLowerCase().trim();
      if (!key || seen.has(key)) continue;
      seen.add(key);
      result.push(n);
      if (result.length >= MAX_WORDS) break;
    }
    return result;
  }, [nodes]);

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

  // Run d3-cloud layout
  useEffect(() => {
    if (wordInput.length === 0) return;

    const maxConf = Math.max(...wordInput.map((w) => w.confidence), 0.01);
    const minFont = 10;
    const maxFont = Math.min(size.w, size.h) * 0.08;

    const words: LayoutWord[] = wordInput.map((w) => {
      const ratio = w.confidence / maxConf;
      const fontSize = minFont + ratio * (maxFont - minFont);
      return {
        text: truncate(w.name, 16),
        fullName: w.name,
        nodeType: w.nodeType,
        confidence: w.confidence,
        size: fontSize,
        color: getColor(w.nodeType),
      };
    });

    const layout = cloud<LayoutWord>()
      .size([size.w, size.h])
      .words(words)
      .padding(4)
      .rotate(() => (Math.random() > 0.7 ? 90 : 0))
      .font('"Inter", system-ui, -apple-system, "Noto Sans SC", "Microsoft YaHei", sans-serif')
      .fontSize((d) => d.size ?? 14)
      .spiral("archimedean")
      .on("end", (output) => {
        setLayoutWords(output as LayoutWord[]);
      });

    layout.start();
  }, [wordInput, size]);

  // Draw on canvas
  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas || layoutWords.length === 0) return;
    const ctx = canvas.getContext("2d");
    if (!ctx) return;

    const dpr = Math.min(window.devicePixelRatio || 1, 2);
    const cw = size.w;
    const ch = size.h;
    canvas.width = cw * dpr;
    canvas.height = ch * dpr;
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);

    // Background
    ctx.fillStyle = "#ffffff";
    ctx.fillRect(0, 0, cw, ch);

    // Subtle center glow
    const glow = ctx.createRadialGradient(
      cw * 0.5, ch * 0.45, 0,
      cw * 0.5, ch * 0.45, Math.min(cw, ch) * 0.45,
    );
    glow.addColorStop(0, "rgba(99, 102, 241, 0.03)");
    glow.addColorStop(1, "rgba(255, 255, 255, 0)");
    ctx.fillStyle = glow;
    ctx.fillRect(0, 0, cw, ch);

    // Apply transform
    ctx.save();
    ctx.translate(cw / 2 + transform.x, ch / 2 + transform.y);
    ctx.scale(transform.scale, transform.scale);

    for (const w of layoutWords) {
      if (w.x == null || w.y == null) continue;
      const isHovered = hoveredWord?.fullName === w.fullName;

      ctx.save();
      ctx.translate(w.x, w.y);
      if (w.rotate) ctx.rotate((w.rotate * Math.PI) / 180);

      const fs = w.size ?? 14;
      const weight = isHovered ? 700 : fs > 20 ? 600 : 500;
      const scale = isHovered ? 1.15 : 1;

      ctx.font = `${weight} ${fs * scale}px "Inter", system-ui, -apple-system, "Noto Sans SC", "Microsoft YaHei", sans-serif`;
      ctx.textAlign = "center";
      ctx.textBaseline = "middle";
      ctx.globalAlpha = isHovered ? 1 : Math.max(0.5, (w.confidence ?? 0.5));

      if (isHovered) {
        ctx.shadowColor = w.color;
        ctx.shadowBlur = 10;
      }

      ctx.fillStyle = w.color;
      ctx.fillText(w.text ?? "", 0, 0);

      ctx.shadowBlur = 0;
      ctx.restore();
    }

    ctx.restore();
  }, [layoutWords, size, hoveredWord, transform]);

  // Hit testing
  const hitTest = useCallback(
    (clientX: number, clientY: number): LayoutWord | null => {
      const canvas = canvasRef.current;
      if (!canvas) return null;
      const rect = canvas.getBoundingClientRect();
      // Convert to canvas-local coordinates, then to layout coordinates
      const mx = clientX - rect.left - size.w / 2 - transform.x;
      const my = clientY - rect.top - size.h / 2 - transform.y;
      const lx = mx / transform.scale;
      const ly = my / transform.scale;

      for (let i = layoutWords.length - 1; i >= 0; i--) {
        const w = layoutWords[i];
        if (w.x == null || w.y == null) continue;
        const fs = w.size ?? 14;
        const textW = (w.text?.length ?? 0) * fs * 0.55;
        const textH = fs * 1.3;

        const isRotated = w.rotate === 90;
        const hw = isRotated ? textH / 2 : textW / 2;
        const hh = isRotated ? textW / 2 : textH / 2;

        if (
          lx >= w.x - hw &&
          lx <= w.x + hw &&
          ly >= w.y - hh &&
          ly <= w.y + hh
        ) {
          return w;
        }
      }
      return null;
    },
    [layoutWords, size, transform],
  );

  // Mouse handlers
  const handleMouseMove = useCallback(
    (e: React.MouseEvent) => {
      if (dragRef.current.dragging) {
        const dx = e.clientX - dragRef.current.lastX;
        const dy = e.clientY - dragRef.current.lastY;
        dragRef.current.lastX = e.clientX;
        dragRef.current.lastY = e.clientY;
        setTransform((prev) => ({ ...prev, x: prev.x + dx, y: prev.y + dy }));
        return;
      }
      const hit = hitTest(e.clientX, e.clientY);
      setHoveredWord(hit);
    },
    [hitTest],
  );

  const handleMouseDown = useCallback((e: React.MouseEvent) => {
    dragRef.current = { dragging: true, lastX: e.clientX, lastY: e.clientY };
  }, []);

  const handleMouseUp = useCallback(() => {
    dragRef.current.dragging = false;
  }, []);

  const handleMouseLeave = useCallback(() => {
    dragRef.current.dragging = false;
    setHoveredWord(null);
  }, []);

  const handleClick = useCallback(
    (e: React.MouseEvent) => {
      const hit = hitTest(e.clientX, e.clientY);
      if (hit && onNodeClick) {
        onNodeClick(hit.fullName);
      }
    },
    [hitTest, onNodeClick],
  );

  // Zoom with scroll wheel
  const handleWheel = useCallback((e: React.WheelEvent) => {
    e.preventDefault();
    const delta = e.deltaY > 0 ? 0.9 : 1.1;
    setTransform((prev) => ({
      ...prev,
      scale: Math.max(0.3, Math.min(3, prev.scale * delta)),
    }));
  }, []);

  const containerHeight = height ?? "100%";

  // Empty state
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
        cursor: hoveredWord ? "pointer" : dragRef.current.dragging ? "grabbing" : "grab",
      }}
      onMouseMove={handleMouseMove}
      onMouseDown={handleMouseDown}
      onMouseUp={handleMouseUp}
      onMouseLeave={handleMouseLeave}
      onClick={handleClick}
      onWheel={handleWheel}
    >
      {/* Canvas */}
      <canvas
        ref={canvasRef}
        className="absolute inset-0 h-full w-full"
        style={{ width: "100%", height: "100%" }}
      />

      {/* Hover tooltip */}
      {hoveredWord && hoveredWord.x != null && hoveredWord.y != null && (
        <div
          className="pointer-events-none absolute z-20 animate-in fade-in-0 duration-150"
          style={{
            left: Math.min(
              size.w / 2 + transform.x + hoveredWord.x * transform.scale + 12,
              size.w - 220,
            ),
            top: Math.max(
              size.h / 2 + transform.y + hoveredWord.y * transform.scale - 48,
              8,
            ),
          }}
        >
          <div className="rounded-lg border border-slate-200/60 bg-white px-3 py-2 shadow-lg">
            <p className="max-w-[200px] text-xs font-bold leading-tight text-slate-800">
              {hoveredWord.fullName}
            </p>
            <div className="mt-1 flex items-center gap-1.5">
              <span
                className="rounded px-1 py-0.5 text-[9px] font-medium text-white"
                style={{ backgroundColor: hoveredWord.color }}
              >
                {TYPE_LABELS[hoveredWord.nodeType] ?? hoveredWord.nodeType}
              </span>
              <span className="text-[9px] text-slate-400">
                {Math.round(hoveredWord.confidence * 100)}%
              </span>
            </div>
          </div>
        </div>
      )}

      {/* Bottom info strip */}
      <div
        className="pointer-events-none absolute bottom-0 left-0 right-0 z-10 px-3 pb-3 pt-8"
        style={{
          background: "linear-gradient(to top, rgba(255,255,255,0.95) 0%, transparent 100%)",
        }}
      >
        <div className="flex items-end justify-between gap-3">
          <div>
            <p className="text-sm font-bold text-slate-800">{subjectLabel}</p>
            <p className="mt-0.5 text-[9px] text-slate-400">
              {nodes.length} 个知识节点 · 点击查看详情 · 滚轮缩放 · 拖拽平移
            </p>
          </div>
          <div className="flex flex-wrap justify-end gap-1.5">
            {topTypes.map(([type, count]) => {
              const color = TYPE_COLORS[type] ?? DEFAULT_COLOR;
              return (
                <div
                  key={type}
                  className="flex items-center gap-1 rounded-full px-2 py-0.5 text-[9px] font-medium"
                  style={{
                    backgroundColor: `${color}15`,
                    border: `1px solid ${color}30`,
                    color,
                  }}
                >
                  <span
                    className="inline-block h-1.5 w-1.5 rounded-full"
                    style={{ backgroundColor: color }}
                  />
                  {TYPE_LABELS[type] ?? type} {count}
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
