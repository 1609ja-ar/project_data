import { Suspense, useEffect, useRef, useState } from 'react';
import { Skeleton } from '../components/ui/index.js';
import { get3DMode } from './capabilities.js';
import ErrorBoundary from '../components/ErrorBoundary.jsx';

/**
 * Renders a lazily-loaded 3D scene only when 3D is allowed, otherwise the static fallback.
 * The scene receives `active` (false when off-screen or the tab is hidden) and `mode`.
 */
export default function Lazy3D({ scene: Scene, fallback, height = 360, sceneProps = {}, label }) {
  const ref = useRef(null);
  const [mode] = useState(get3DMode);
  const [onScreen, setOnScreen] = useState(false);
  const [tabVisible, setTabVisible] = useState(() => (typeof document === 'undefined' ? true : !document.hidden));

  useEffect(() => {
    if (!ref.current || typeof IntersectionObserver === 'undefined') {
      setOnScreen(true);
      return undefined;
    }
    const io = new IntersectionObserver(([e]) => setOnScreen(e.isIntersecting), { rootMargin: '100px' });
    io.observe(ref.current);
    return () => io.disconnect();
  }, []);

  useEffect(() => {
    const onVis = () => setTabVisible(!document.hidden);
    document.addEventListener('visibilitychange', onVis);
    return () => document.removeEventListener('visibilitychange', onVis);
  }, []);

  if (mode === 'off') return <div role="img" aria-label={label}>{fallback}</div>;

  return (
    <div ref={ref} style={{ height, position: 'relative' }} role="img" aria-label={label} data-3d-mode={mode}>
      <ErrorBoundary title="3D view unavailable">
        <Suspense fallback={<Skeleton height={height} radius="var(--r-lg)" />}>
          <Scene active={onScreen && tabVisible && mode !== 'static'} mode={mode} {...sceneProps} />
        </Suspense>
      </ErrorBoundary>
    </div>
  );
}
