/** @type {import('tailwindcss').Config} */
// Tailwind v3 classic config. Design language: calm, professional, high-contrast.
// Structure built on slate/ink neutrals; ONE safety accent family (amber) for
// warnings/amendments, plus a deep red used sparingly for critical states.
export default {
  content: ["./index.html", "./src/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        // Semantic aliases so component code reads intentionally.
        ink: {
          DEFAULT: "#0f172a", // slate-900 — primary text / strongest structure
          muted: "#475569",   // slate-600 — secondary text
          faint: "#94a3b8",   // slate-400 — tertiary / metadata
        },
        // Amber = the single safety accent (amendments, citation warnings).
        safety: {
          50: "#fffbeb",
          100: "#fef3c7",
          200: "#fde68a",
          500: "#f59e0b",
          600: "#d97706",
          700: "#b45309",
          900: "#78350f",
        },
        // Deep red, reserved for the most critical / escalated states only.
        critical: {
          50: "#fef2f2",
          200: "#fecaca",
          600: "#dc2626",
          700: "#b91c1c",
        },
      },
      fontFamily: {
        // System font stack — fast, native, no web-font payload.
        sans: [
          "ui-sans-serif", "system-ui", "-apple-system", "Segoe UI",
          "Roboto", "Helvetica Neue", "Arial", "sans-serif",
        ],
        mono: [
          "ui-monospace", "SFMono-Regular", "Menlo", "Consolas",
          "Liberation Mono", "monospace",
        ],
      },
      maxWidth: {
        prose: "46rem", // comfortable reading measure for answers
      },
      keyframes: {
        // Gentle three-dot "thinking" pulse for the loading indicator.
        blink: {
          "0%, 80%, 100%": { opacity: "0.2" },
          "40%": { opacity: "1" },
        },
        // Subtle entrance for new messages.
        rise: {
          "0%": { opacity: "0", transform: "translateY(4px)" },
          "100%": { opacity: "1", transform: "translateY(0)" },
        },
      },
      animation: {
        blink: "blink 1.4s infinite both",
        rise: "rise 0.18s ease-out",
      },
    },
  },
  plugins: [],
};
