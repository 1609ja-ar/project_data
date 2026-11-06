// Moment 4 - Insights "3D ranking": each finding is a column whose height is its ranking score from the
// insights engine, coloured by severity. Columns race up in rank order; hover shows the headline and clicking
// a column opens that insight.
import { useRef, useState } from 'react';
import { Platform } from '../Stage.jsx';
import useThemeColors from '../../hooks/useThemeColors.js';
import { Anchors, MomentCanvas, Riser, easeBack, useClock } from './common.jsx';

const H = 2.6;
const STEP = 0.78;

function Scene({ items, onPick, hovered, setHovered, refs }) {
  const colors = useThemeColors();
  const group = useRef();
  const clock = useClock(true);
  const tone = { important: colors.danger, notable: colors.warning, info: colors.info };
  const max = Math.max(...items.map((i) => i.score), 1e-9);
  const width = (items.length - 1) * STEP;
  const hs = items.map((it) => Math.max(0.25, (it.score / max) * H));
  const x = (i) => i * STEP - width / 2;
  const anchors = items.flatMap((it, i) => [
    { ref: refs.rank[i], pos: [x(i), hs[i] + 0.32, 0], shift: '-50%, -100%', show: () => clock.current > 0.5 + i * 0.12 + 0.6 },
  ]);
  const hi = items.findIndex((it) => it.id === hovered);
  if (hi >= 0) anchors.push({ ref: refs.tip, pos: [x(hi), hs[hi] + 0.85, 0], shift: '-50%, -100%' });
  return (
    <group ref={group} position={[0, -1.25, 0]} rotation={[0, -0.28, 0]}>
      <Platform width={width + 1.3} depth={1.9} colors={colors} xLines={items.slice(1).map((_, i) => (i + 0.5) * STEP - width / 2)} />
      {items.map((it, i) => (
        <Riser key={it.id} x={x(i)} h={hs[i]} color={tone[it.severity] || colors.info} start={0.2 + i * 0.12} dur={0.9} clock={clock} curve={easeBack}
          width={0.56} emissive={hovered === it.id ? 0.35 : 0}
          onOver={(e) => { e.stopPropagation(); setHovered(it.id); }} onOut={() => setHovered(null)}
          onClick={onPick ? (e) => { e.stopPropagation(); onPick(it.id); } : undefined} />
      ))}
      <Anchors group={group} anchors={anchors} />
    </group>
  );
}

/** items: [{ id, headline, score, severity }] sorted by rank; onPick(id) opens the insight. */
export default function InsightRace3D({ items, onPick, mode = 'full', active = true }) {
  const shown = items.slice(0, 10);
  const [hovered, setHovered] = useState(null);
  const refs = { rank: shown.map(() => ({ current: null })), tip: useRef(null) };
  const tip = shown.find((i) => i.id === hovered);
  return (
    <div className="bars3d moment-scene" style={{ cursor: hovered && onPick ? 'pointer' : 'grab' }}>
      <MomentCanvas animate={(active && mode !== 'static') || Boolean(hovered)} mode={mode} camera={[0, 2.4, 8]} reach={6}>
        <Scene items={shown} onPick={onPick} hovered={hovered} setHovered={setHovered} refs={refs} />
      </MomentCanvas>
      {shown.map((it, i) => (
        <span key={it.id} ref={(el) => { refs.rank[i].current = el; }} className="m-label m-rank" style={{ opacity: 0 }}>#{i + 1}</span>
      ))}
      <div ref={refs.tip} className="bars3d-tip" style={{ opacity: tip ? 1 : 0, maxWidth: 280, whiteSpace: 'normal' }}>
        {tip && <><strong style={{ textTransform: 'capitalize' }}>{tip.severity}</strong> · {tip.headline}</>}
      </div>
    </div>
  );
}
