import '@testing-library/jest-dom/vitest';

// jsdom lacks these browser APIs; minimal stand-ins for tests only.
class IO {
  constructor(cb) { this.cb = cb; }
  observe(el) { this.cb([{ isIntersecting: true, target: el }]); }
  unobserve() {}
  disconnect() {}
  takeRecords() { return []; }
}
class RO {
  constructor(cb) { this.cb = cb; }
  observe(el) { this.cb([{ target: el, contentRect: { width: 600, height: 300 } }]); }
  unobserve() {}
  disconnect() {}
}
globalThis.IntersectionObserver ??= IO;
globalThis.ResizeObserver ??= RO;
if (!window.matchMedia) {
  window.matchMedia = (q) => ({ matches: false, media: q, addEventListener() {}, removeEventListener() {}, addListener() {}, removeListener() {} });
}
