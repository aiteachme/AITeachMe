import { useEffect, useMemo, useRef, useState } from "react";

interface WordCloudNode {
  name: string;
  nodeType: string;
  confidence: number;
}

interface WordCloud3DProps {
  subjectLabel: string;
  nodes: WordCloudNode[];
  height?: number;
}

interface PlacedWord {
  name: string;
  color: string;
  confidence: number;
  fontSize: number;
  x: number;
  y: number;
  z: number;
}

interface RenderWord extends PlacedWord {
  screenX: number;
  screenY: number;
  scale: number;
  opacity: number;
  depth: number;
}

const TYPE_COLORS: Record<string, string> = {
  Topic: "#a78bfa",
  topic: "#a78bfa",
  Concept: "#818cf8",
  concept: "#818cf8",
  Method: "#fbbf24",
  method: "#fbbf24",
  Definition: "#34d399",
  definition: "#34d399",
  Example: "#f472b6",
  example: "#f472b6",
  Theorem: "#60a5fa",
  theorem: "#60a5fa",
  Formula: "#22d3ee",
  formula: "#22d3ee",
};

const DEFAULT_COLOR = "#94a3b8";
const MAX_VISIBLE_WORDS = 80;
const AUTO_ROTATE_SPEED = 0.002;
const TILT_X = -0.15;
const SPRING_FACTOR = 0.06;
const GOLDEN_ANGLE = Math.PI * (3 - Math.sqrt(5));

function clamp(value: number, min: number, max: number): number {
  return Math.min(max, Math.max(min, value));
}

function buildWordSphere(nodes: WordCloudNode[], radius: number): PlacedWord[] {
  return nodes.slice(0, MAX_VISIBLE_WORDS).map((node, index, visibleNodes) => {
    const total = visibleNodes.length;
    const step = index + 0.5;
    const phi = Math.acos(1 - (2 * step) / Math.max(total, 1));
    const theta = GOLDEN_ANGLE * index;
    const emphasis = clamp(node.confidence, 0.1, 1);
    const r = radius * (0.85 + emphasis * 0.15);
    const color = TYPE_COLORS[node.nodeType] || DEFAULT_COLOR;

    return {
      name: node.name,
      confidence: emphasis,
      color,
      fontSize: 11 + emphasis * 15,
      x: Math.cos(theta) * Math.sin(phi) * r,
      y: Math.sin(theta) * Math.sin(phi) * r * 0.75,
      z: Math.cos(phi) * r,
    };
  });
}

function projectWord(word: PlacedWord, rotX: number, rotY: number, radius: number): RenderWord {
  const cosY = Math.cos(rotY);
  const sinY = Math.sin(rotY);
  const cosX = Math.cos(rotX);
  const sinX = Math.sin(rotX);

  const rx = word.x * cosY + word.z * sinY;
  const rz = word.z * cosY - word.x * sinY;
  const ry = word.y * cosX - rz * sinX;
  const dz = word.y * sinX + rz * cosX;
  const depth = clamp((dz + radius) / (radius * 2), 0, 1);

  return {
    ...word,
    screenX: rx,
    screenY: ry,
    scale: 0.5 + depth * 0.6,
    opacity: 0.15 + depth * 0.85,
    depth,
  };
}

export function WordCloud3D({ subjectLabel, nodes, height }: WordCloud3DProps) {
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const containerRef = useRef<HTMLDivElement>(null);
  const [size, setSize] = useState({ w: 600, h: 400 });
  const rotationRef = useRef({ x: TILT_X, y: 0 });
  const targetRotRef = useRef({ x: TILT_X, y: 0 });
  const isDraggingRef = useRef(false);

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

  const sphereRadius = Math.min(size.w, size.h) * 0.38;
  const words = useMemo(() => buildWordSphere(nodes, sphereRadius), [nodes, sphereRadius]);

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

  // Animation loop — Canvas rendering
  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas || words.length === 0) return;
    const ctx = canvas.getContext("2d");
    if (!ctx) return;

    let rafId = 0;

    const render = () => {
      const rot = rotationRef.current;
      const target = targetRotRef.current;

      rot.x += (target.x - rot.x) * SPRING_FACTOR;
      rot.y += (target.y - rot.y) * SPRING_FACTOR;
      if (!isDraggingRef.current) {
        target.y += AUTO_ROTATE_SPEED;
      }

      const dpr = window.devicePixelRatio || 1;
      const cw = size.w;
      const ch = size.h;
      canvas.width = cw * dpr;
      canvas.height = ch * dpr;
      ctx.setTransform(dpr, 0, 0, dpr, 0, 0);

      // Background
      ctx.clearRect(0, 0, cw, ch);

      // Ambient glow
      const grad = ctx.createRadialGradient(cw / 2, ch / 2, 0, cw / 2, ch / 2, sphereRadius * 1.3);
      grad.addColorStop(0, "rgba(139, 92, 246, 0.06)");
      grad.addColorStop(0.5, "rgba(99, 102, 241, 0.03)");
      grad.addColorStop(1, "rgba(0, 0, 0, 0)");
      ctx.fillStyle = grad;
      ctx.fillRect(0, 0, cw, ch);

      // Orbit ring
      ctx.save();
      ctx.strokeStyle = "rgba(255, 255, 255, 0.04)";
      ctx.lineWidth = 1;
      ctx.beginPath();
      ctx.ellipse(cw / 2, ch / 2, sphereRadius, sphereRadius * 0.65, 0, 0, Math.PI * 2);
      ctx.stroke();
      ctx.restore();

      // Project and sort
      const projected = words
        .map((w) => projectWord(w, rot.x, rot.y, sphereRadius))
        .sort((a, b) => a.depth - b.depth);

      const cx = cw / 2;
      const cy = ch / 2;

      for (const w of projected) {
        const fs = w.fontSize * w.scale;
        ctx.save();
        ctx.globalAlpha = w.opacity;
        ctx.font = `600 ${fs}px system-ui, -apple-system, "Noto Sans SC", sans-serif`;
        ctx.textAlign = "center";
        ctx.textBaseline = "middle";

        // Glow
        const glowAlpha = 0.15 + w.depth * 0.25;
        ctx.shadowColor = w.color;
        ctx.shadowBlur = 8 + w.depth * 10;
        ctx.fillStyle = w.color.replace(")", `, ${glowAlpha})`).replace("rgb", "rgba");

        // Draw text
        ctx.fillStyle = w.color;
        ctx.fillText(w.name, cx + w.screenX, cy + w.screenY);

        ctx.shadowBlur = 0;
        ctx.restore();
      }

      rafId = requestAnimationFrame(render);
    };

    rafId = requestAnimationFrame(render);
    return () => cancelAnimationFrame(rafId);
  }, [words, size, sphereRadius]);

  // Mouse interaction
  const handleMouseMove = (e: React.MouseEvent) => {
    const rect = e.currentTarget.getBoundingClientRect();
    const ox = (e.clientX - rect.left) / rect.width - 0.5;
    const oy = (e.clientY - rect.top) / rect.height - 0.5;
    targetRotRef.current = {
      x: clamp(TILT_X - oy * 0.6, -0.5, 0.4),
      y: rotationRef.current.y + ox * 0.1,
    };
    isDraggingRef.current = true;
  };

  const handleMouseLeave = () => {
    targetRotRef.current = { x: TILT_X, y: rotationRef.current.y };
    isDraggingRef.current = false;
  };

  const containerHeight = height ?? "calc(100vh - 14rem)";

  if (nodes.length === 0) {
    return (
      <div
        className="flex items-center justify-center rounded-2xl border border-slate-800 bg-slate-950"
        style={{ height: containerHeight }}
      >
        <div className="text-center text-slate-500">
          <div className="mx-auto mb-3 flex h-10 w-10 items-center justify-center rounded-full bg-slate-800">
            <svg className="h-5 w-5 text-slate-500" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
              <circle cx="12" cy="12" r="10" />
              <path d="M8 12h8M12 8v8" />
            </svg>
          </div>
          <p className="text-sm font-medium text-slate-400">暂无图谱数据</p>
          <p className="mt-1 text-xs text-slate-600">构建知识资产后自动生成词云</p>
        </div>
      </div>
    );
  }

  return (
    <div
      ref={containerRef}
      className="relative overflow-hidden rounded-2xl border border-slate-800 bg-gradient-to-b from-slate-950 via-[#0a0a1a] to-slate-950"
      style={{ height: containerHeight }}
      onMouseMove={handleMouseMove}
      onMouseLeave={handleMouseLeave}
    >
      {/* Canvas fills the entire container */}
      <canvas
        ref={canvasRef}
        className="absolute inset-0 h-full w-full"
        style={{ width: "100%", height: "100%" }}
      />

      {/* Top-left badge */}
      <div className="pointer-events-none absolute left-0 right-0 top-0 p-4">
        <div className="flex items-center gap-2">
          <div className="h-2 w-2 animate-pulse rounded-full bg-fuchsia-500" />
          <span className="text-[10px] font-medium uppercase tracking-[0.2em] text-slate-500">
            Knowledge Universe
          </span>
        </div>
      </div>

      {/* Bottom info bar */}
      <div className="pointer-events-none absolute bottom-0 left-0 right-0 bg-gradient-to-t from-slate-950/90 to-transparent p-4 pt-10">
        <div className="flex items-end justify-between gap-3">
          <div>
            <p className="text-base font-bold text-white/90">{subjectLabel}</p>
            <p className="mt-0.5 text-[10px] text-slate-500">
              {nodes.length} 个知识节点 · 鼠标移动旋转
            </p>
          </div>
          <div className="flex gap-3">
            {topTypes.map(([type, count]) => (
              <div key={type} className="flex items-center gap-1.5">
                <span
                  className="inline-block h-2 w-2 rounded-full"
                  style={{ backgroundColor: TYPE_COLORS[type] || DEFAULT_COLOR }}
                />
                <span className="text-[10px] text-slate-500">
                  {type} {count}
                </span>
              </div>
            ))}
          </div>
        </div>
      </div>
    </div>
  );
}

export default WordCloud3D;
