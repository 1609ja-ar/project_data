// "Data city": a period x category grid of 3D columns from a split-trend result (backend rows).
// Heights are proportional to the values; columns rise in a wave; hover shows the exact figure.
import { createRef, useMemo, useRef, useState } from 'react';
import { Canvas, useFrame, useThree } from '@react-three/fiber';
import { OrbitControls, RoundedBox } from '@react-three/drei';
import { Vector3 } from 'three';
import Stage, { Platform } from './Stage.jsx';
import useThemeColors from '../hooks/useThemeColors.js';
import { formatCell, formatPeriod } from '../utils/format.js';

const MAX_H = 2.6;
const STEP = 0.62;
const v = new Vector3();

function Column({ x, z, h, color, delay, animate, active, onOver, onOut }) {
  const ref = useRef();
  const start = useRef(null);
  useFrame((state) => {
    if (!ref.current) return;
    let t = 1;
    if (animate) {
      if (start.current === null) start.current = state.clock.elapsedTime;
      const p = Math.min(1, Math.max(0, (state.clock.elapsedTime - start.current - delay) / 0.7));
      t = 1 - (1 - p) ** 3;
    }
    const lift = active ? 0.06 : 0;
    ref.current.scale.y = Math.max(0.001, t);
    ref.current.position.y = (h * t) / 2 + lift;
  });
  return (
    <group position={[x, 0, z]}>
      <group ref={ref}>
        <RoundedBox args={[0.46, Math.max(h, 0.02), 0.46]} radius={0.05} smoothness={4} castShadow receiveShadow onPointerOver={onOver} onPointerOut={onOut}>
          <meshPhysicalMaterial color={color} roughness={0.3} metalness={0.02} clearcoat={0.8} clearcoatRoughness={0.18} sheen={0.3}
            emissive={color} emissiveIntensity={active ? 0.35 : 0} />
        </RoundedBox>
      </group>
    </group>
  );
}

function Labels({ group, anchors, refs, tipRef, hoverPos }) {
  const { camera, size } = useThree();
  useFrame(() => {
    if (!group.current) return;
    const place = (el, p, shift = '-50%, 0') => {
      v.set(p[0], p[1], p[2]).applyMatrix4(group.current.matrixWorld).project(camera);
      el.style.transform = `translate(${shift}) translate(${((v.x + 1) / 2) * size.width}px, ${((1 - v.y) / 2) * size.height}px)`;
    };
    anchors.forEach((a, i) => refs[i].current && place(refs[i].current, a.pos, a.shift));
    if (tipRef.current) {
      tipRef.current.style.opacity = hoverPos ? '1' : '0';
      if (hoverPos) place(tipRef.current, hoverPos, '-50%, -100%');
    }
  });
  return null;
}

function Scene({ grid, animate, colors, anchors, refs, tipRef, hovered, setHovered }) {
  const group = useRef();
  useFrame((state) => {
    if (group.current && animate && !hovered) group.current.rotation.y = -0.55 + Math.sin(state.clock.elapsedTime * 0.25) * 0.12;
  });
  const hp = hovered ? grid.cells.find((c) => c.id === hovered) : null;
  return (
    <>
      <group ref={group} rotation={[0, -0.55, 0]} position={[0, -0.95, 0]}>
        {grid.cells.map((c) => (
          <Column key={c.id} x={c.x} z={c.z} h={c.h} color={c.color} delay={c.delay} animate={animate} active={hovered === c.id}
            onOver={(e) => { e.stopPropagation(); setHovered(c.id); }} onOut={() => setHovered(null)} />
        ))}
        <Platform width={grid.w + 1} depth={grid.d + 1} colors={colors}
          xLines={grid.periods.slice(1).map((_, i) => (i + 0.5) * STEP - grid.w / 2)}
          zLines={grid.cats.slice(1).map((_, i) => (i + 0.5) * STEP * 1.25 - grid.d / 2)} />
        <Labels group={group} anchors={anchors} refs={refs} tipRef={tipRef} hoverPos={hp ? [hp.x, hp.h + 0.25, hp.z] : null} />
      </group>
      <Stage shadowY={-0.948} shadowScale={Math.max(grid.w, grid.d) + 4} reach={Math.max(grid.w, grid.d) / 2 + 2} />
    </>
  );
}

/** columns/rows/spec: a split trend result (x = period, series = category, y = value). */
export default function City3D({ columns, rows, spec, seriesOrder, active = true, mode = 'full' }) {
  const colors = useThemeColors();
  const animate = active && mode !== 'static';
  const [hovered, setHovered] = useState(null);
  const tipRef = useRef(null);
  const grid = useMemo(() => {
    const ix = Object.fromEntries(columns.map((c, i) => [c.key, i]));
    const periods = [...new Set(rows.map((r) => r[ix[spec.x]]))].slice(-36);
    const cats = [...new Set(rows.map((r) => String(r[ix[spec.series]] ?? '(empty)')))].slice(0, 8);
    const max = Math.max(...rows.map((r) => Number(r[ix.value]) || 0), 1);
    const w = (periods.length - 1) * STEP;
    const d = (cats.length - 1) * STEP * 1.25;
    const cells = [];
    rows.forEach((r) => {
      const pi = periods.indexOf(r[ix[spec.x]]);
      const cat = String(r[ix[spec.series]] ?? '(empty)');
      const ci = cats.indexOf(cat);
      if (pi < 0 || ci < 0) return;
      const slot = seriesOrder ? seriesOrder.indexOf(cat) : -1;
      cells.push({
        id: `${pi}-${ci}`, x: pi * STEP - w / 2, z: ci * STEP * 1.25 - d / 2, h: (Math.max(0, Number(r[ix.value]) || 0) / max) * MAX_H,
        color: colors.series[(slot >= 0 ? slot : ci) % colors.series.length], delay: pi * 0.035 + ci * 0.05,
        text: `${formatPeriod(String(r[ix[spec.x]]))} · ${cat}: ${formatCell(r[ix.value], columns[ix.value]) ?? '—'}`,
      });
    });
    return { cells, periods, cats, w, d };
  }, [columns, rows, spec, seriesOrder, colors.series]);

  // Axis labels: every few periods along the front edge, each category along the right edge.
  const anchors = useMemo(() => {
    const every = Math.max(1, Math.ceil(grid.periods.length / 6));
    const out = grid.periods.map((p, i) => (i % every === 0 ? { text: formatPeriod(String(p)), pos: [i * STEP - grid.w / 2, -0.05, grid.d / 2 + 0.55] } : null)).filter(Boolean);
    grid.cats.forEach((c, i) => out.push({ text: c, pos: [grid.w / 2 + 0.6, 0, i * STEP * 1.25 - grid.d / 2], shift: '0, -50%' }));
    return out;
  }, [grid]);
  const refs = useMemo(() => anchors.map(() => createRef()), [anchors]);
  const tip = grid.cells.find((c) => c.id === hovered);
  const span = Math.max(grid.w, grid.d * 1.4, 4);

  return (
    <div className="bars3d" style={{ cursor: 'grab' }}>
      <Canvas shadows="percentage" dpr={[1, mode === 'lite' ? 1.5 : 2]} frameloop={animate || hovered ? 'always' : 'demand'}
        camera={{ position: [0, 3.5, Math.min(14, 2.8 + span * 0.9)], fov: 36 }}
        gl={{ antialias: mode !== 'lite', alpha: true, powerPreference: 'low-power', toneMappingExposure: 1.05 }} style={{ background: 'transparent' }}>
        <fog attach="fog" args={[colors.surface, 2.8 + span * 0.9, 8 + span * 1.6]} />
        <Scene grid={grid} animate={animate} colors={colors} anchors={anchors} refs={refs} tipRef={tipRef} hovered={hovered} setHovered={setHovered} />
        <OrbitControls enableZoom={false} enablePan={false} minPolarAngle={0.5} maxPolarAngle={1.35} />
      </Canvas>
      {anchors.map((a, i) => <span key={`${a.text}-${i}`} ref={refs[i]} className="bars3d-label" style={{ color: colors.muted }}>{a.text}</span>)}
      <div ref={tipRef} className="bars3d-tip" style={{ opacity: 0 }} aria-hidden="true">{tip?.text}</div>
    </div>
  );
}
