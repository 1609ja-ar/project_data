// Moment 3 - Share: a card showing the dashboard rises, flips over to a "Link ready" back face, and settles
// while a few particles drift out. Both faces are drawn on canvases from the dashboard's own title and KPIs.
import { useMemo, useRef } from 'react';
import { useFrame } from '@react-three/fiber';
import { RoundedBox } from '@react-three/drei';
import { CanvasTexture, SRGBColorSpace } from 'three';
import useThemeColors from '../../hooks/useThemeColors.js';
import { MomentCanvas, easeInOut, easeOut, useClock } from './common.jsx';

const W = 3.4;
const Hc = 2.1;

function roundRect(ctx, x, y, w, h, r) {
  ctx.beginPath();
  ctx.moveTo(x + r, y);
  ctx.arcTo(x + w, y, x + w, y + h, r);
  ctx.arcTo(x + w, y + h, x, y + h, r);
  ctx.arcTo(x, y + h, x, y, r);
  ctx.arcTo(x, y, x + w, y, r);
  ctx.closePath();
}

function texture(draw) {
  const c = document.createElement('canvas');
  c.width = 1024;
  c.height = Math.round((1024 * Hc) / W);
  draw(c.getContext('2d'), c.width, c.height);
  const t = new CanvasTexture(c);
  t.colorSpace = SRGBColorSpace;
  t.anisotropy = 8;
  return t;
}

function useFaces({ title, kpis, bars, link, colors }) {
  return useMemo(() => {
    const font = (w, s) => `${w} ${s}px Inter, system-ui, sans-serif`;
    const front = texture((ctx, w, h) => {
      ctx.fillStyle = colors.surface; ctx.fillRect(0, 0, w, h);
      ctx.fillStyle = colors.text; ctx.font = font(650, 40); ctx.fillText(title, 48, 78);
      ctx.fillStyle = colors.muted; ctx.font = font(500, 24); ctx.fillText('Read-only dashboard', 48, 116);
      kpis.slice(0, 3).forEach((k, i) => {
        const x = 48 + i * 312;
        ctx.strokeStyle = colors.border; ctx.lineWidth = 2; roundRect(ctx, x, 150, 290, 120, 14); ctx.stroke();
        ctx.fillStyle = colors.series[[0, 6, 2][i]]; ctx.fillRect(x, 150, 290, 6);
        ctx.fillStyle = colors.muted; ctx.font = font(500, 22); ctx.fillText(k.label, x + 20, 194);
        ctx.fillStyle = colors.text; ctx.font = font(650, 40); ctx.fillText(k.text, x + 20, 245);
      });
      const max = Math.max(...bars, 1);
      const bw = (w - 96) / bars.length;
      bars.forEach((b, i) => {
        const bh = (b / max) * (h - 340);
        ctx.fillStyle = colors.series[0];
        roundRect(ctx, 48 + i * bw + bw * 0.18, h - 40 - bh, bw * 0.64, bh, 6); ctx.fill();
      });
    });
    const back = texture((ctx, w, h) => {
      ctx.fillStyle = colors.surface; ctx.fillRect(0, 0, w, h);
      const cx = w / 2;
      ctx.fillStyle = colors.success; ctx.beginPath(); ctx.arc(cx, 190, 74, 0, Math.PI * 2); ctx.fill();
      ctx.strokeStyle = '#ffffff'; ctx.lineWidth = 14; ctx.lineCap = 'round'; ctx.lineJoin = 'round';
      ctx.beginPath(); ctx.moveTo(cx - 32, 192); ctx.lineTo(cx - 8, 216); ctx.lineTo(cx + 36, 168); ctx.stroke();
      ctx.textAlign = 'center';
      ctx.fillStyle = colors.text; ctx.font = font(650, 64); ctx.fillText('Link ready', cx, 350);
      ctx.fillStyle = colors.muted; ctx.font = font(500, link.length > 48 ? 26 : 32); ctx.fillText(link, cx, 410);
      ctx.font = font(500, 28); ctx.fillText('Read-only · figures and charts only · revocable', cx, 462);
    });
    return { front, back };
  }, [title, kpis, bars, link, colors]);
}

function Particles({ clock, color }) {
  const group = useRef();
  const seeds = useMemo(() => Array.from({ length: 14 }, (_, i) => ({ a: (i / 14) * Math.PI * 2, s: 0.8 + ((i * 37) % 10) / 10, y: ((i * 53) % 10) / 10 - 0.5 })), []);
  useFrame(() => {
    const t = clock.current - 1.6;
    group.current?.children.forEach((m, i) => {
      const s = seeds[i];
      const p = easeOut(t / 1.4);
      m.position.set(Math.cos(s.a) * (1.9 + p * 1.2 * s.s), s.y * 1.6 + p * 0.5, Math.sin(s.a) * 0.6);
      m.scale.setScalar(t > 0 ? Math.max(0.001, (1 - p) * 0.9) : 0.001);
    });
  });
  return (
    <group ref={group}>
      {seeds.map((_, i) => (
        <mesh key={i}><sphereGeometry args={[0.045, 12, 12]} /><meshStandardMaterial color={color} emissive={color} emissiveIntensity={0.6} /></mesh>
      ))}
    </group>
  );
}

function Card({ faces, clock, colors }) {
  const ref = useRef();
  useFrame((state) => {
    const t = clock.current;
    if (!ref.current) return;
    const rise = easeOut(t / 0.7);
    const flip = easeInOut((t - 0.8) / 0.9);
    const settle = easeOut((t - 1.7) / 0.8);
    ref.current.position.set(0, -0.7 + rise * 0.75 + settle * 0.1 + Math.sin(state.clock.elapsedTime * 1.4) * 0.02 * settle, -0.4 + settle * 0.3);
    ref.current.rotation.set(-0.12 + settle * 0.04, -0.35 + flip * Math.PI, 0.02 * (1 - settle));
    ref.current.scale.setScalar(0.85 + rise * 0.15);
  });
  return (
    <group ref={ref}>
      <RoundedBox args={[W + 0.08, Hc + 0.08, 0.08]} radius={0.05} smoothness={4} castShadow>
        <meshPhysicalMaterial color={colors.border} roughness={0.4} clearcoat={0.6} />
      </RoundedBox>
      <mesh position={[0, 0, 0.042]}>
        <planeGeometry args={[W, Hc]} />
        <meshStandardMaterial map={faces.front} roughness={0.55} />
      </mesh>
      <mesh position={[0, 0, -0.042]} rotation={[0, Math.PI, 0]}>
        <planeGeometry args={[W, Hc]} />
        <meshStandardMaterial map={faces.back} roughness={0.55} />
      </mesh>
    </group>
  );
}

function Scene({ title, kpis, bars, link }) {
  const colors = useThemeColors();
  const clock = useClock(true);
  const faces = useFaces({ title, kpis, bars, link, colors });
  return (
    <group position={[0, 0.1, 0]}>
      <Card faces={faces} clock={clock} colors={colors} />
      <Particles clock={clock} color={colors.series[0]} />
    </group>
  );
}

/** kpis: [{ label, text }], bars: numbers for the small chart, link: text shown on the back. */
export default function ShareFlip3D({ title, kpis, bars, link, mode = 'full', active = true }) {
  return (
    <div className="bars3d moment-scene">
      <MomentCanvas animate={active && mode !== 'static'} mode={mode} camera={[0, 0.5, 4.3]} shadowY={-1.4} controls={false}>
        <Scene title={title} kpis={kpis} bars={bars} link={link} />
      </MomentCanvas>
    </div>
  );
}
