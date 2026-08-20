import "@testing-library/jest-dom/vitest";
import { vi } from "vitest";

// jsdom does not implement element scrolling; the app uses it only for visual auto-follow.
Object.defineProperty(HTMLElement.prototype, "scrollTo", {
  configurable: true,
  value: vi.fn(),
});
