import { Suspense, useEffect, useMemo, useRef, useState } from "react";
import { Canvas, useFrame, useThree } from "@react-three/fiber";
import { Line, OrbitControls, Stars } from "@react-three/drei";
import { Bloom, EffectComposer } from "@react-three/postprocessing";
import * as THREE from "three";

import { relationTone, truncateGraphLabel } from "../knowledgeGraphVisual";
import type { GraphInsightModel, NodeInsight } from "./insightsCore";
import { nodeStyle, nodeTypeLabel, percentText, relationLabel } from "./insightsCore";
import { CategoryBar, ChartPanel } from "./sharedPrimitives";

type GalaxyNode = NodeInsight & {
  position: [number, number, number];
  color: string;
  radius: number;
  type: string;
  orbitIndex: number;
};

type GalaxyOrbit = {
  type: string;
  label: string;
  color: string;
  count: number;
  radius: number;
  rotation: [number, number, number];
  position: [number, number, number];
};

type GalaxyEdge = {
  id: number;
  source: GalaxyNode;
  target: GalaxyNode;
  color: string;
  opacity: number;
  width: number;
  relationType: string;
};

const TYPE_ORDER = [
  "core_knowledge",
  "principle_reasoning",
  "method_demo",
  "practice_assessment",
  "knowledge_organization",
  "explanation_support",
  "application_extension",
];

function buildGalaxy(model: GraphInsightModel): {
  nodes: GalaxyNode[];
  edges: GalaxyEdge[];
  orbits: GalaxyOrbit[];
} {
  const nodesByType = new Map<string, NodeInsight[]>();
  for (const node of model.nodes) {
    const type = String(node.knowledge_unit_type || "other");
    nodesByType.set(type, [...(nodesByType.get(type) ?? []), node]);
  }

  const types = TYPE_ORDER.filter((type) => nodesByType.has(type));
  for (const type of nodesByType.keys()) {
    if (!types.includes(type)) types.push(type);
  }

  const totalTypes = Math.max(1, types.length);
  const orbits: GalaxyOrbit[] = types.map((type, index) => {
    const style = nodeStyle(type);
    const count = nodesByType.get(type)?.length ?? 0;
    const angle = (index / totalTypes) * Math.PI * 2;
    const distance = totalTypes <= 1 ? 0 : 2.2 + Math.sqrt(count / Math.max(1, model.nodeCount)) * 3.2;
    return {
      type,
      label: nodeTypeLabel(type),
      color: style.fill,
      count,
      radius: 1.6 + Math.sqrt(count) * 0.42,
      rotation: [Math.PI / 2.5, angle * 0.28, angle] as [number, number, number],
      position: [Math.cos(angle) * distance, (index % 3 - 1) * 0.44, Math.sin(angle) * distance] as [
        number,
        number,
        number,
      ],
    };
  });

  const orbitByType = new Map(orbits.map((orbit, index) => [orbit.type, { orbit, index }]));
  const galaxyNodes: GalaxyNode[] = [];

  for (const orbit of orbits) {
    const orbitMeta = orbitByType.get(orbit.type);
    const bucket = (nodesByType.get(orbit.type) ?? []).slice().sort((left, right) => right.degree - left.degree);
    bucket.forEach((node, nodeIndex) => {
      const fraction = bucket.length > 1 ? nodeIndex / (bucket.length - 1) : 0.5;
      const ring = 0.48 + orbit.radius * (0.28 + fraction * 0.72);
      const theta = nodeIndex * 2.399963 + (node.id % 13) * 0.17;
      const vertical = ((node.id % 9) - 4) * 0.075;
      const type = String(node.knowledge_unit_type || "other");
      const style = nodeStyle(type);
      const localX = Math.cos(theta) * ring;
      const localZ = Math.sin(theta) * ring;
      galaxyNodes.push({
        ...node,
        type,
        color: style.fill,
        radius: 0.09 + Math.sqrt(Math.max(1, node.degree)) * 0.045 + (type === "core_knowledge" ? 0.04 : 0),
        orbitIndex: orbitMeta?.index ?? 0,
        position: [orbit.position[0] + localX, orbit.position[1] + vertical, orbit.position[2] + localZ],
      });
    });
  }

  const nodeMap = new Map(galaxyNodes.map((node) => [node.id, node]));
  const edgeCandidates = model.edges
    .map((edge) => {
      const source = nodeMap.get(edge.source_node_id);
      const target = nodeMap.get(edge.target_node_id);
      if (!source || !target) return null;
      const confidence = Math.max(0, Math.min(1, Number(edge.confidence || 0)));
      const crossOrbit = source.orbitIndex !== target.orbitIndex;
      const score = confidence * 2 + Math.sqrt(source.degree + target.degree + 1) * 0.3 + (crossOrbit ? 0.6 : 0);
      return { edge, source, target, confidence, crossOrbit, score };
    })
    .filter((item): item is NonNullable<typeof item> => Boolean(item))
    .sort((left, right) => right.score - left.score);

  const edgeBudget = Math.min(edgeCandidates.length, Math.max(90, Math.round(galaxyNodes.length * 1.35)));
  const galaxyEdges = edgeCandidates.slice(0, edgeBudget).map((item): GalaxyEdge => {
    const relationType = String(item.edge.edge_type || "related");
    return {
      id: item.edge.id,
      source: item.source,
      target: item.target,
      relationType,
      color: relationTone(relationType),
      opacity: 0.18 + item.confidence * 0.5 + (item.crossOrbit ? 0.12 : 0),
      width: 0.7 + item.confidence * 1.4 + (item.crossOrbit ? 0.3 : 0),
    };
  });

  return { nodes: galaxyNodes, edges: galaxyEdges, orbits };
}

function RotatingGalaxy({
  galaxy,
  hoveredId,
  selectedId,
  onHover,
  onSelect,
}: {
  galaxy: ReturnType<typeof buildGalaxy>;
  hoveredId: number | null;
  selectedId: number | null;
  onHover: (nodeId: number | null) => void;
  onSelect: (nodeId: number | null) => void;
}) {
  const groupRef = useRef<THREE.Group>(null);
  const { size } = useThree();
  const visualScale = size.width < 640 ? 0.52 : size.width < 900 ? 0.72 : 1;
  useFrame((_, delta) => {
    if (!groupRef.current || hoveredId || selectedId) return;
    groupRef.current.rotation.y += delta * 0.055;
  });

  const activeId = hoveredId ?? selectedId;
  const relatedIds = useMemo(() => {
    if (!activeId) return new Set<number>();
    const set = new Set<number>([activeId]);
    for (const edge of galaxy.edges) {
      if (edge.source.id === activeId) set.add(edge.target.id);
      if (edge.target.id === activeId) set.add(edge.source.id);
    }
    return set;
  }, [activeId, galaxy.edges]);

  return (
    <group ref={groupRef} scale={visualScale} rotation={[-0.38, 0.12, 0]}>
      <ambientLight intensity={0.8} />
      <pointLight position={[7, 8, 10]} intensity={3.8} color="#dbeafe" />
      <pointLight position={[-10, -4, -8]} intensity={1.6} color="#a78bfa" />

      {galaxy.orbits.map((orbit) => (
        <group key={orbit.type} position={orbit.position} rotation={orbit.rotation}>
          <mesh>
            <torusGeometry args={[orbit.radius, 0.012, 8, 150]} />
            <meshBasicMaterial color={orbit.color} transparent opacity={0.34} />
          </mesh>
          <mesh>
            <torusGeometry args={[orbit.radius * 0.66, 0.006, 8, 110]} />
            <meshBasicMaterial color={orbit.color} transparent opacity={0.13} />
          </mesh>
        </group>
      ))}

      {galaxy.edges.map((edge) => {
        const active = activeId && relatedIds.has(edge.source.id) && relatedIds.has(edge.target.id);
        const dimmed = activeId && !active;
        return (
          <Line
            key={edge.id}
            points={[edge.source.position, edge.target.position]}
            color={edge.color}
            lineWidth={active ? edge.width + 1.2 : edge.width}
            transparent
            opacity={dimmed ? 0.05 : active ? 0.92 : edge.opacity}
          />
        );
      })}

      {galaxy.nodes.map((node) => {
        const active = activeId === node.id;
        const related = activeId ? relatedIds.has(node.id) : true;
        return (
          <mesh
            key={node.id}
            position={node.position}
            scale={active ? 1.5 : related ? 1 : 0.72}
            onPointerOver={(event) => {
              event.stopPropagation();
              onHover(node.id);
            }}
            onPointerOut={() => onHover(null)}
            onClick={(event) => {
              event.stopPropagation();
              onSelect(selectedId === node.id ? null : node.id);
            }}
          >
            <sphereGeometry args={[node.radius, 24, 16]} />
            <meshStandardMaterial
              color={node.color}
              emissive={node.color}
              emissiveIntensity={active ? 1.25 : 0.58 + Math.min(0.5, node.degree * 0.035)}
              roughness={0.42}
              metalness={0.1}
              transparent
              opacity={related ? 0.98 : 0.22}
            />
          </mesh>
        );
      })}
    </group>
  );
}

function GalaxyCameraRig() {
  const { camera, size } = useThree();

  useEffect(() => {
    const perspectiveCamera = camera as THREE.PerspectiveCamera;
    if (size.width < 640) {
      perspectiveCamera.position.set(0, 8.5, 28);
      perspectiveCamera.fov = 54;
    } else if (size.width < 900) {
      perspectiveCamera.position.set(0, 8, 22);
      perspectiveCamera.fov = 52;
    } else {
      perspectiveCamera.position.set(0, 7, 16);
      perspectiveCamera.fov = 48;
    }
    perspectiveCamera.updateProjectionMatrix();
  }, [camera, size.width]);

  return null;
}

export function AtlasGalaxyView({ model }: { model: GraphInsightModel }) {
  const galaxy = useMemo(() => buildGalaxy(model), [model]);
  const [hoveredId, setHoveredId] = useState<number | null>(null);
  const [selectedId, setSelectedId] = useState<number | null>(null);
  const activeNode = useMemo(() => {
    const activeId = hoveredId ?? selectedId;
    return activeId ? galaxy.nodes.find((node) => node.id === activeId) ?? null : null;
  }, [galaxy.nodes, hoveredId, selectedId]);
  const relationSegments = model.relationItems.slice(0, 6).map((relation) => ({
    key: relation.type,
    label: relation.label,
    color: relation.color,
    count: relation.count,
  }));

  return (
    <div className="grid gap-4">
      <ChartPanel
        title="3D 知识星云"
        meta={`${model.nodeCount} 节点 · ${model.edgeCount} 关系 · ${galaxy.orbits.length} 类知识`}
        description="星盘代表知识类型，节点大小代表连接数，亮线代表高价值关系。拖拽旋转，悬停查看节点。"
        className="overflow-hidden"
      >
        <div className="relative h-[680px] bg-slate-950">
          <Canvas camera={{ position: [0, 7, 16], fov: 48 }} dpr={[1, 1.6]} gl={{ antialias: true }}>
            <color attach="background" args={["#050816"]} />
            <fog attach="fog" args={["#050816", 18, 46]} />
            <GalaxyCameraRig />
            <Stars radius={90} depth={42} count={900} factor={3.4} saturation={0} fade speed={0.35} />
            <Suspense fallback={null}>
              <RotatingGalaxy
                galaxy={galaxy}
                hoveredId={hoveredId}
                selectedId={selectedId}
                onHover={setHoveredId}
                onSelect={setSelectedId}
              />
            </Suspense>
            <OrbitControls enablePan={false} enableDamping dampingFactor={0.08} minDistance={7} maxDistance={34} />
            <EffectComposer>
              <Bloom intensity={0.78} luminanceThreshold={0.2} luminanceSmoothing={0.22} mipmapBlur />
            </EffectComposer>
          </Canvas>

          <div className="pointer-events-none absolute left-3 top-3 w-[142px] rounded-lg border border-white/10 bg-slate-950/72 p-3 text-slate-100 shadow-xl backdrop-blur sm:left-4 sm:top-4 sm:w-[260px]">
            <p className="text-xs font-semibold">知识类型</p>
            <div className="mt-2 grid gap-1.5">
              {galaxy.orbits.slice(0, 7).map((orbit) => (
                <div key={orbit.type} className="flex items-center justify-between gap-2 text-[11px]">
                  <span className="flex items-center gap-1.5">
                    <span className="h-2 w-2 rounded-full" style={{ backgroundColor: orbit.color }} />
                    {orbit.label}
                  </span>
                  <span className="font-semibold tabular-nums text-slate-300">{orbit.count}</span>
                </div>
              ))}
            </div>
          </div>

          <div className="pointer-events-none absolute right-4 top-4 hidden w-[260px] rounded-lg border border-white/10 bg-slate-950/72 p-3 text-slate-100 shadow-xl backdrop-blur md:block">
            <p className="text-xs font-semibold">关系光谱</p>
            <div className="mt-2">
              <CategoryBar segments={relationSegments} height={9} showLegend={false} />
            </div>
            <div className="mt-2 grid gap-1">
              {relationSegments.slice(0, 5).map((segment) => (
                <div key={segment.key} className="flex items-center justify-between gap-2 text-[11px] text-slate-300">
                  <span className="flex items-center gap-1.5">
                    <span className="h-2 w-2 rounded-full" style={{ backgroundColor: segment.color }} />
                    {segment.label}
                  </span>
                  <span className="font-semibold tabular-nums">{segment.count}</span>
                </div>
              ))}
            </div>
          </div>

          {activeNode ? (
            <div className="pointer-events-none absolute bottom-4 left-4 max-w-[360px] rounded-lg border border-white/10 bg-slate-950/78 p-3 text-slate-100 shadow-xl backdrop-blur">
              <p className="truncate text-sm font-semibold">{truncateGraphLabel(activeNode.canonical_name, 22)}</p>
              <p className="mt-1 text-xs text-slate-300">
                {nodeTypeLabel(activeNode.type)} · 连接 {activeNode.degree} · 置信 {percentText(Number(activeNode.confidence || 0))}
              </p>
              {activeNode.issueReasons.length ? (
                <p className="mt-2 text-xs leading-5 text-amber-200">{activeNode.issueReasons[0]}</p>
              ) : null}
            </div>
          ) : (
            <div className="pointer-events-none absolute bottom-4 left-4 rounded-lg border border-white/10 bg-slate-950/60 px-3 py-2 text-[11px] text-slate-300 shadow-xl backdrop-blur">
              拖拽旋转 · 滚轮缩放 · 悬停查看连接
            </div>
          )}
        </div>
      </ChartPanel>

      <div className="grid gap-4 xl:grid-cols-[minmax(0,0.72fr)_minmax(0,1.28fr)]">
        <ChartPanel title="主导关系" description="只看前几类关系，判断图谱更像路径、讲解、推理还是训练。">
          <div className="grid gap-2 p-4">
            {model.relationItems.slice(0, 5).map((relation) => (
              <div key={relation.type} className="flex items-center justify-between gap-3 rounded-lg bg-slate-50 px-3 py-2 text-xs dark:bg-slate-900/70">
                <span className="flex items-center gap-2 text-slate-700 dark:text-slate-200">
                  <span className="h-2 w-2 rounded-full" style={{ backgroundColor: relation.color }} />
                  <strong>{relationLabel(relation.type)}</strong>
                </span>
                <span className="font-semibold tabular-nums text-slate-500 dark:text-slate-400">
                  {relation.count} · {percentText(relation.percent)}
                </span>
              </div>
            ))}
          </div>
        </ChartPanel>
        <ChartPanel title="结构提醒" description="保留最直接的下一步，不把指标堆满页面。">
          <div className="grid gap-2 p-4">
            {model.issues.slice(0, 2).map((issue) => (
              <div key={issue.title} className="rounded-lg border border-slate-200 bg-slate-50 px-3 py-2.5 dark:border-slate-800 dark:bg-slate-900/70">
                <p className="text-sm font-semibold text-slate-900 dark:text-slate-100">{issue.title}</p>
                <p className="mt-1 text-xs leading-5 text-slate-500 dark:text-slate-400">{issue.detail}</p>
              </div>
            ))}
            {!model.issues.length ? (
              <div className="rounded-lg border border-emerald-200 bg-emerald-50 px-3 py-2.5 text-sm text-emerald-700 dark:border-emerald-500/30 dark:bg-emerald-500/10 dark:text-emerald-300">
                当前图谱结构已经比较完整。
              </div>
            ) : null}
          </div>
        </ChartPanel>
      </div>
    </div>
  );
}
