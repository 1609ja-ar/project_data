import { useState } from 'react';
import { Box } from 'lucide-react';
import { Button, Modal } from './ui/index.js';
import Lazy3D from '../three/Lazy3D.jsx';

/**
 * A short 3D animation in a dialog (a "moment"), opened from an icon. The scene is lazy-loaded, so nothing
 * 3D is downloaded until someone clicks; with reduced motion the final frame is shown without animation.
 */
export function Moment3D({ open, onClose, title, caption, scene, sceneProps, height = 380, fallback, footer }) {
  const [run, setRun] = useState(0);
  return (
    <Modal open={open} onClose={onClose} title={title} width={760}
      footer={footer || <><Button variant="ghost" onClick={() => setRun((r) => r + 1)}>Replay</Button><Button onClick={onClose}>Done</Button></>}>
      <div className="moment">
        {open && (
          <Lazy3D key={run} scene={scene} height={height} label={title} sceneProps={sceneProps}
            fallback={fallback || <div className="moment-fallback">{caption}</div>} />
        )}
        {caption && <p className="moment-caption">{caption}</p>}
      </div>
    </Modal>
  );
}

/** Small icon button that opens a moment. */
export function Moment3DButton({ label, onClick, size = 'sm', icon = Box, children }) {
  return (
    <Button variant="ghost" size={size} icon={icon} onClick={onClick} aria-label={label} title={label}>{children}</Button>
  );
}
