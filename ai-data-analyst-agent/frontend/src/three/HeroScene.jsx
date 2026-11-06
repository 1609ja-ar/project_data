// Landing hero: a 3D "data city" of SAMPLE values (the page labels it "Sample data"). Columns rise in a
// wave and then breathe gently; a trend line with point markers runs along the tops of the back row; the
// scene tilts with the pointer. Lighting, shadows and the platform come from Stage.
import { useMemo, useRef } from 'react';
import { Canvas, useFrame } from '@react-three/fiber';
import { RoundedBox } from '@react-three/drei';
import { CatmullRomCurve3, Vector3 } from 'three';
import Stage, { Platform } from './Stage.jsx';
import useThemeColors from '../hooks/useThemeColors.js';

const MONTHS = 9;
// Rows front to back; the back row is the largest series and carries the trend line.
const SERIES = [[0.3, 0.35, 0.3, 0.4, 0.45, 0.5, 0.5, 0.6, 0.65], [0.45, 0.5, 0.6, 0.55, 0.65, 0.7, 0.8, 0.85, 0.9],
  [0.7, 0.8, 0.75, 0.9, 1.0, 1.05, 1.15, 1.2, 1.3], [1.1, 1.25, 1.2, 1.5, 1.45, 1.75, 1.7, 2.05, 2.3]];
const ROW_COLORS = [3, 2, 1, 0]; // chart palette slots: amber, green, orange, blue (back)
const STEP = 0.62;
const ROW = 0.72;

function ease(t) {
  return 1 - (1 - Math.min(1, Math.max(0, t))) ** 3;
}

function Column({ x, z, h, color, delay, animate }) {
  const ref = useRef();
  const t0 = useRef(null);
  useFrame((state) => {
    if (!ref.current) return;
    let s = 1;
    if (animate) {
      if (t0.current === null) t0.current = state.clock.elapsedTime;
      const t = state.clock.elapsedTime - t0.current;
      const p = ease((t - delay) / 0.9);
      s = p * (1 + Math.sin(t * 1.1 + delay * 6) * 0.03 * p);
    }
    ref.current.scale.y = Math.max(0.001, s);
    ref.current.position.y = (h * s) / 2;
  });
  return (
    <group position={[x, 0, z]}>
      <group ref={ref}>
        <RoundedBox args={[0.46, h, 0.46]} radius={0.05} smoothness={4} castShadow receiveShadow>
          <meshPhysicalMaterial color={color} roughness={0.32} metalness={0.02} clearcoat={0.8} clearcoatRoughness={0.18} sheen={0.3} />
        </RoundedBox>
      </group>
    </group>
  );
}

function TopTrend({ color, w, z, animate }) {
  // Runs along the tops of the back row (the values it sits on), so the line is part of the data.
  const back = SERIES[SERIES.length - 1];
  const pts = useMemo(() => back.map((h, i) => new Vector3(i * STEP - w / 2, h + 0.09, z)), [back, w, z]);
  const curve = useMemo(() => new CatmullRomCurve3(pts, false, 'centripetal'), [pts]);
  const group = useRef();
  const t0 = useRef(null);
  useFrame((state) => {
    if (!group.current) return;
    if (!animate) { group.current.scale.set(1, 1, 1); return; }
    if (t0.current === null) t0.current = state.clock.elapsedTime;
    const p = ease((state.clock.elapsedTime - t0.current - 0.9) / 0.6); // appears once the columns have risen
    group.current.scale.set(1, Math.max(0.001, p), 1);
  });
  return (
    <group ref={group}>
      <mesh castShadow>
        <tubeGeometry args={[curve, 160, 0.026, 12, false]} />
        <meshPhysicalMaterial color={color} emissive={color} emissiveIntensity={0.35} roughness={0.25} clearcoat={1} />
      </mesh>
      {pts.map((p, i) => (
        <mesh key={i} position={p} castShadow>
          <sphereGeometry args={[i === pts.length - 1 ? 0.075 : 0.05, 24, 24]} />
          <meshPhysicalMaterial color="#ffffff" emissive={color} emissiveIntensity={0.25} roughness={0.2} clearcoat={1} />
        </mesh>
      ))}
    </group>
  );
}

function City({ colors, animate }) {
  const group = useRef();
  const w = (MONTHS - 1) * STEP;
  const d = (SERIES.length - 1) * ROW;
  useFrame((state) => {
    if (!group.current || !animate) return;
    const { x, y } = state.pointer;
    const t = state.clock.elapsedTime;
    group.current.rotation.y += ((-0.6 + x * 0.2 + Math.sin(t * 0.18) * 0.05) - group.current.rotation.y) * 0.04;
    group.current.rotation.x += ((0.06 - y * 0.05) - group.current.rotation.x) * 0.04;
  });
  return (
    <group ref={group} rotation={[0.06, -0.6, 0]} position={[-0.3, -1.05, 0]}>
      <Platform width={w + 1.1} depth={d + 1.1} colors={colors}
        xLines={Array.from({ length: MONTHS - 1 }, (_, i) => (i + 0.5) * STEP - w / 2)}
        zLines={Array.from({ length: SERIES.length - 1 }, (_, i) => (i + 0.5) * ROW - d / 2)} />
      {SERIES.map((row, si) => row.map((h, mi) => (
        <Column key={`${si}-${mi}`} x={mi * STEP - w / 2} z={d / 2 - si * ROW} h={h} color={colors.series[ROW_COLORS[si]]}
          delay={mi * 0.06 + (SERIES.length - si) * 0.07} animate={animate} />
      )))}
      <TopTrend color={colors.series[3]} w={w} z={-d / 2} animate={animate} />
    </group>
  );
}

export default function HeroScene({ active, mode }) {
  const colors = useThemeColors();
  const animate = active && mode !== 'static';
  return (
    <Canvas shadows="percentage" dpr={[1, mode === 'lite' ? 1.5 : 2]} frameloop={animate ? 'always' : 'demand'} camera={{ position: [0, 2.4, 9.4], fov: 36 }}
      gl={{ antialias: mode !== 'lite', alpha: true, powerPreference: 'low-power', toneMappingExposure: 1.05 }} style={{ background: 'transparent' }}>
      <fog attach="fog" args={[colors.surface, 10.5, 18]} />
      <City colors={colors} animate={animate} />
      <Stage shadowY={-1.048} shadowScale={11} mode={mode} reach={6} />
    </Canvas>
  );
}
