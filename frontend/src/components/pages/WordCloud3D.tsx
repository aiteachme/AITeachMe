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

interface BaseWord {
  color: string;
  confidence: number;
  fontSize: number;
  name: string;
  x: number;
  y: number;
  z: number;
}

interface RenderWord extends BaseWord {
  blurPx: number;
  glowColor: string;
  opacity: number;
  scale: number;
  screenX: number;
  screenY: number;
  zIndex: number;
}

const TYPE_COLORS: Record<string, string> = {
  Topic: "#8b5cf6",
  topic: "#8b5cf6",
  Concept: "#6366f1",
  concept: "#6366f1",
  Method: "#f59e0b",
  method: "#f59e0b",
  Definition: "#10b981",
  definition: "#10b981",
  Example: "#ec4899",
  example: "#ec4899",
  Theorem: "#3b82f6",
  theorem: "#3b82f6",
  Formula: "#06b6d4",
  formula: "#06b6d4",
};

const DEFAULT_COLOR = "#94a3b8";
const MAX_VISIBLE_WORDS = 80;
const SPHERE_RADIUS = 320;
const AUTO_ROTATE_SPEED = 0.003;
const TILT_RESET_X = -0.16;
const SPRING_FACTOR = 0.07;
const GOLDEN_ANGLE = Math.PI * (3 - Math.sqrt(5));

function clamp(value: number, min: number, max: number): number {
  return Math.min(max, Math.max(min, value));
}

function hexToRgba(hex: string, alpha: number): string {
  const normalized = hex.replace("#", "");
  const chunkSize = normalized.length === 3 ? 1 : 2;
  const raw = normalized.length === 3
    ? normalized.split("").map((char) => char.repeat(2))
    : normalized.match(/.{1,2}/g) ?? ["94", "a3", "b8"];
  const [r, g, b] = raw.map((chunk) => Number.parseInt(chunk.slice(0, chunkSize === 1 ? 1 : 2), 16));
  return `rgba(${r}, ${g}, ${b}, ${alpha})`;
}

function buildWordSphere(nodes: WordCloudNode[]): BaseWord[] {
  return nodes.slice(0, MAX_VISIBLE_WORDS).map((node, index, visibleNodes) => {
    const total = visibleNodes.length;
    const step = index + 0.5;
    const phi = Math.acos(1 - (2 * step) / Math.max(total, 1));
    const theta = GOLDEN_ANGLE * index;
    const emphasis = clamp(node.confidence, 0.15, 1);
    const radius = SPHERE_RADIUS - emphasis * 26;
    const color = TYPE_COLORS[node.nodeType] || DEFAULT_COLOR;

    return {
      name: node.name,
      confidence: emphasis,
      color,
      fontSize: 10 + emphasis * 6,
      x: Math.cos(theta) * Math.sin(phi) * radius,
      y: Math.sin(theta) * Math.sin(phi) * radius * 0.72,
      z: Math.cos(phi) * radius,
    };
  });
}

function rotateWord(word: BaseWord, rotateX: number, rotateY: number): RenderWord {
  const cosY = Math.cos(rotateY);
  const sinY = Math.sin(rotateY);
  const cosX = Math.cos(rotateX);
  const sinX = Math.sin(rotateX);

  const rotatedX = word.x * cosY + word.z * sinY;
  const rotatedZ = word.z * cosY - word.x * sinY;
  const rotatedY = word.y * cosX - rotatedZ * sinX;
  const depthZ = word.y * sinX + rotatedZ * cosX;
  const depth = clamp((depthZ + SPHERE_RADIUS) / (SPHERE_RADIUS * 2), 0, 1);

  return {
    ...word,
    screenX: rotatedX,
    screenY: rotatedY,
    scale: 0.6 + depth * 0.5 + word.confidence * 0.12,
    opacity: 0.2 + depth * 0.78,
    blurPx: (1 - depth) * 1.2,
    glowColor: hexToRgba(word.color, 0.18 + depth * 0.32),
    zIndex: Math.round(depth * 100),
  };
}

export function WordCloud3D({ subjectLabel, nodes, height }: WordCloud3DProps) {
  const containerHeight = height ?? "calc(100vh - 14rem)";
  const [rotation, setRotation] = useState({ x: TILT_RESET_X, y: 0 });
  const targetRotationRef = useRef({ x: TILT_RESET_X, y: 0 });
  const rotationRef = useRef({ x: TILT_RESET_X, y: 0 });

  const words = useMemo(() => buildWordSphere(nodes), [nodes]);
  const renderedWords = useMemo(
    () => words.map((word) => rotateWord(word, rotation.x, rotation.y)).sort((left, right) => left.zIndex - right.zIndex),
    [rotation.x, rotation.y, words],
  );

  useEffect(() => {
    let rafId = 0;

    const animate = () => {
      const nextX = rotationRef.current.x + (targetRotationRef.current.x - rotationRef.current.x) * SPRING_FACTOR;
      const nextY = rotationRef.current.y + (targetRotationRef.current.y - rotationRef.current.y) * SPRING_FACTOR + AUTO_ROTATE_SPEED;
      rotationRef.current = { x: nextX, y: nextY };
      setRotation(rotationRef.current);
      rafId = window.requestAnimationFrame(animate);
    };

    rafId = window.requestAnimationFrame(animate);
    return () => window.cancelAnimationFrame(rafId);
  }, []);

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
          <p className="text-sm font-medium text-slate-400">No graph data yet</p>
          <p className="mt-1 text-xs text-slate-600">Build the knowledge assets to render the word cloud.</p>
        </div>
      </div>
    );
  }

  const topTypes = Object.entries(
    nodes.reduce<Record<string, number>>((accumulator, node) => {
      const type = node.nodeType;
      accumulator[type] = (accumulator[type] || 0) + 1;
      return accumulator;
    }, {}),
  )
    .sort((left, right) => right[1] - left[1])
    .slice(0, 4);

  return (
    <div
      className="relative overflow-hidden rounded-2xl border border-slate-800 bg-gradient-to-b from-slate-950 via-[#0a0a1a] to-slate-950"
      style={{ height: containerHeight }}
      onMouseMove={(event) => {
        const rect = event.currentTarget.getBoundingClientRect();
        const offsetX = (event.clientX - rect.left) / rect.width - 0.5;
        const offsetY = (event.clientY - rect.top) / rect.height - 0.5;
        targetRotationRef.current = {
          x: clamp(TILT_RESET_X - offsetY * 0.7, -0.58, 0.42),
          y: rotationRef.current.y + offsetX * 0.14,
        };
      }}
      onMouseLeave={() => {
        targetRotationRef.current = { x: TILT_RESET_X, y: rotationRef.current.y };
      }}
    >
      <div className="pointer-events-none absolute inset-0">
        <div className="absolute left-1/2 top-1/2 h-[58%] w-[58%] -translate-x-1/2 -translate-y-1/2 rounded-full bg-fuchsia-700/12 blur-[120px]" />
        <div className="absolute left-[18%] top-[18%] h-40 w-40 rounded-full bg-cyan-500/8 blur-[90px]" />
        <div className="absolute bottom-[14%] right-[16%] h-48 w-48 rounded-full bg-indigo-500/10 blur-[100px]" />
        <div className="absolute left-1/2 top-1/2 h-[540px] w-[540px] -translate-x-1/2 -translate-y-1/2 rounded-full border border-white/6" />
        <div className="absolute left-1/2 top-1/2 h-[380px] w-[380px] -translate-x-1/2 -translate-y-1/2 rounded-full border border-white/5" />
      </div>

      <div className="pointer-events-none absolute left-0 right-0 top-0 p-5">
        <div className="flex items-center gap-2">
          <div className="h-2 w-2 animate-pulse rounded-full bg-fuchsia-500" />
          <span className="text-xs font-medium uppercase tracking-wider text-slate-400">
            Knowledge Universe
          </span>
        </div>
      </div>

      <div className="absolute inset-0 overflow-hidden [perspective:1400px]">
        <div className="pointer-events-none absolute left-1/2 top-1/2 z-10 -translate-x-1/2 -translate-y-1/2 rounded-full border border-white/10 bg-slate-950/45 px-5 py-4 text-center shadow-[0_0_40px_rgba(15,23,42,0.45)] backdrop-blur-xl">
          <p className="text-[10px] uppercase tracking-[0.28em] text-slate-500">Subject Core</p>
          <p className="mt-2 text-2xl font-semibold text-white">{subjectLabel}</p>
          <p className="mt-1 text-xs text-slate-400">{nodes.length} nodes orbiting in focus</p>
        </div>

        {renderedWords.map((word, index) => (
          <div
            key={`${word.name}-${index}`}
            className="pointer-events-none absolute left-1/2 top-1/2 whitespace-nowrap rounded-full border border-white/8 px-2 py-0.5 text-center font-medium tracking-[0.02em] backdrop-blur-sm"
            style={{
              transform: `translate(calc(-50% + ${word.screenX}px), calc(-50% + ${word.screenY}px)) scale(${word.scale})`,
              color: word.color,
              opacity: word.opacity,
              fontSize: `${word.fontSize}px`,
              zIndex: word.zIndex,
              filter: `blur(${word.blurPx}px)`,
              backgroundColor: "rgba(2, 6, 23, 0.38)",
              boxShadow: `0 0 20px ${word.glowColor}`,
              textShadow: `0 0 18px ${word.glowColor}`,
            }}
          >
            {word.name}
          </div>
        ))}
      </div>

      <div className="pointer-events-none absolute bottom-0 left-0 right-0 bg-gradient-to-t from-slate-950/90 to-transparent p-5 pt-10">
        <div className="flex items-end justify-between gap-3">
          <div>
            <p className="text-lg font-bold text-white/90">{subjectLabel}</p>
            <p className="mt-0.5 text-xs text-slate-500">{nodes.length} nodes - move cursor to rotate</p>
          </div>
          <div className="flex gap-3">
            {topTypes.map(([type, count]) => (
              <div key={type} className="flex items-center gap-1.5">
                <span
                  className="inline-block h-1.5 w-1.5 rounded-full"
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
