// Building blocks shared by the five 3D "moments" (short animations that play when an icon is clicked).
import { useRef } from 'react';
import { Canvas, useFrame, useThree } from '@react-three/fiber';
import { OrbitControls, RoundedBox } from '@react-three/drei';
import { Vector3 } from 'three';
import Stage from '../Stage.jsx';
import useThemeColors from '../../hooks/useThemeColors.js';

export const clamp01 = (t) => Math.min(1, Math.max(0, t));
export const easeOut = (t) => 1 - (1 - clamp01(t)) ** 3;
export const easeInOut = (t) => { const x = clamp01(t); return x < 0.5 ? 4 * x * x * x : 1 - (-2 * x + 2) ** 3 / 2; };
export const easeBack = (t) => { const x = clamp01(t); const c = 1.4; return 1 + (c + 1) * (x - 1) ** 3 + c * (x - 1) ** 2; };

/** Seconds since the scene started; frozen at `end` when animation is off (static / reduced motion). */
export function useClock(animate, end = 99) {
  const t0 = useRef(null);
  const now = useRef(animate ? 0 : end);
  useFrame((state) => {
    if (!animate) { now.current = end; return; }
    if (t0.current === null) t0.current = state.clock.elapsedTime;
    now.current = state.clock.elapsedTime - t0.current;
  });
  return now;
}

/** A canvas with the shared studio lighting, real shadows and a gentle depth fog. */
export function MomentCanvas({ children, camera = [0, 2.6, 7.6], fov = 38, mode = 'full', animate, shadowY = -1.198, reach = 6, controls = true }) {
  const colors = useThemeColors();
  return (
    <Canvas shadows="percentage" dpr={[1, mode === 'lite' ? 1.5 : 2]} frameloop={animate ? 'always' : 'demand'} camera={{ position: camera, fov }}
      gl={{ antialias: mode !== 'lite', alpha: true, powerPreference: 'low-power', toneMappingExposure: 1.05 }} style={{ background: 'transparent' }}>
      <fog attach="fog" args={[colors.surface, camera[2] + 3, camera[2] + 12]} />
      {children}
      <Stage shadowY={shadowY} shadowScale={12} mode={mode} reach={reach} />
      {controls && <OrbitControls enableZoom={false} enablePan={false} minPolarAngle={0.5} maxPolarAngle={1.45} />}
    </Canvas>
  );
}

/** A column that grows from the floor between `start` and `start + dur` on the given clock. */
export function Riser({ x = 0, z = 0, h, color, start = 0, dur = 0.9, clock, curve = easeOut, width = 0.7, depth, opacity = 1, emissive = 0,
  onOver, onOut, onClick }) {
  const ref = useRef();
  useFrame(() => {
    if (!ref.current) return;
    const s = Math.max(0.001, curve((clock.current - start) / dur));
    ref.current.scale.y = s;
    ref.current.position.y = (h * s) / 2;
  });
  return (
    <group position={[x, 0, z]}>
      <group ref={ref}>
        <RoundedBox args={[width, Math.max(h, 0.02), depth ?? width]} radius={Math.min(0.06, width / 4)} smoothness={4} castShadow receiveShadow
          onPointerOver={onOver} onPointerOut={onOut} onClick={onClick}>
          <meshPhysicalMaterial color={color} roughness={0.3} metalness={0.02} clearcoat={0.8} clearcoatRoughness={0.18}
            transparent={opacity < 1} opacity={opacity} emissive={color} emissiveIntensity={emissive} />
        </RoundedBox>
      </group>
    </group>
  );
}

const v = new Vector3();

/** Moves DOM labels to the screen position of 3D anchor points every frame (no extra React roots).
 *  anchors: [{ ref, pos: [x, y, z] (in the group's space), shift: '-50%, -100%', show: () => boolean }] */
export function Anchors({ group, anchors }) {
  const { camera, size } = useThree();
  useFrame(() => {
    if (!group.current) return;
    anchors.forEach((a) => {
      const el = a.ref.current;
      if (!el) return;
      const pos = typeof a.pos === 'function' ? a.pos() : a.pos;
      v.set(pos[0], pos[1], pos[2]).applyMatrix4(group.current.matrixWorld).project(camera);
      el.style.transform = `translate(${a.shift || '-50%, 0'}) translate(${((v.x + 1) / 2) * size.width}px, ${((1 - v.y) / 2) * size.height}px)`;
      if (a.show) el.style.opacity = a.show() ? '1' : '0';
    });
  });
  return null;
}
