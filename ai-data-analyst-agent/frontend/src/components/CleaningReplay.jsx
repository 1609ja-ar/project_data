import { useState } from 'react';
import { Sparkles } from 'lucide-react';
import { Button } from './ui/index.js';
import { Moment3D } from './Moment3D.jsx';
import { CleaningSort3D } from '../three/moments/index.js';
import { formatInteger } from '../utils/format.js';

/** "Replay cleaning in 3D": a button plus the moment, fed by the dataset's cleaning counts. */
export default function CleaningReplay({ counts, columns, label = 'Replay cleaning in 3D', showLabel = false }) {
  const [open, setOpen] = useState(false);
  if (!counts?.rows_before) return null;
  return (
    <>
      <Button variant={showLabel ? 'secondary' : 'ghost'} size="sm" icon={Sparkles} onClick={() => setOpen(true)} aria-label={label} title={label}>
        {showLabel ? 'Replay in 3D' : null}
      </Button>
      <Moment3D open={open} onClose={() => setOpen(false)} title="What cleaning did"
        caption={`${formatInteger(counts.rows_before)} rows read, ${formatInteger(counts.rows_removed)} removed, ${formatInteger(counts.cells_changed)} values fixed. Blocks are scaled to your file: red is the share of rows removed, green the share of values fixed.`}
        scene={CleaningSort3D} sceneProps={{ rowsBefore: counts.rows_before, rowsRemoved: counts.rows_removed, cellsChanged: counts.cells_changed, columns }} />
    </>
  );
}
