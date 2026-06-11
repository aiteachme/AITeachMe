import { Suspense, useEffect, useMemo, useRef, useState } from "react";
import { Canvas, useFrame, useThree } from "@react-three/fiber";
import { Billboard, Line, OrbitControls, Stars, Text } from "@react-three/drei";
import * as THREE from "three";

import { relationTone, truncateGraphLabel } from "../knowledgeGraphVisual";
import type { GraphInsightModel, NodeInsight } from "./insightsCore";
import { nodeStyle, nodeTypeLabel, percentText } from "./insightsCore";
import { ChartPanel } from "./sharedPrimitives";

type GalaxyNode = NodeInsight & {
  position: [number, number, number];
  color: string;
  label: string;
  labelWidth: number;
  defaultLabelVisible: boolean;
  radius: number;
  type: string;
  clusterIndex: number;
};

type GalaxyCluster = {
  type: string;
  label: string;
  color: string;
  count: number;
  radius: number;
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
  "topic",
  "concept",
  "formula_model",
  "principle",
  "procedure",
  "skill",
  "misconception",
  "application_case",
  "resource",
];

const GOLDEN_ANGLE = Math.PI * (3 - Math.sqrt(5));

function stableUnit(seed: number, salt: number): number {
  let value = Math.imul((seed || 1) ^ Math.imul(salt + 17, 374761393), 668265263);
  value = (value ^ (value >>> 13)) >>> 0;
  value = Math.imul(value, 2246822519) >>> 0;
  return value / 4294967295;
}

function labelWidth(label: string): number {
  let width = 0;
  for (const char of label) {
    width += /[\u4e00-\u9fff]/.test(char) ? 0.2 : 0.105;
  }
  return Math.min(2.2, Math.max(0.86, width + 0.34));
}

function clusterPosition(index: number, total: number, count: number, nodeCount: number): [number, number, number] {
  if (total <= 1) return [0, 0, 0];
  const ratio = (index + 0.5) / total;
  const polar = Math.acos(1 - 2 * ratio);
  const theta = index * GOLDEN_ANGLE + 0.7;
  const distance = 5.4 + Math.sqrt(count / Math.max(1, nodeCount)) * 5.4 + Math.min(2.2, total * 0.22);
  const horizontal = Math.sin(polar) * distance;
  return [
    Math.cos(theta) * horizontal,
    Math.cos(polar) * distance * 0.76,
    Math.sin(theta) * horizontal,
  ];
}

function buildGalaxy(model: GraphInsightModel): {
  nodes: GalaxyNode[];
  edges: GalaxyEdge[];
  clusters: GalaxyCluster[];
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
  const clusters: GalaxyCluster[] = types.map((type, index) => {
    const style = nodeStyle(type);
    const count = nodesByType.get(type)?.length ?? 0;
    return {
      type,
      label: nodeTypeLabel(type),
      color: style.fill,
      count,
      radius: Math.max(1.25, 1.08 + Math.sqrt(count) * 0.26),
      position: clusterPosition(index, totalTypes, count, model.nodeCount),
    };
  });

  const clusterByType = new Map(clusters.map((cluster, index) => [cluster.type, { cluster, index }]));
  const galaxyNodes: GalaxyNode[] = [];

  for (const cluster of clusters) {
    const clusterMeta = clusterByType.get(cluster.type);
    const bucket = (nodesByType.get(cluster.type) ?? []).slice().sort((left, right) => right.degree - left.degree);
    const visibleBudget = bucket.length > 18 ? 5 : bucket.length > 8 ? 3 : 2;
    bucket.forEach((node, nodeIndex) => {
      const type = String(node.knowledge_unit_type || "other");
      const style = nodeStyle(type);
      const label = truncateGraphLabel(node.canonical_name, nodeIndex < 2 ? 10 : 8);
      const rankRatio = bucket.length > 1 ? nodeIndex / (bucket.length - 1) : 0.5;
      const distance = cluster.radius * (0.24 + Math.pow(rankRatio, 0.58) * 1.02);
      const theta = nodeIndex * GOLDEN_ANGLE + stableUnit(node.id, 19) * Math.PI * 2;
      const z = 1 - stableUnit(node.id, 31) * 2;
      const planar = Math.sqrt(Math.max(0, 1 - z * z));
      const jitter = (stableUnit(node.id, 47) - 0.5) * cluster.radius * 0.14;
      const localX = Math.cos(theta) * planar * (distance + jitter);
      const localY = z * distance * 0.86 + (stableUnit(node.id, 71) - 0.5) * 0.28;
      const localZ = Math.sin(theta) * planar * (distance + jitter);

      galaxyNodes.push({
        ...node,
        type,
        color: style.fill,
        label,
        labelWidth: labelWidth(label),
        defaultLabelVisible: nodeIndex < visibleBudget || node.issueScore >= 3.2 || node.degree >= 7,
        radius: 0.1 + Math.sqrt(Math.max(1, node.degree)) * 0.048 + (type === "concept" ? 0.035 : 0),
        clusterIndex: clusterMeta?.index ?? 0,
        position: [
          cluster.position[0] + localX,
          cluster.position[1] + localY,
          cluster.position[2] + localZ,
        ],
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
      const crossCluster = source.clusterIndex !== target.clusterIndex;
      const score = confidence * 2 + Math.sqrt(source.degree + target.degree + 1) * 0.3 + (crossCluster ? 0.7 : 0);
      return { edge, source, target, confidence, crossCluster, score };
    })
    .filter((item): item is NonNullable<typeof item> => Boolean(item))
    .sort((left, right) => right.score - left.score);

  const galaxyEdges = edgeCandidates.map((item): GalaxyEdge => {
    const relationType = String(item.edge.edge_type || "related");
    return {
      id: item.edge.id,
      source: item.source,
      target: item.target,
      relationType,
      color: relationTone(relationType),
      opacity: 0.52 + item.confidence * 0.34 + (item.crossCluster ? 0.08 : 0),
      width: 0.85 + item.confidence * 1.15 + (item.crossCluster ? 0.24 : 0),
    };
  });

  return { nodes: galaxyNodes, edges: galaxyEdges, clusters };
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
  const visualScale = size.width < 640 ? 0.52 : size.width < 900 ? 0.7 : 0.94;

  useFrame((_, delta) => {
    if (!groupRef.current || hoveredId || selectedId) return;
    groupRef.current.rotation.y += delta * 0.075;
  });

  const activeId = hoveredId ?? selectedId;
  const activeEdges = useMemo(() => {
    if (!activeId) return [];
    return galaxy.edges
      .filter((edge) => edge.source.id === activeId || edge.target.id === activeId)
      .slice(0, 10);
  }, [activeId, galaxy.edges]);

  const relatedIds = useMemo(() => {
    if (!activeId) return new Set<number>();
    const set = new Set<number>([activeId]);
    for (const edge of activeEdges) {
      set.add(edge.source.id);
      set.add(edge.target.id);
    }
    return set;
  }, [activeEdges, activeId]);

  return (
    <group ref={groupRef} scale={visualScale} rotation={[-0.5, 0.28, 0.04]}>
      <ambientLight intensity={0.86} />
      <pointLight position={[8, 9, 11]} intensity={3.6} color="#e0f2fe" />
      <pointLight position={[-9, -6, -7]} intensity={1.45} color="#c4b5fd" />

      {galaxy.clusters.map((cluster) => (
        <group key={cluster.type} position={cluster.position}>
          <mesh>
            <sphereGeometry args={[cluster.radius * 1.08, 16, 10]} />
            <meshBasicMaterial color={cluster.color} transparent opacity={0.045} depthWrite={false} />
          </mesh>
          <mesh>
            <sphereGeometry args={[cluster.radius * 1.12, 10, 6]} />
            <meshBasicMaterial color={cluster.color} transparent opacity={0.06} wireframe depthWrite={false} />
          </mesh>
          <Billboard position={[0, cluster.radius + 0.6, 0]}>
            <mesh>
              <planeGeometry args={[1.24, 0.34]} />
              <meshBasicMaterial color={cluster.color} transparent opacity={0.22} depthWrite={false} />
            </mesh>
            <Text position={[0, 0, 0.01]} fontSize={0.12} color="#f8fafc" anchorX="center" anchorY="middle">
              {cluster.label} {cluster.count}
            </Text>
          </Billboard>
        </group>
      ))}

      {activeEdges.map((edge) => (
        <Line
          key={edge.id}
          points={[edge.source.position, edge.target.position]}
          color={edge.color}
          lineWidth={edge.width}
          transparent
          opacity={edge.opacity}
        />
      ))}

      {galaxy.nodes.map((node) => {
        const active = activeId === node.id;
        const related = activeId ? relatedIds.has(node.id) : true;
        const showLabel = active || related || node.defaultLabelVisible;
        const labelOpacity = active ? 1 : related ? 0.86 : 0.46;
        const label = active ? truncateGraphLabel(node.canonical_name, 14) : node.label;
        return (
          <group key={node.id} position={node.position}>
            <mesh
              scale={active ? 2.25 : related ? 1.55 : 1}
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
              <meshBasicMaterial
                color={node.color}
                transparent
                opacity={showLabel ? 0.08 : related ? 0.42 : 0.16}
                depthWrite={false}
              />
            </mesh>
            {showLabel ? (
              <Billboard position={[0, node.radius + 0.08, 0]}>
                <mesh
                  onPointerOver={(event) => {
                    event.stopPropagation();
                    onHover(node.id);
                  }}
                  onPointerOut={() => onHover(null)}
                  onClick={(event) => {
                    event.stopPropagation();
                    onSelect(selectedId === node.id ? null : node.id);
                  }}
                  scale={active ? 1.1 : 1}
                >
                  <planeGeometry args={[active ? Math.min(2.6, node.labelWidth + 0.4) : node.labelWidth, active ? 0.4 : 0.28]} />
                  <meshBasicMaterial
                    color={active ? "#f8fafc" : node.color}
                    transparent
                    opacity={labelOpacity}
                    depthWrite={false}
                  />
                </mesh>
                <Text
                  position={[0, 0, 0.01]}
                  fontSize={active ? 0.15 : 0.105}
                  color={active ? "#0f172a" : "#f8fafc"}
                  anchorX="center"
                  anchorY="middle"
                >
                  {label}
                </Text>
              </Billboard>
            ) : null}
          </group>
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
      perspectiveCamera.position.set(5, 9.4, 32);
      perspectiveCamera.fov = 54;
    } else if (size.width < 900) {
      perspectiveCamera.position.set(6, 8.8, 26);
      perspectiveCamera.fov = 52;
    } else {
      perspectiveCamera.position.set(7.4, 8.2, 21);
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

  return (
    <div className="h-full min-h-0">
      <ChartPanel
        title="3D 知识星团"
        meta={`${model.nodeCount} 知识点 · ${galaxy.clusters.length} 类型`}
        description="方块是关键知识点；颜色代表类型；点击可固定查看邻接关系。"
        className="flex h-full min-h-0 flex-col overflow-hidden"
        bodyClassName="flex min-h-0 flex-1"
      >
        <div className="relative min-h-0 flex-1 bg-slate-950">
          <Canvas
            camera={{ position: [7.4, 8.2, 21], fov: 48 }}
            dpr={[1, 1.25]}
            gl={{ antialias: true, powerPreference: "high-performance" }}
            performance={{ min: 0.55 }}
            onPointerMissed={() => setSelectedId(null)}
          >
            <color attach="background" args={["#050816"]} />
            <fog attach="fog" args={["#050816", 16, 44]} />
            <GalaxyCameraRig />
            <Stars radius={92} depth={44} count={180} factor={2.2} saturation={0} fade speed={0.25} />
            <Suspense fallback={null}>
              <RotatingGalaxy
                galaxy={galaxy}
                hoveredId={hoveredId}
                selectedId={selectedId}
                onHover={setHoveredId}
                onSelect={setSelectedId}
              />
            </Suspense>
            <OrbitControls enablePan={false} enableDamping dampingFactor={0.08} minDistance={9} maxDistance={42} />
          </Canvas>

          <div className="pointer-events-none absolute left-3 top-3 flex max-w-[520px] flex-wrap gap-1.5 sm:left-4 sm:top-4">
            {galaxy.clusters.slice(0, 7).map((cluster) => (
              <span
                key={cluster.type}
                className="inline-flex h-6 items-center gap-1.5 rounded-full border border-white/10 bg-white/5 px-2 text-[10px] font-semibold text-white/75 shadow-sm backdrop-blur"
              >
                <span className="h-1.5 w-1.5 rounded-full" style={{ backgroundColor: cluster.color }} />
                <span className="hidden sm:inline">{cluster.label}</span>
                <span className="tabular-nums">{cluster.count}</span>
              </span>
            ))}
          </div>

          {activeNode ? (
            <div className="pointer-events-none absolute bottom-4 left-4 max-w-[300px] rounded-lg border border-white/10 bg-slate-950/76 px-3 py-2.5 text-slate-100 shadow-xl backdrop-blur">
              <p className="truncate text-sm font-semibold">
                {selectedId === activeNode.id ? "已固定 · " : ""}
                {truncateGraphLabel(activeNode.canonical_name, 24)}
              </p>
              <p className="mt-1 text-[11px] leading-4 text-slate-300">
                {nodeTypeLabel(activeNode.type)} · {activeNode.degree} 连 · {percentText(Number(activeNode.confidence || 0))}
              </p>
            </div>
          ) : (
            <div className="pointer-events-none absolute bottom-4 left-4 rounded-full border border-white/10 bg-slate-950/60 px-3 py-1.5 text-[11px] text-slate-300 shadow-xl backdrop-blur">
              拖动旋转 · 点击固定
            </div>
          )}
        </div>
      </ChartPanel>
    </div>
  );
}
