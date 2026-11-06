import { useMemo } from 'react';
import { cssVar, useTheme } from '../context/ThemeContext.jsx';

const SERIES = ['--chart-1', '--chart-2', '--chart-3', '--chart-4', '--chart-5', '--chart-6', '--chart-7', '--chart-8'];

// Reads chart/3D colors from CSS tokens; recomputes whenever the resolved theme changes.
export default function useThemeColors() {
  const { resolved } = useTheme();
  return useMemo(
    () => ({
      theme: resolved,
      series: SERIES.map((v) => cssVar(v) || '#2a78d6'),
      grid: cssVar('--chart-grid') || '#e2e6ef',
      axis: cssVar('--chart-axis') || '#64748b',
      text: cssVar('--text') || '#0f172a',
      muted: cssVar('--text-muted') || '#475569',
      surface: cssVar('--bg-elev') || '#ffffff',
      bg: cssVar('--bg') || '#f7f8fc',
      primary: cssVar('--primary') || '#4f46e5',
      border: cssVar('--border') || '#e2e6ef',
      success: cssVar('--success') || '#0f7a3d',
      warning: cssVar('--warning') || '#935700',
      danger: cssVar('--danger') || '#b42318',
      info: cssVar('--info') || '#1d5bd6',
    }),
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [resolved],
  );
}
