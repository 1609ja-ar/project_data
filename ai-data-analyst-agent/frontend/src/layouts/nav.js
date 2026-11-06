import { BarChart3, Database, FileDown, Grid3x3, FileSpreadsheet, FileText, Home, Lightbulb, MessageSquare, Terminal, Upload } from 'lucide-react';

// Each area of the app has its own colour (tokens --m-<name>), used for its icon and active state.
export const MODULES = {
  home: { label: 'Home', icon: Home },
  dashboard: { label: 'Dashboard', icon: BarChart3 },
  ask: { label: 'Ask', icon: MessageSquare },
  insights: { label: 'Insights', icon: Lightbulb },
  pivot: { label: 'Pivot', icon: Grid3x3 },
  reports: { label: 'Reports', icon: FileText },
  datasets: { label: 'Datasets', icon: Database },
  upload: { label: 'Upload', icon: Upload },
  sql: { label: 'SQL', icon: Terminal },
  downloads: { label: 'Clean data', icon: FileDown },
  exports: { label: 'Excel & Power BI', icon: FileSpreadsheet },
};

const item = (m, to, end) => ({ to, label: MODULES[m].label, icon: MODULES[m].icon, module: m, end });

// Only pages that are actually built appear here (no placeholder links). SQL is reached from Datasets and
// "Verify in SQL", not the main menu: most people never need it.
export const NAV = [
  item('home', '/app', true),
  item('dashboard', '/app/dashboard'),
  item('ask', '/app/ask'),
  { section: 'Analyse' },
  item('insights', '/app/insights'),
  item('pivot', '/app/pivot'),
  item('reports', '/app/reports'),
  { section: 'Data' },
  item('datasets', '/app/datasets'),
  item('upload', '/app/upload'),
  { section: 'Share' },
  item('downloads', '/app/downloads'),
  item('exports', '/app/exports'),
];
