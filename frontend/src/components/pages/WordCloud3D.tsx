import { Billboard, Text } from "@react-three/drei";
import { Canvas, useFrame } from "@react-three/fiber";
import { useMemo, useRef, useState } from "react";
import * as THREE from "three";

import type { FullGraphResponse } from "../../api/generated/model";

interface WordCloud3DProps {
  subjectLabel: string;
  graph: FullGraphResponse | null;
  height?: number | string;
}

interface RankedNode {
  id: number;
  label: string;
  shortLabel: string;
  nodeType: string;
  color: string;
  salience: number;
  degree: number;
  radius: number;
  speed: number;
  phase: number;
  verticalOffset: number;
  bobAmplitude: number;
  fontSize: number;
}

interface ParticleNode {
  position: [number, number, number];
  color: string;
  size: number;
}

const TYPE_COLORS: Record<string, string> = {
  Topic: "#0f172a",
  topic: "#0f172a",
  Concept: "#0369a1",
  concept: "#0369a1",
  Definition: "#0284c7",
  definition: "#0284c7",
  Formula: "#0f766e",
  formula: "#0f766e",
  Method: "#ea580c",
  method: "#ea580c",
  Theorem: "#1d4ed8",
  theorem: "#1d4ed8",
  Example: "#7c3aed",
  example: "#7c3aed",
};

const TYPE_WEIGHTS: Record<string, number> = {
  Topic: 1.35,
  topic: 1.35,
  Concept: 1.25,
  concept: 1.25,
  Definition: 1.05,
  definition: 1.05,
  Formula: 1.1,
  formula: 1.1,
  Method: 1.0,
  method: 1.0,
  Theorem: 1.08,
  theorem: 1.08,
  Example: 0.82,
  example: 0.82,
};

const DEFAULT_COLOR = "#64748b";

function clamp(value: number, min: number, max: number): number {
  return Math.min(max, Math.max(min, value));
}

function seededUnit(index: number, salt: number): number {
  const raw = Math.sin(index * 12.9898 + salt * 78.233) * 43758.5453;
  return raw - Math.floor(raw);
}

function truncateLabel(label: string): string {
  return label.length > 14 ? `${label.slice(0, 13)}…` : label;
}

function buildVisualState(graph: FullGraphResponse | null) {
  const nodes = graph?.nodes ?? [];
  const edges = graph?.edges ?? [];
  const degreeMap = new Map<number, number>();

  for (const edge of edges) {
    degreeMap.set(edge.source_node_id, (degreeMap.get(edge.source_node_id) ?? 0) + 1);
    degreeMap.set(edge.target_node_id, (degreeMap.get(edge.target_node_id) ?? 0) + 1);
  }

  const maxDegree = Math.max(
    1,
    ...nodes.map((node) => degreeMap.get(node.id) ?? 0),
  );

  const ranked = nodes
    .map((node, index) => {
      const degree = degreeMap.get(node.id) ?? 0;
      const degreeScore = degree / maxDegree;
      const typeWeight = TYPE_WEIGHTS[node.node_type] ?? 0.92;
      const salience = clamp(
        node.confidence * 0.42 + degreeScore * 0.42 + Math.min(typeWeight / 1.35, 1) * 0.16,
        0.12,
        1,
      );

      return {
        id: node.id,
        index,
        label: node.canonical_name,
        shortLabel: truncateLabel(node.canonical_name),
        nodeType: node.node_type,
        color: TYPE_COLORS[node.node_type] ?? DEFAULT_COLOR,
        salience,
        degree,
      };
    })
    .sort((left, right) => right.salience - left.salience || right.degree - left.degree);

  const labelCount = Math.min(45, Math.max(30, Math.ceil(ranked.length * 0.34)));
  const labels: RankedNode[] = ranked.slice(0, labelCount).map((node, index) => {
    const layer = index % 3;
    const radius = 3.1 + layer * 1.05 + (1 - node.salience) * 0.95;
    const phase = (index / Math.max(labelCount, 1)) * Math.PI * 2 + seededUnit(index, 1) * 0.65;
    const verticalOffset = -2 + layer * 1.85 + seededUnit(index, 2) * 0.7;

    return {
      ...node,
      radius,
      phase,
      verticalOffset,
      speed: 0.07 + node.salience * 0.11,
      bobAmplitude: 0.12 + seededUnit(index, 3) * 0.16,
      fontSize: 0.34 + node.salience * 0.34,
    };
  });

  const particles: ParticleNode[] = ranked.slice(labelCount).map((node, index) => {
    const radius = 3.6 + seededUnit(index, 4) * 2.9;
    const theta = seededUnit(index, 5) * Math.PI * 2;
    const phi = Math.acos(1 - 2 * seededUnit(index, 6));
    const x = Math.cos(theta) * Math.sin(phi) * radius;
    const y = Math.cos(phi) * radius * 0.85;
    const z = Math.sin(theta) * Math.sin(phi) * radius;

    return {
      position: [x, y, z],
      color: node.color,
      size: 0.022 + node.salience * 0.028,
    };
  });

  const topTypes = Object.entries(
    nodes.reduce<Record<string, number>>((accumulator, node) => {
      accumulator[node.node_type] = (accumulator[node.node_type] ?? 0) + 1;
      return accumulator;
    }, {}),
  )
    .sort((left, right) => right[1] - left[1])
    .slice(0, 4);

  return {
    nodeCount: nodes.length,
    edgeCount: edges.length,
    labels,
    particles,
    topTypes,
  };
}

function ParticleShell({ particles }: { particles: ParticleNode[] }) {
  const ref = useRef<THREE.Points>(null);
  const [positions, colors] = useMemo(() => {
    const positionArray = new Float32Array(particles.length * 3);
    const colorArray = new Float32Array(particles.length * 3);

    particles.forEach((particle, index) => {
      const [x, y, z] = particle.position;
      positionArray[index * 3] = x;
      positionArray[index * 3 + 1] = y;
      positionArray[index * 3 + 2] = z;

      const color = new THREE.Color(particle.color);
      colorArray[index * 3] = color.r;
      colorArray[index * 3 + 1] = color.g;
      colorArray[index * 3 + 2] = color.b;
    });

    return [positionArray, colorArray];
  }, [particles]);

  useFrame((_, delta) => {
    if (!ref.current) return;
    ref.current.rotation.y += delta * 0.035;
    ref.current.rotation.x = Math.sin(performance.now() * 0.00008) * 0.08;
  });

  return (
    <points ref={ref}>
      <bufferGeometry>
        <bufferAttribute attach="attributes-position" args={[positions, 3]} />
        <bufferAttribute attach="attributes-color" args={[colors, 3]} />
      </bufferGeometry>
      <pointsMaterial
        size={0.08}
        vertexColors
        transparent
        opacity={0.44}
        sizeAttenuation
        depthWrite={false}
      />
    </points>
  );
}

function WordOrbit({
  word,
  onHover,
  onLeave,
}: {
  word: RankedNode;
  onHover: (word: RankedNode) => void;
  onLeave: () => void;
}) {
  const ref = useRef<THREE.Group>(null);

  useFrame((state) => {
    if (!ref.current) return;
    const elapsed = state.clock.elapsedTime;
    const angle = elapsed * word.speed + word.phase;
    ref.current.position.set(
      Math.cos(angle) * word.radius,
      word.verticalOffset + Math.sin(angle * 1.4) * word.bobAmplitude,
      Math.sin(angle) * word.radius,
    );
  });

  return (
    <group ref={ref}>
      <Billboard follow>
        <Text
          fontSize={word.fontSize}
          color={word.color}
          anchorX="center"
          anchorY="middle"
          outlineColor="#f8fafc"
          outlineWidth={0.018}
          letterSpacing={0.01}
          onPointerOver={(event) => {
            event.stopPropagation();
            onHover(word);
          }}
          onPointerOut={(event) => {
            event.stopPropagation();
            onLeave();
          }}
        >
          {word.shortLabel}
        </Text>
      </Billboard>
    </group>
  );
}

function KnowledgeCloudScene({
  labels,
  particles,
  onHover,
  onLeave,
}: {
  labels: RankedNode[];
  particles: ParticleNode[];
  onHover: (word: RankedNode) => void;
  onLeave: () => void;
}) {
  const rigRef = useRef<THREE.Group>(null);

  useFrame((state, delta) => {
    if (!rigRef.current) return;
    const targetX = state.pointer.y * 0.18;
    const targetY = state.pointer.x * 0.28;
    rigRef.current.rotation.x = THREE.MathUtils.damp(rigRef.current.rotation.x, targetX, 4, delta);
    rigRef.current.rotation.y = THREE.MathUtils.damp(rigRef.current.rotation.y, targetY, 4, delta);
  });

  return (
    <>
      <fog attach="fog" args={["#f8fbff", 9, 18]} />
      <ambientLight intensity={1.05} />
      <directionalLight position={[6, 8, 6]} intensity={1.7} color="#f8fafc" />
      <pointLight position={[-5, -3, 5]} intensity={1.4} color="#7dd3fc" />
      <group ref={rigRef}>
        <mesh>
          <icosahedronGeometry args={[1.28, 5]} />
          <meshStandardMaterial
            color="#f8fafc"
            emissive="#7dd3fc"
            emissiveIntensity={0.26}
            roughness={0.18}
            metalness={0.08}
            transparent
            opacity={0.96}
          />
        </mesh>
        <mesh rotation={[Math.PI / 2, 0, 0]}>
          <torusGeometry args={[1.9, 0.03, 18, 120]} />
          <meshBasicMaterial color="#93c5fd" transparent opacity={0.34} />
        </mesh>
        <mesh rotation={[Math.PI / 3, Math.PI / 7, 0]}>
          <torusGeometry args={[2.55, 0.02, 18, 120]} />
          <meshBasicMaterial color="#c4b5fd" transparent opacity={0.22} />
        </mesh>
        <ParticleShell particles={particles} />
        {labels.map((word) => (
          <WordOrbit
            key={word.id}
            word={word}
            onHover={onHover}
            onLeave={onLeave}
          />
        ))}
      </group>
    </>
  );
}

export function WordCloud3D({ subjectLabel, graph, height }: WordCloud3DProps) {
  const [hoveredWord, setHoveredWord] = useState<RankedNode | null>(null);
  const visualState = useMemo(() => buildVisualState(graph), [graph]);
  const containerStyle =
    typeof height === "number"
      ? { height: `${height}px` }
      : { height: height ?? "calc(100vh - 14rem)" };

  if (visualState.nodeCount === 0) {
    return (
      <div
        className="flex items-center justify-center rounded-[28px] border border-slate-200 bg-[radial-gradient(circle_at_top,#ffffff_0%,#eff6ff_45%,#e2e8f0_100%)]"
        style={containerStyle}
      >
        <div className="text-center text-slate-500">
          <p className="text-sm font-semibold text-slate-700">暂无知识图谱数据</p>
          <p className="mt-2 text-xs text-slate-500">完成 digest 构建后，这里会生成空间词云与核心知识分布。</p>
        </div>
      </div>
    );
  }

  return (
    <div
      className="relative overflow-hidden rounded-[30px] border border-slate-200 bg-[linear-gradient(180deg,#ffffff_0%,#f8fbff_45%,#eef6ff_100%)] shadow-[0_24px_70px_-44px_rgba(15,23,42,0.35)]"
      style={containerStyle}
    >
      <div className="pointer-events-none absolute inset-0">
        <div className="absolute inset-x-0 top-0 h-28 bg-[linear-gradient(180deg,rgba(255,255,255,0.96)_0%,rgba(255,255,255,0)_100%)]" />
        <div className="absolute left-1/2 top-[18%] h-52 w-52 -translate-x-1/2 rounded-full bg-sky-200/45 blur-3xl" />
        <div className="absolute right-[12%] top-[26%] h-44 w-44 rounded-full bg-indigo-200/35 blur-3xl" />
        <div className="absolute left-[10%] bottom-[18%] h-40 w-40 rounded-full bg-cyan-200/35 blur-3xl" />
        <div className="absolute inset-0 opacity-[0.18]" style={{ backgroundImage: "linear-gradient(rgba(148,163,184,0.28) 1px, transparent 1px), linear-gradient(90deg, rgba(148,163,184,0.28) 1px, transparent 1px)", backgroundSize: "40px 40px" }} />
      </div>

      <div className="absolute inset-0">
        <Canvas camera={{ position: [0, 0, 9.6], fov: 42 }}>
          <KnowledgeCloudScene
            labels={visualState.labels}
            particles={visualState.particles}
            onHover={setHoveredWord}
            onLeave={() => setHoveredWord(null)}
          />
        </Canvas>
      </div>

      <div className="pointer-events-none absolute inset-x-0 top-0 flex items-start justify-between p-5">
        <div className="rounded-full border border-slate-200/70 bg-white/80 px-3 py-1 text-[11px] font-medium tracking-[0.24em] text-slate-500 backdrop-blur">
          AITeachMe KNOWLEDGE SPACE
        </div>
        {hoveredWord ? (
          <div className="max-w-[240px] rounded-2xl border border-slate-200/80 bg-white/88 px-4 py-3 text-right shadow-sm backdrop-blur">
            <p className="text-[11px] uppercase tracking-[0.24em] text-slate-400">{hoveredWord.nodeType}</p>
            <p className="mt-1 text-sm font-semibold text-slate-900">{hoveredWord.label}</p>
            <p className="mt-1 text-xs text-slate-500">连接度 {hoveredWord.degree} · 显著性 {Math.round(hoveredWord.salience * 100)}%</p>
          </div>
        ) : (
          <div className="rounded-full border border-slate-200/70 bg-white/70 px-3 py-1 text-xs text-slate-500 backdrop-blur">
            悬停查看完整标签
          </div>
        )}
      </div>

      <div className="pointer-events-none absolute left-1/2 top-1/2 z-10 flex -translate-x-1/2 -translate-y-1/2 flex-col items-center">
        <div className="rounded-full border border-white/80 bg-white/72 px-6 py-2 text-[11px] tracking-[0.28em] text-slate-500 shadow-[0_18px_40px_-28px_rgba(14,116,144,0.35)] backdrop-blur">
          SUBJECT CORE
        </div>
        <h3 className="mt-4 max-w-[320px] text-center text-3xl font-semibold tracking-tight text-slate-900">
          {subjectLabel}
        </h3>
        <p className="mt-2 text-center text-sm text-slate-500">
          仅展示最重要的 {visualState.labels.length} 个知识词，弱信号退化为粒子层
        </p>
      </div>

      <div className="pointer-events-none absolute inset-x-0 bottom-0 flex flex-wrap items-end justify-between gap-4 p-5">
        <div className="rounded-2xl border border-white/70 bg-white/82 px-4 py-3 shadow-sm backdrop-blur">
          <p className="text-xs font-medium uppercase tracking-[0.2em] text-slate-400">Graph Snapshot</p>
          <p className="mt-2 text-sm text-slate-600">
            {visualState.nodeCount} nodes · {visualState.edgeCount} edges
          </p>
        </div>
        <div className="flex flex-wrap gap-2">
          {visualState.topTypes.map(([type, count]) => (
            <div
              key={type}
              className="rounded-full border border-white/70 bg-white/82 px-3 py-1.5 text-xs text-slate-600 shadow-sm backdrop-blur"
            >
              <span
                className="mr-2 inline-block h-2 w-2 rounded-full"
                style={{ backgroundColor: TYPE_COLORS[type] ?? DEFAULT_COLOR }}
              />
              {type} · {count}
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}

export default WordCloud3D;
