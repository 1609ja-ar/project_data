// Moment 5 - "Replay cleaning in 3D": blocks stand for rows (scaled from the real counts). They fall in
// scattered, removed rows turn red and sink away, fixed rows flash amber and turn green, then everything
// left snaps into neat columns. A phase label narrates each step.
import { useMemo, useRef } from 'react';
import { useFrame } from '@react-three/fiber';
import { RoundedBox } from '@react-three/drei';
import { Color } from 'three';
import { Platform } from '../Stage.jsx';
import useThemeColors from '../../hooks/useThemeColors.js';
import { MomentCanvas, clamp01, easeInOut, easeOut, useClock } from './common.jsx';

const SIZE = 0.3;
const FALL = [0, 1.3];
const FIX = [1.5, 2.3];
const SORT = [2.4, 3.6];
const COLS = 8;

function rng(seed) {
  let s = seed;
  return () => ((s = (s * 16807) % 2147483647) / 2147483647);
}

function Block({ b, clock, colors }) {
  const ref = useRef();
  const mat = useRef();
  const tmp = useMemo(() => new Color(), []);
  const base = useMemo(() => new Color(colors.series[0]), [colors.series]);
  const red = useMemo(() => new Color(colors.danger), [colors.danger]);
  const amber = useMemo(() => new Color(colors.warning), [colors.warning]);
  const green = useMemo(() => new Color(colors.success), [colors.success]);
  useFrame(() => {
    const t = clock.current;
    if (!ref.current) return;
    // 1. fall onto the platform, scattered, with a small bounce
    const f = clamp01((t - FALL[0] - b.delay) / 0.7);
    const bounce = f < 1 ? easeOut(f) : 1;
    let y = b.y0 + (SIZE / 2 - b.y0) * bounce + Math.sin(Math.PI * clamp01((f - 0.75) / 0.25)) * 0.08;
    let { x, z } = b.scatter;
    let rotY = b.rot * (1 - easeInOut((t - SORT[0]) / (SORT[1] - SORT[0])));
    const fx = clamp01((t - FIX[0]) / (FIX[1] - FIX[0]));
    // 2. removed rows: red, then sink and fade; fixed rows: amber flash, then green
    if (b.kind === 'removed') {
      tmp.copy(base).lerp(red, clamp01(fx * 2));
      y -= easeInOut((fx - 0.4) / 0.6) * 0.9;
      mat.current.opacity = 1 - clamp01((fx - 0.5) / 0.5);
    } else if (b.kind === 'changed') {
      tmp.copy(base).lerp(amber, clamp01(fx * 2.5));
      if (fx > 0.5) tmp.lerp(green, clamp01((fx - 0.5) * 2));
    } else {
      tmp.copy(base);
    }
    mat.current.color.copy(tmp);
    // 3. kept rows move into tidy columns
    if (b.kind !== 'removed') {
      const s = easeInOut((t - SORT[0] - b.sortDelay) / (SORT[1] - SORT[0]));
      x += (b.final.x - x) * s;
      z += (b.final.z - z) * s;
      y += (b.final.y - y) * s;
    }
    ref.current.position.set(x, y, z);
    ref.current.rotation.set(0, rotY, 0);
    ref.current.visible = !(b.kind === 'removed' && fx >= 1);
  });
  return (
    <group ref={ref} position={[b.scatter.x, b.y0, b.scatter.z]}>
      <RoundedBox args={[SIZE, SIZE, SIZE]} radius={0.04} smoothness={3} castShadow receiveShadow>
        <meshPhysicalMaterial ref={mat} color={colors.series[0]} roughness={0.35} clearcoat={0.7} transparent />
      </RoundedBox>
    </group>
  );
}

function Phase({ clock, phaseRef }) {
  useFrame(() => {
    const t = clock.current;
    if (!phaseRef.current) return;
    const text = t < FIX[0] ? 'Reading rows…' : t < SORT[0] ? 'Fixing values and removing bad rows…' : t < SORT[1] ? 'Sorting into a clean table…' : 'Clean version ready';
    if (phaseRef.current.textContent !== text) phaseRef.current.textContent = text;
  });
  return null;
}

function Scene({ n, removed, changed, phaseRef }) {
  const colors = useThemeColors();
  const clock = useClock(true);
  const blocks = useMemo(() => {
    const r = rng(42);
    // Spread removed and changed rows evenly through the file rather than bunching them.
    const kinds = Array(n).fill('kept');
    for (let k = 0; k < removed; k += 1) kinds[Math.floor(((k + 0.5) * n) / removed)] = 'removed';
    for (let k = 0; k < changed; k += 1) {
      let j = Math.floor(((k + 0.25) * n) / changed);
      while (kinds[j] !== 'kept') j = (j + 1) % n;
      kinds[j] = 'changed';
    }
    const out = [];
    let keptIndex = 0;
    for (let i = 0; i < n; i += 1) {
      const kind = kinds[i];
      const b = { kind, delay: r() * 0.6, y0: 2.6 + r() * 2, rot: (r() - 0.5) * 2.4, scatter: { x: (r() - 0.5) * 4.6, z: (r() - 0.5) * 2 } };
      if (kind !== 'removed') {
        const col = keptIndex % COLS;
        const layer = Math.floor(keptIndex / COLS);
        b.final = { x: (col - (COLS - 1) / 2) * (SIZE + 0.08), y: SIZE / 2 + layer * (SIZE + 0.02), z: 0 };
        b.sortDelay = col * 0.04 + layer * 0.02;
        keptIndex += 1;
      }
      out.push(b);
    }
    return out;
  }, [n, removed, changed]);
  return (
    <group position={[0, -1.2, 0]} rotation={[0.04, -0.3, 0]}>
      <Platform width={5.6} depth={2.6} colors={colors} />
      {blocks.map((b, i) => <Block key={i} b={b} clock={clock} colors={colors} />)}
      <Phase clock={clock} phaseRef={phaseRef} />
    </group>
  );
}

/** Counts from the dataset's cleaning report; blocks are scaled to at most 48 so the scene stays readable.
 *  Red blocks are the share of rows removed; amber blocks the share of values (cells) fixed. */
export default function CleaningSort3D({ rowsBefore, rowsRemoved, cellsChanged, columns = 1, mode = 'full', active = true }) {
  const n = Math.max(12, Math.min(48, rowsBefore || 0));
  const removed = rowsRemoved > 0 ? Math.min(n - 4, Math.max(1, Math.round((rowsRemoved / rowsBefore) * n))) : 0;
  const cellShare = Math.min(1, cellsChanged / (rowsBefore * Math.max(1, columns || 1)));
  const changed = cellsChanged > 0 ? Math.min(n - removed, Math.max(1, Math.round(cellShare * n))) : 0;
  const phaseRef = useRef(null);
  return (
    <div className="bars3d moment-scene">
      <MomentCanvas animate={active && mode !== 'static'} mode={mode} camera={[0, 3, 7.4]} reach={5}>
        <Scene n={n} removed={removed} changed={changed} phaseRef={phaseRef} />
      </MomentCanvas>
      <span ref={phaseRef} className="m-phase">Reading rows…</span>
      <div className="m-legend">
        <span><i style={{ background: 'var(--chart-1)' }} /> row</span>
        <span><i style={{ background: 'var(--success)' }} /> values fixed</span>
        <span><i style={{ background: 'var(--danger)' }} /> rows removed</span>
      </div>
    </div>
  );
}
