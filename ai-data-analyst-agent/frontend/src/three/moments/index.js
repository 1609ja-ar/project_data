// Lazy entry points for the five 3D moments, so three.js only loads when one is opened.
import { lazy } from 'react';

export const KpiRise3D = lazy(() => import('./KpiRise3D.jsx'));
export const ForecastRibbon3D = lazy(() => import('./ForecastRibbon3D.jsx'));
export const ShareFlip3D = lazy(() => import('./ShareFlip3D.jsx'));
export const InsightRace3D = lazy(() => import('./InsightRace3D.jsx'));
export const CleaningSort3D = lazy(() => import('./CleaningSort3D.jsx'));
