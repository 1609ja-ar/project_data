// Decides whether (and how richly) 3D may render. Every 3D element has a static fallback.

export function is3DEnabledByFlag() {
  return String(import.meta.env.VITE_ENABLE_3D ?? 'true').toLowerCase() !== 'false';
}

export function hasWebGL() {
  try {
    const canvas = document.createElement('canvas');
    return Boolean(window.WebGLRenderingContext && (canvas.getContext('webgl2') || canvas.getContext('webgl')));
  } catch {
    return false;
  }
}

export function prefersReducedMotion() {
  return typeof window !== 'undefined' && window.matchMedia ? window.matchMedia('(prefers-reduced-motion: reduce)').matches : false;
}

export function isLowPower() {
  if (typeof navigator === 'undefined') return false;
  const cores = navigator.hardwareConcurrency || 8;
  const mem = navigator.deviceMemory || 8;
  const small = typeof window !== 'undefined' && window.innerWidth < 640;
  return cores <= 4 || mem <= 4 || small;
}

/** 'off' (static fallback) | 'static' (render once, no animation) | 'lite' | 'full' */
export function get3DMode() {
  if (!is3DEnabledByFlag() || !hasWebGL()) return 'off';
  if (prefersReducedMotion()) return 'static';
  return isLowPower() ? 'lite' : 'full';
}
