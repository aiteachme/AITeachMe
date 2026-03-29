/**
 * WordCloud3D — 3D 交互式词云可视化组件
 *
 * 灵感来源：algo.qq.com 首页粒子词云效果
 * 使用 Three.js + React Three Fiber 实现：
 *   - 大量文字粒子在 3D 空间中漂浮
 *   - 中心区域粒子密集排列，拟合学科名/主题词的字形轮廓
 *   - 支持 OrbitControls 拖拽旋转、缩放
 *   - 粒子颜色、大小、透明度随节点类型和重要度变化
 */

import { useRef, useMemo, useEffect, useState } from "react";
import { Canvas, useFrame } from "@react-three/fiber";
import { OrbitControls, Text } from "@react-three/drei";
import * as THREE from "three";

/* ------------------------------------------------------------------ */
/*  Types                                                              */
/* ------------------------------------------------------------------ */

interface WordCloudNode {
  name: string;
  nodeType: string;
  confidence: number;
}

interface WordCloud3DProps {
  /** 学科名（用于中心大字拟合） */
  subjectLabel: string;
  /** 知识图谱节点列表 */
  nodes: WordCloudNode[];
  /** 容器高度px */
  height?: number;
}

/* ------------------------------------------------------------------ */
/*  Color palette                                                      */
/* ------------------------------------------------------------------ */

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
const ACCENT_COLOR = "#c026d3"; // fuchsia for highlight particles

/* ------------------------------------------------------------------ */
/*  Sample text shape from Canvas 2D                                   */
/* ------------------------------------------------------------------ */

function sampleTextPositions(
  text: string,
  sampleCount: number,
  canvasSize = 512
): [number, number][] {
  const canvas = document.createElement("canvas");
  canvas.width = canvasSize;
  canvas.height = canvasSize;
  const ctx = canvas.getContext("2d")!;

  // 根据文字长度动态调整字号
  const fontSize = text.length <= 2 ? canvasSize * 0.65 : text.length <= 4 ? canvasSize * 0.4 : canvasSize * 0.28;
  ctx.fillStyle = "#000";
  ctx.font = `900 ${fontSize}px "Microsoft YaHei", "PingFang SC", sans-serif`;
  ctx.textAlign = "center";
  ctx.textBaseline = "middle";
  ctx.fillText(text, canvasSize / 2, canvasSize / 2);

  const imageData = ctx.getImageData(0, 0, canvasSize, canvasSize);
  const filledPixels: [number, number][] = [];

  for (let y = 0; y < canvasSize; y += 2) {
    for (let x = 0; x < canvasSize; x += 2) {
      const idx = (y * canvasSize + x) * 4;
      if (imageData.data[idx + 3] > 128) {
        // 归一化到 [-1, 1]
        filledPixels.push([
          (x / canvasSize - 0.5) * 2,
          -(y / canvasSize - 0.5) * 2,
        ]);
      }
    }
  }

  // 从填充像素中随机采样
  const result: [number, number][] = [];
  for (let i = 0; i < sampleCount && filledPixels.length > 0; i++) {
    const idx = Math.floor(Math.random() * filledPixels.length);
    result.push(filledPixels[idx]);
  }
  return result;
}

/* ------------------------------------------------------------------ */
/*  Floating words (漂浮在外围的关键词)                                    */
/* ------------------------------------------------------------------ */

interface FloatingWordData {
  text: string;
  position: [number, number, number];
  color: string;
  size: number;
  opacity: number;
  speed: number;
  phase: number;
}

function FloatingWord({ data }: { data: FloatingWordData }) {
  const ref = useRef<THREE.Group>(null!);
  const initialY = data.position[1];

  useFrame(({ clock }) => {
    if (ref.current) {
      // 缓慢上下浮动
      ref.current.position.y =
        initialY + Math.sin(clock.getElapsedTime() * data.speed + data.phase) * 0.15;
      // 缓慢旋转
      ref.current.rotation.y = Math.sin(clock.getElapsedTime() * 0.1 + data.phase) * 0.08;
    }
  });

  return (
    <group ref={ref} position={data.position}>
      <Text
        fontSize={data.size}
        color={data.color}
        anchorX="center"
        anchorY="middle"
        fillOpacity={data.opacity}
        font="/fonts/noto-sans-sc-bold.woff"
        characters="abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789+-×÷=()[]{}.,;:!?/\\|#@$%^&*~`<>_ÀàÈèÉéÌìÒòÙùáéíóúÁÍÓÚ"
      >
        {data.text}
      </Text>
    </group>
  );
}

/* ------------------------------------------------------------------ */
/*  Center particle cloud (中心粒子拟合字形)                              */
/* ------------------------------------------------------------------ */

function CenterParticles({
  subjectLabel,
  particleCount,
}: {
  subjectLabel: string;
  particleCount: number;
}) {
  const pointsRef = useRef<THREE.Points>(null!);
  const materialRef = useRef<THREE.ShaderMaterial>(null!);

  const { positions, targetPositions, colors, sizes, randoms } =
    useMemo(() => {
      const textPositions = sampleTextPositions(subjectLabel, particleCount);
      const spreadScale = 3.5;

      const positions = new Float32Array(particleCount * 3);
      const targetPositions = new Float32Array(particleCount * 3);
      const colors = new Float32Array(particleCount * 3);
      const sizes = new Float32Array(particleCount);
      const randoms = new Float32Array(particleCount);

      for (let i = 0; i < particleCount; i++) {
        // 起始位置：随机散布
        positions[i * 3] = (Math.random() - 0.5) * 12;
        positions[i * 3 + 1] = (Math.random() - 0.5) * 8;
        positions[i * 3 + 2] = (Math.random() - 0.5) * 6;

        // 目标位置：文字字形 or 随机漫游
        if (i < textPositions.length) {
          targetPositions[i * 3] = textPositions[i][0] * spreadScale;
          targetPositions[i * 3 + 1] = textPositions[i][1] * spreadScale;
          targetPositions[i * 3 + 2] = (Math.random() - 0.5) * 0.6;
        } else {
          // 外围漂浮粒子
          const angle = Math.random() * Math.PI * 2;
          const radius = 3.5 + Math.random() * 5;
          targetPositions[i * 3] = Math.cos(angle) * radius;
          targetPositions[i * 3 + 1] = (Math.random() - 0.5) * 6;
          targetPositions[i * 3 + 2] = Math.sin(angle) * radius * 0.6;
        }

        // 颜色：中心粒子用品红/紫色系，外围粒子用深色
        const isCenterParticle = i < textPositions.length;
        if (isCenterParticle) {
          const hue = 280 + Math.random() * 40; // 紫-品红
          const color = new THREE.Color().setHSL(hue / 360, 0.7 + Math.random() * 0.3, 0.55 + Math.random() * 0.15);
          colors[i * 3] = color.r;
          colors[i * 3 + 1] = color.g;
          colors[i * 3 + 2] = color.b;
        } else {
          const gray = 0.2 + Math.random() * 0.3;
          colors[i * 3] = gray;
          colors[i * 3 + 1] = gray;
          colors[i * 3 + 2] = gray + Math.random() * 0.1;
        }

        sizes[i] = isCenterParticle ? 3.0 + Math.random() * 4.0 : 1.5 + Math.random() * 2.5;
        randoms[i] = Math.random();
      }

      return { positions, targetPositions, colors, sizes, randoms };
    }, [subjectLabel, particleCount]);

  const shaderMaterial = useMemo(() => {
    return new THREE.ShaderMaterial({
      uniforms: {
        uTime: { value: 0 },
        uProgress: { value: 0 },
        uPixelRatio: { value: window.devicePixelRatio },
      },
      vertexShader: `
        attribute vec3 aTarget;
        attribute float aSize;
        attribute float aRandom;
        
        uniform float uTime;
        uniform float uProgress;
        uniform float uPixelRatio;
        
        varying vec3 vColor;
        varying float vOpacity;
        
        void main() {
          vColor = color;
          
          // 从当前位置向目标位置插值
          vec3 pos = mix(position, aTarget, uProgress);
          
          // 添加微小浮动动画
          pos.x += sin(uTime * 0.3 + aRandom * 6.283) * 0.04 * (1.0 - uProgress * 0.5);
          pos.y += cos(uTime * 0.25 + aRandom * 6.283) * 0.05 * (1.0 - uProgress * 0.5);
          pos.z += sin(uTime * 0.2 + aRandom * 3.14) * 0.03;
          
          vec4 mvPosition = modelViewMatrix * vec4(pos, 1.0);
          gl_Position = projectionMatrix * mvPosition;
          
          // 大小随距离衰减
          gl_PointSize = aSize * uPixelRatio * (200.0 / -mvPosition.z);
          gl_PointSize = max(gl_PointSize, 1.0);
          
          // 透明度：远处的粒子更透明
          float dist = length(mvPosition.xyz);
          vOpacity = mix(0.9, 0.3, smoothstep(2.0, 15.0, dist));
        }
      `,
      fragmentShader: `
        varying vec3 vColor;
        varying float vOpacity;
        
        void main() {
          // 圆形粒子
          float dist = length(gl_PointCoord - vec2(0.5));
          if (dist > 0.5) discard;
          
          // 柔和边缘
          float alpha = smoothstep(0.5, 0.15, dist) * vOpacity;
          
          // 微弱辉光
          vec3 glow = vColor * 1.3;
          vec3 finalColor = mix(vColor, glow, smoothstep(0.3, 0.0, dist));
          
          gl_FragColor = vec4(finalColor, alpha);
        }
      `,
      transparent: true,
      depthWrite: false,
      blending: THREE.AdditiveBlending,
      vertexColors: true,
    });
  }, []);

  // 动画进度 (0 → 1)
  const progressRef = useRef(0);

  useFrame(({ clock }) => {
    if (materialRef.current) {
      materialRef.current.uniforms.uTime.value = clock.getElapsedTime();

      // 缓慢聚合到目标位置
      progressRef.current = Math.min(1.0, progressRef.current + 0.003);
      const eased =
        progressRef.current < 0.5
          ? 4 * progressRef.current ** 3
          : 1 - (-2 * progressRef.current + 2) ** 3 / 2;
      materialRef.current.uniforms.uProgress.value = eased;
    }
  });

  const geometryRef = useRef<THREE.BufferGeometry>(null!);

  useEffect(() => {
    const geom = geometryRef.current;
    if (!geom) return;
    geom.setAttribute("position", new THREE.BufferAttribute(positions, 3));
    geom.setAttribute("color", new THREE.BufferAttribute(colors, 3));
    geom.setAttribute("aTarget", new THREE.BufferAttribute(targetPositions, 3));
    geom.setAttribute("aSize", new THREE.BufferAttribute(sizes, 1));
    geom.setAttribute("aRandom", new THREE.BufferAttribute(randoms, 1));
  }, [positions, colors, targetPositions, sizes, randoms]);

  return (
    <points ref={pointsRef}>
      <bufferGeometry ref={geometryRef} />
      <primitive object={shaderMaterial} ref={materialRef} attach="material" />
    </points>
  );
}

/* ------------------------------------------------------------------ */
/*  Scene (场景)                                                       */
/* ------------------------------------------------------------------ */

function WordCloudScene({
  subjectLabel,
  nodes,
}: {
  subjectLabel: string;
  nodes: WordCloudNode[];
}) {
  // 构建漂浮词数据
  const floatingWords: FloatingWordData[] = useMemo(() => {
    const maxWords = Math.min(nodes.length, 80);
    const words: FloatingWordData[] = [];

    for (let i = 0; i < maxWords; i++) {
      const node = nodes[i];
      const color = TYPE_COLORS[node.nodeType] || DEFAULT_COLOR;

      // 按重要度分层：高置信度的词更靠近中心、更大
      const isImportant = node.confidence > 0.7;
      const layer = isImportant ? 1 : 2;

      // 球面分布
      const phi = Math.acos(2 * Math.random() - 1);
      const theta = Math.random() * Math.PI * 2;
      const radius = layer === 1 ? 3.5 + Math.random() * 2 : 4.5 + Math.random() * 4;

      const x = radius * Math.sin(phi) * Math.cos(theta);
      const y = radius * Math.sin(phi) * Math.sin(theta) * 0.6; // y 轴压缩
      const z = radius * Math.cos(phi) * 0.5;

      words.push({
        text: node.name,
        position: [x, y, z],
        color: i % 3 === 0 ? ACCENT_COLOR : color,
        size: isImportant ? 0.14 + Math.random() * 0.06 : 0.08 + Math.random() * 0.06,
        opacity: isImportant ? 0.85 + Math.random() * 0.15 : 0.35 + Math.random() * 0.35,
        speed: 0.15 + Math.random() * 0.2,
        phase: Math.random() * Math.PI * 2,
      });
    }
    return words;
  }, [nodes]);

  const particleCount = Math.max(1500, Math.min(3000, nodes.length * 30));

  return (
    <>
      {/* 环境光 */}
      <ambientLight intensity={0.4} />
      <directionalLight position={[5, 5, 5]} intensity={0.3} />

      {/* 中心粒子字形 */}
      <CenterParticles
        subjectLabel={subjectLabel}
        particleCount={particleCount}
      />

      {/* 漂浮关键词 */}
      {floatingWords.map((word, i) => (
        <FloatingWord key={`${word.text}-${i}`} data={word} />
      ))}

      {/* 交互控制 */}
      <OrbitControls
        enableDamping
        dampingFactor={0.05}
        rotateSpeed={0.5}
        zoomSpeed={0.8}
        minDistance={3}
        maxDistance={15}
        autoRotate
        autoRotateSpeed={0.3}
        enablePan={false}
      />
    </>
  );
}

/* ------------------------------------------------------------------ */
/*  Main export                                                        */
/* ------------------------------------------------------------------ */

export function WordCloud3D({
  subjectLabel,
  nodes,
  height = 520,
}: WordCloud3DProps) {
  const [isClient, setIsClient] = useState(false);

  useEffect(() => {
    setIsClient(true);
  }, []);

  if (!isClient || nodes.length === 0) {
    return (
      <div
        className="flex items-center justify-center rounded-2xl border border-slate-800 bg-slate-950"
        style={{ height }}
      >
        <div className="text-center text-slate-500">
          <div className="mx-auto mb-3 h-10 w-10 rounded-full bg-slate-800 flex items-center justify-center">
            <svg className="h-5 w-5 text-slate-500" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
              <circle cx="12" cy="12" r="10" />
              <path d="M8 12h8M12 8v8" />
            </svg>
          </div>
          <p className="text-sm font-medium text-slate-400">暂无图谱数据</p>
          <p className="mt-1 text-xs text-slate-600">
            构建知识产物后，这里将展示3D交互式词云
          </p>
        </div>
      </div>
    );
  }

  return (
    <div
      className="relative overflow-hidden rounded-2xl border border-slate-800 bg-gradient-to-b from-slate-950 via-[#0a0a1a] to-slate-950"
      style={{ height }}
    >
      {/* 背景光效 */}
      <div className="pointer-events-none absolute inset-0">
        <div className="absolute left-1/2 top-1/2 -translate-x-1/2 -translate-y-1/2 h-[60%] w-[60%] rounded-full bg-purple-900/10 blur-[100px]" />
        <div className="absolute right-1/4 top-1/3 h-32 w-32 rounded-full bg-fuchsia-800/8 blur-[60px]" />
        <div className="absolute left-1/4 bottom-1/3 h-24 w-24 rounded-full bg-blue-800/8 blur-[60px]" />
      </div>

      {/* Three.js Canvas */}
      <Canvas
        camera={{
          position: [0, 0, 7],
          fov: 55,
          near: 0.1,
          far: 100,
        }}
        dpr={[1, 2]}
        gl={{
          antialias: true,
          alpha: true,
          powerPreference: "high-performance",
        }}
        style={{ background: "transparent" }}
      >
        <WordCloudScene subjectLabel={subjectLabel} nodes={nodes} />
      </Canvas>

      {/* 顶部叠加层 —— 标题 */}
      <div className="pointer-events-none absolute left-0 top-0 right-0 p-5">
        <div className="flex items-center gap-2">
          <div className="h-2 w-2 rounded-full bg-fuchsia-500 animate-pulse" />
          <span className="text-xs font-medium tracking-wider text-slate-400 uppercase">
            Knowledge Universe
          </span>
        </div>
      </div>

      {/* 底部统计 */}
      <div className="pointer-events-none absolute bottom-0 left-0 right-0 bg-gradient-to-t from-slate-950/80 to-transparent p-5 pt-10">
        <div className="flex items-end justify-between">
          <div>
            <p className="text-lg font-bold text-white/90">{subjectLabel}</p>
            <p className="mt-0.5 text-xs text-slate-500">
              {nodes.length} 个知识节点 · 拖拽旋转探索
            </p>
          </div>
          <div className="flex gap-3">
            {Object.entries(
              nodes.reduce<Record<string, number>>((acc, n) => {
                const type = n.nodeType;
                acc[type] = (acc[type] || 0) + 1;
                return acc;
              }, {})
            )
              .sort((a, b) => b[1] - a[1])
              .slice(0, 4)
              .map(([type, count]) => (
                <div
                  key={type}
                  className="flex items-center gap-1.5"
                >
                  <span
                    className="inline-block h-1.5 w-1.5 rounded-full"
                    style={{
                      backgroundColor: TYPE_COLORS[type] || DEFAULT_COLOR,
                    }}
                  />
                  <span className="text-[10px] text-slate-500">
                    {type} {count}
                  </span>
                </div>
              ))}
          </div>
        </div>
      </div>

      {/* 操作提示 */}
      <div className="pointer-events-none absolute right-4 top-1/2 -translate-y-1/2">
        <div className="flex flex-col items-center gap-1 text-slate-600">
          <svg className="h-5 w-5" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5">
            <path d="M12 2C6.48 2 2 6.48 2 12s4.48 10 10 10 10-4.48 10-10S17.52 2 12 2z" />
            <path d="M12 8v4M12 16h.01" />
          </svg>
          <span className="text-[9px] writing-vertical">拖拽旋转</span>
        </div>
      </div>
    </div>
  );
}

export default WordCloud3D;
