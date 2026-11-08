import "@testing-library/jest-dom/vitest";

// jsdom has no ResizeObserver; the chart workspace observes its container
class RO {
  observe() {}
  unobserve() {}
  disconnect() {}
}
(globalThis as { ResizeObserver?: unknown }).ResizeObserver ??= RO;
