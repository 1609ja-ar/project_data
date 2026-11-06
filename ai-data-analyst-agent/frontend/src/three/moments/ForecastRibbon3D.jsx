// Moment 2 - "Forecast in 3D": the recorded trend draws itself as a glowing ribbon over thin pillars, then
// the projection grows forward as a dashed line inside a translucent 80% range band. Values come from the
// trend tile (recorded periods) and the backend forecast (projection and range).
import { useMemo, useRef } from 'react';
import { useFrame } from '@react-three/fiber';
import { BufferGeometry, CatmullRomCurve3, DoubleSide, Float32BufferAttribute, Vector3 } from 'three';
import { Platform } from '../Stage.jsx';
import useThemeColors from '../../hooks/useThemeColors.js';
import { Anchors, MomentCanvas, Riser, easeInOut, easeOut, useClock } from './common.jsx';

const H = 2.4;
const DRAW = [0.3, 1.9]; // seconds: recorded line draws
const GROW = [2.0, 3.0]; // seconds: forecast grows

function bandGeometry(xs, lows, highs) {
  const g = new BufferGeometry();
  const pos = [];
  xs.forEach((x, i) => { pos.push(x, lows[i], 0, x, highs[i], 0); });
  const idx = [];
  for (let i = 0; i < xs.length - 1; i += 1) {
    const a = i * 2;
    idx.push(a, a + 1, a + 2, a + 1, a + 3, a + 2);
  }
  g.setAttribute('position', new Float32BufferAttribute(pos, 3));
  g.setIndex(idx);
  g.computeVertexNormals();
  return g;
}

function Scene({ actual, forecast, refs }) {
  const colors = useThemeColors();
  const group = useRef();
  const lineGeo = useRef();
  const fc = useRef();
  const clock = useClock(true);
  const color = colors.series[0];
  const n = actual.length + forecast.length;
  const step = Math.min(0.55, 7.2 / Math.max(1, n - 1));
  const width = (n - 1) * step;
  const max = Math.max(...actual.map((p) => p.value), ...forecast.map((p) => p.high), 1e-9);
  const y = (v) => (Math.max(0, v) / max) * H;
  const xs = Array.from({ length: n }, (_, i) => i * step - width / 2);
  const ax = xs.slice(0, actual.length);
  const pts = useMemo(() => actual.map((p, i) => new Vector3(ax[i], y(p.value) + 0.02, 0)), [actual]); // eslint-disable-line react-hooks/exhaustive-deps
  const curve = useMemo(() => new CatmullRomCurve3(pts, false, 'centripetal'), [pts]);
  const last = actual.length - 1;
  // Forecast geometry is built from the last recorded point so it connects; it grows by scaling along x.
  const fx = [0, ...forecast.map((_, i) => (i + 1) * step)];
  const fy = [y(actual[last].value), ...forecast.map((p) => y(p.value))];
  const band = useMemo(() => bandGeometry(fx, [fy[0], ...forecast.map((p) => y(p.low))], [fy[0], ...forecast.map((p) => y(p.high))]), [forecast]); // eslint-disable-line react-hooks/exhaustive-deps
  const fcurve = useMemo(() => new CatmullRomCurve3(fx.map((x, i) => new Vector3(x, fy[i] + 0.02, 0))), [forecast]); // eslint-disable-line react-hooks/exhaustive-deps

  useFrame(() => {
    const t = clock.current;
    if (lineGeo.current?.index) {
      const p = easeInOut((t - DRAW[0]) / (DRAW[1] - DRAW[0]));
      lineGeo.current.setDrawRange(0, Math.floor(lineGeo.current.index.count * p));
    }
    if (fc.current) fc.current.scale.x = Math.max(0.001, easeOut((t - GROW[0]) / (GROW[1] - GROW[0])));
  });

  const anchors = [
    { ref: refs.first, pos: [ax[0], -0.05, 0.8] },
    { ref: refs.lastLabel, pos: [ax[last], -0.05, 0.8] },
    { ref: refs.lastValue, pos: [ax[last], fy[0] + 0.35, 0], shift: '-50%, -100%', show: () => clock.current > DRAW[1] },
    { ref: refs.fcValue, pos: [ax[last] + fx[fx.length - 1], Math.max(...forecast.map((p) => y(p.high))) + 0.3, 0], shift: '-50%, -100%', show: () => clock.current > GROW[1] },
  ];

  return (
    <group ref={group} position={[0, -1.2, 0]} rotation={[0, -0.32, 0]}>
      <Platform width={width + 1.2} depth={1.8} colors={colors} />
      {actual.map((p, i) => (
        <Riser key={i} x={ax[i]} h={y(p.value)} color={colors.series[0]} start={DRAW[0] + (i / actual.length) * (DRAW[1] - DRAW[0]) - 0.25}
          dur={0.5} clock={clock} width={Math.min(0.16, step * 0.4)} opacity={0.35} />
      ))}
      <mesh castShadow>
        <tubeGeometry ref={lineGeo} args={[curve, 220, 0.04, 12, false]} />
        <meshPhysicalMaterial color={color} emissive={color} emissiveIntensity={0.45} roughness={0.25} clearcoat={1} />
      </mesh>
      {pts.map((p, i) => <Dot key={i} pos={p} color={color} at={DRAW[0] + (i / Math.max(1, last)) * (DRAW[1] - DRAW[0])} clock={clock} />)}
      <group ref={fc} position={[ax[last], 0, 0]}>
        <mesh geometry={band}>
          <meshStandardMaterial color={color} transparent opacity={0.22} side={DoubleSide} depthWrite={false} />
        </mesh>
        <mesh>
          <tubeGeometry args={[fcurve, 80, 0.028, 10, false]} />
          <meshStandardMaterial color={color} emissive={color} emissiveIntensity={0.3} transparent opacity={0.75} />
        </mesh>
        {fx.slice(1).map((x, i) => (
          <mesh key={i} position={[x, fy[i + 1] + 0.02, 0]} castShadow>
            <sphereGeometry args={[0.07, 20, 20]} />
            <meshPhysicalMaterial color="#ffffff" emissive={color} emissiveIntensity={0.4} clearcoat={1} />
          </mesh>
        ))}
      </group>
      <Anchors group={group} anchors={anchors} />
    </group>
  );
}

function Dot({ pos, color, at, clock }) {
  const ref = useRef();
  useFrame(() => { if (ref.current) ref.current.scale.setScalar(Math.max(0.001, easeOut((clock.current - at) / 0.3))); });
  return (
    <mesh ref={ref} position={pos} castShadow>
      <sphereGeometry args={[0.06, 20, 20]} />
      <meshPhysicalMaterial color="#ffffff" emissive={color} emissiveIntensity={0.25} clearcoat={1} />
    </mesh>
  );
}

/** actual: [{ label, value }] complete periods; forecast: [{ label, value, low, high }]; texts are preformatted. */
export default function ForecastRibbon3D({ actual, forecast, firstLabel, lastLabel, lastText, forecastText, mode = 'full', active = true }) {
  const refs = { first: useRef(null), lastLabel: useRef(null), lastValue: useRef(null), fcValue: useRef(null) };
  return (
    <div className="bars3d moment-scene">
      <MomentCanvas animate={active && mode !== 'static'} mode={mode} camera={[0, 2.3, 8.2]} reach={6}>
        <Scene actual={actual} forecast={forecast} refs={refs} />
      </MomentCanvas>
      <span ref={refs.first} className="m-label m-axis">{firstLabel}</span>
      <span ref={refs.lastLabel} className="m-label m-axis">{lastLabel}</span>
      <span ref={refs.lastValue} className="m-label m-muted" style={{ opacity: 0 }}>{lastText}</span>
      <div ref={refs.fcValue} className="m-label m-big m-forecast" style={{ opacity: 0 }}>{forecastText}</div>
    </div>
  );
}
