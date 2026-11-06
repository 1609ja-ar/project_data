import { Monitor, Moon, Sun } from 'lucide-react';
import { Segmented } from './ui/index.js';
import { useTheme } from '../context/ThemeContext.jsx';

const OPTIONS = [
  { value: 'light', label: 'Light', icon: Sun },
  { value: 'dark', label: 'Dark', icon: Moon },
  { value: 'system', label: 'System', icon: Monitor },
];

export default function ThemeSwitcher({ showLabels = false }) {
  const { mode, setMode } = useTheme();
  return (
    <Segmented
      label="Color theme"
      value={mode}
      onChange={setMode}
      options={OPTIONS.map((o) => ({ ...o, showLabel: showLabels }))}
    />
  );
}
