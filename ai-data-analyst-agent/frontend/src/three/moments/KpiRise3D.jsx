// Moment 1 - KPI card icon: last period as a translucent "ghost" column, then the current value rises next
// to it (with a small overshoot) and the figure and change appear above it. Values come from the KPI card.
import { useRef } from 'react';
import { Platform } from '../Stage.jsx';
import useThemeColors from '../../hooks/useThemeColors.js';
import { Anchors, MomentCanvas, Riser, easeBack, useClock } from './common.jsx';

const H = 2.5;

function Scene({ previous, current, color, refs }) {
  const colors = useThemeColors();
  const group = useRef();
  const clock = useClock(true);
  const hasPrev = previous != null && previous > 0;
  const max = Math.max(current || 0, hasPrev ? previous : 0, 1e-9);
  const hc = (Math.max(0, current || 0) / max) * H;
  const hp = hasPrev ? (previous / max) * H : 0;
  const xc = hasPrev ? 0.75 : 0;
  const anchors = [
    { ref: refs.value, pos: [xc, hc + 0.55, 0], shift: '-30%, -100%', show: () => clock.current > 1.3 },
    { ref: refs.cur, pos: [xc, -0.05, 0.8] },
    ...(hasPrev ? [{ ref: refs.prevValue, pos: [-0.75, hp + 0.3, 0], shift: '-80%, -100%', show: () => clock.current > 0.8 },
      { ref: refs.prev, pos: [-0.75, -0.05, 0.8] }] : []),
  ];
  return (
    <group ref={group} position={[0, -1.2, 0]} rotation={[0, -0.35, 0]}>
      <Platform width={hasPrev ? 3.4 : 2.2} depth={2} colors={colors} xLines={hasPrev ? [0] : []} />
      {hasPrev && <Riser x={-0.75} h={hp} color={colors.muted} start={0.1} dur={0.8} clock={clock} opacity={0.35} width={0.9} />}
      <Riser x={xc} h={hc} color={color} start={hasPrev ? 0.6 : 0.1} dur={1.1} clock={clock} curve={easeBack} width={0.9} emissive={0.05} />
      <Anchors group={group} anchors={anchors} />
    </group>
  );
}

/** previous/current: KPI values; *Text: formatted labels; dir: 'up' | 'down' | 'flat'. */
export default function KpiRise3D({ previous, current, prevLabel, curLabel, valueText, prevText, changeText, dir, color, mode = 'full', active = true }) {
  const refs = { value: useRef(null), cur: useRef(null), prev: useRef(null), prevValue: useRef(null) };
  return (
    <div className="bars3d moment-scene">
      <MomentCanvas animate={active && mode !== 'static'} mode={mode} camera={[0, 2.1, 6.6]} reach={4}>
        <Scene previous={previous} current={current} color={color} refs={refs} />
      </MomentCanvas>
      <div ref={refs.value} className="m-label m-big" style={{ opacity: 0 }}>
        {valueText}{changeText && <span className="m-change" data-dir={dir}>{changeText}</span>}
      </div>
      <span ref={refs.cur} className="m-label m-axis">{curLabel}</span>
      {previous != null && (
        <>
          <span ref={refs.prevValue} className="m-label m-muted" style={{ opacity: 0 }}>{prevText}</span>
          <span ref={refs.prev} className="m-label m-axis">{prevLabel}</span>
        </>
      )}
    </div>
  );
}
