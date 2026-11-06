// Interactive 3D bar chart of backend result rows. Heights are proportional to the values it is given;
// it never computes values. Drag to rotate, hover for the exact figure, click to filter (optional).
// Labels are ordinary DOM elements positioned every frame from the 3D scene (no extra React roots).
import { createRef, useMemo, useRef, useState } from 'react';
import { Canvas, useFrame, useThree } from '@react-three/fiber';
import { OrbitControls, RoundedBox } from '@react-three/drei';
import { Vector3 } from 'three';
import Stage, { Platform } from './Stage.jsx';
import useThemeColors from '../hooks/useThemeColors.js';

const MAX_H = 3;
const GAP = 0.95;
const v = new Vector3();

function Bar({ item, x, h, color, animate, delay, active, setHovered, onSelect }) {
  const ref = useRef();
  const start = useRef(null);
  useFrame((state) => {
    if (!ref.current) return;
    let t = 1;
    if (animate) { // staggered grow-in with ease-out; static mode draws the final heights at once
      if (start.current === null) start.current = state.clock.elapsedTime;
      const p = Math.min(1, Math.max(0, (state.clock.elapsedTime - start.current - delay * 0.07) / 0.8));
      t = 1 - (1 - p) ** 3;
    }
    ref.current.scale.y = Math.max(0.001, t);
    ref.current.position.y = (h * t) / 2 + (active ? 0.08 : 0); // hovered bar lifts slightly
  });
  return (
    <group position={[x, 0, 0]}>
      <group ref={ref}>
        <RoundedBox args={[0.62, Math.max(h, 0.02), 0.62]} radius={0.06} smoothness={4} castShadow receiveShadow
          onPointerOver={(e) => { e.stopPropagation(); setHovered(item.label); }}
          onPointerOut={() => setHovered(null)}
          onClick={onSelect ? (e) => { e.stopPropagation(); onSelect(item.raw); } : undefined}>
          <meshPhysicalMaterial color={color} roughness={0.3} metalness={0.02} clearcoat={0.8} clearcoatRoughness={0.18} sheen={0.3}
            emissive={color} emissiveIntensity={active ? 0.35 : 0} transparent opacity={item.dim ? 0.35 : 1} />
        </RoundedBox>
      </group>
    </group>
  );
}

/** Projects each bar's base (and the hovered bar's top) to screen pixels and moves the DOM labels. */
function LabelSync({ group, positions, labelRefs, tipRef, hovered, items }) {
  const { camera, size } = useThree();
  useFrame(() => {
    if (!group.current) return;
    positions.forEach((p, i) => {
      const el = labelRefs[i].current;
      if (!el) return;
      v.set(p.x, -0.1, 1.2).applyMatrix4(group.current.matrixWorld).project(camera);
      el.style.transform = `translate(-50%, 0) translate(${((v.x + 1) / 2) * size.width}px, ${((1 - v.y) / 2) * size.height}px)`;
    });
    const tip = tipRef.current;
    const i = items.findIndex((it) => it.label === hovered);
    if (tip) {
      if (i < 0) { tip.style.opacity = '0'; return; }
      v.set(positions[i].x, positions[i].h + 0.3, 0).applyMatrix4(group.current.matrixWorld).project(camera);
      tip.style.opacity = '1';
      tip.style.transform = `translate(-50%, -100%) translate(${((v.x + 1) / 2) * size.width}px, ${((1 - v.y) / 2) * size.height}px)`;
    }
  });
  return null;
}

function Scene({ items, animate, onSelect, colors, labelRefs, tipRef, hovered, setHovered }) {
  const group = useRef();
  const max = Math.max(...items.map((i) => Math.abs(i.value) || 0), 1);
  const width = (items.length - 1) * GAP;
  const positions = useMemo(() => items.map((it, i) => ({ x: i * GAP - width / 2, h: (Math.max(0, it.value) / max) * MAX_H })), [items, width, max]);
  useFrame((state) => {
    // Gentle sway (not a spin) so labels stay readable; it pauses while a bar is hovered.
    if (group.current && animate && !hovered) group.current.rotation.y = -0.18 + Math.sin(state.clock.elapsedTime * 0.35) * 0.2;
  });
  return (
    <>
      <group ref={group} position={[0, -1.35, 0]} rotation={[0, -0.18, 0]}>
        {items.map((it, i) => (
          <Bar key={it.label} item={it} x={positions[i].x} h={positions[i].h} color={it.color} animate={animate} delay={i}
            active={hovered === it.label} setHovered={setHovered} onSelect={onSelect} />
        ))}
        <Platform width={width + 1.6} depth={1.9} colors={colors} xLines={items.slice(1).map((_, i) => (i + 0.5) * GAP - width / 2)} />
      </group>
      <LabelSync group={group} positions={positions} labelRefs={labelRefs} tipRef={tipRef} hovered={hovered} items={items} />
    </>
  );
}

/**
 * items: [{ label, value, raw, text, color, dim }] - value drives the height, text is the formatted figure.
 */
export default function DataBars3D({ items, active = true, mode = 'full', onSelect }) {
  const colors = useThemeColors();
  const animate = active && mode !== 'static';
  const shown = useMemo(() => items.slice(0, 12), [items]);
  const labelRefs = useMemo(() => shown.map(() => createRef()), [shown]);
  const tipRef = useRef(null);
  const [hovered, setHovered] = useState(null);
  const span = Math.max(4, shown.length * GAP);
  const tip = shown.find((s) => s.label === hovered);
  return (
    <div className="bars3d" style={{ cursor: hovered && onSelect ? 'pointer' : 'grab' }}>
      <Canvas shadows="percentage" dpr={[1, mode === 'lite' ? 1.5 : 2]} frameloop={animate || hovered ? 'always' : 'demand'}
        camera={{ position: [0, 1.7, Math.min(11, 3.4 + span * 0.85)], fov: 38 }}
        gl={{ antialias: mode !== 'lite', alpha: true, powerPreference: 'low-power', toneMappingExposure: 1.05 }} style={{ background: 'transparent' }}>
        <Stage shadowY={-1.348} mode={mode} reach={span / 2 + 2} />
        <Scene items={shown} animate={animate} onSelect={onSelect} colors={colors} labelRefs={labelRefs} tipRef={tipRef} hovered={hovered} setHovered={setHovered} />
        <OrbitControls enableZoom={false} enablePan={false} minPolarAngle={0.6} maxPolarAngle={1.45} />
      </Canvas>
      {shown.map((s, i) => <span key={s.label} ref={labelRefs[i]} className="bars3d-label" style={{ color: colors.text }}>{s.label}</span>)}
      <div ref={tipRef} className="bars3d-tip" style={{ opacity: 0 }} aria-hidden="true">
        {tip && <><strong>{tip.label}</strong> {tip.text}</>}
      </div>
    </div>
  );
}
