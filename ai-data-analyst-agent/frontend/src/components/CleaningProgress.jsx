import { Check, X } from 'lucide-react';
import { ProgressBar } from './ui/index.js';
import { formatInteger } from '../utils/format.js';

const STEPS = [
  { key: 'uploading', label: 'Uploading' },
  { key: 'reading', label: 'Reading' },
  { key: 'cleaning', label: 'Cleaning' },
  { key: 'profiling', label: 'Profiling' },
];
const ORDER = ['uploading', 'reading', 'cleaning', 'profiling', 'done'];

export function Stepper({ stage, failed }) {
  const idx = ORDER.indexOf(stage);
  return (
    <ol className="stepper" aria-label="Processing steps" style={{ listStyle: 'none', padding: 0, margin: 0 }}>
      {STEPS.map((s, i) => {
        const state = failed && i === Math.max(0, idx) ? 'failed' : i < idx || stage === 'done' ? 'done' : i === idx ? 'active' : 'todo';
        return (
          <li key={s.key} className="row" style={{ gap: 8 }}>
            {i > 0 && <span className="step-sep" aria-hidden="true" />}
            <span className="step" data-state={state} aria-current={state === 'active' ? 'step' : undefined}>
              <span className="dot">{state === 'done' ? <Check size={12} /> : state === 'failed' ? <X size={12} /> : i + 1}</span>
              {s.label}
            </span>
          </li>
        );
      })}
    </ol>
  );
}

/** stage: uploading|reading|cleaning|profiling|done|failed ; counts: cleaning report summary (real numbers) */
export default function CleaningProgress({ stage, uploadPct, counts, failed }) {
  // Upload progress is measured; later steps run on the server, so the bar shows the step reached.
  const pct = stage === 'uploading' ? (uploadPct || 0) * 0.25 : stage === 'done' ? 100 : (ORDER.indexOf(stage) / 4) * 100;
  return (
    <div className="stack">
      <Stepper stage={failed ? 'cleaning' : stage} failed={failed} />
      {!failed && <ProgressBar value={pct} label="Processing progress" />}
      <p className="small muted" aria-live="polite">
        {failed
          ? 'Cleaning failed.'
          : counts
            ? `${formatInteger(counts.rows_before)} rows read · ${formatInteger(counts.rows_removed)} removed · ${formatInteger(counts.cells_changed)} values fixed`
            : stage === 'uploading'
              ? `Uploading… ${Math.round(uploadPct || 0)}%`
              : stage === 'reading'
                ? 'Reading and validating the file…'
                : 'Cleaning and profiling the data…'}
      </p>
    </div>
  );
}
