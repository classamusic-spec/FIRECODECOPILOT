/** @type {import('tailwindcss').Config} */
// Fire Code CoPilot — premium "navy cockpit" theme.
// Firefighter palette: deep NAVY structure, a single CORAL hot-accent (brand,
// CTAs, Connecticut amendments), cool STEEL greys for type, WHITE for emphasis.
// Futuristic but authoritative: glass panels on a navy canvas with a soft coral glow.
export default {
  content: ["./index.html", "./src/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        // Structural navy — from near-black canvas up to lifted surfaces.
        navy: {
          950: "#05090F",
          900: "#070D1A",
          850: "#0A1426",
          800: "#0D1B30",
          700: "#11233F",
          600: "#16304F",
          500: "#1E3E63",
          400: "#2C5283",
        },
        // The fire accent. Used sparingly: brand mark, primary actions, amendments.
        coral: {
          200: "#FFC7BB",
          300: "#FFA08D",
          400: "#FF7D66",
          500: "#FF5C42", // primary accent
          600: "#F03E22",
          700: "#C72E16",
        },
        // Cool steel greys for text + secondary surfaces on the dark canvas.
        steel: {
          50: "#F3F6FB",
          100: "#E4EAF3",
          200: "#CBD5E5",
          300: "#A7B4CC",
          400: "#7C8AA6",
          500: "#5A6884",
          600: "#404D67",
          700: "#2C3650",
          800: "#1B2236",
        },
        // Light-on-dark text aliases (also a safety net so any stray text-ink reads light).
        ink: { DEFAULT: "#E7ECF5", muted: "#A7B4CC", faint: "#7C8AA6" },
        // Warnings / amendments ride the coral family (on-brand "hot" attention).
        safety: { 50: "#241009", 200: "#7A3422", 500: "#FF5C42", 600: "#FF7D66", 700: "#FFA08D", 900: "#FFD7CE" },
        // Deep red, reserved for hard errors only.
        critical: { 50: "#2A0F12", 200: "#7C2A2F", 600: "#FF6B6B", 700: "#FF9B9B" },
        // Positive / verified.
        verified: { 50: "#062019", 200: "#1F5C4A", 500: "#34D399", 700: "#86EFC9" },
      },
      fontFamily: {
        sans: ["InterVariable", "Inter", "ui-sans-serif", "system-ui", "-apple-system",
               "Segoe UI", "Roboto", "Helvetica Neue", "Arial", "sans-serif"],
        mono: ["ui-monospace", "SFMono-Regular", "Menlo", "Consolas", "Liberation Mono", "monospace"],
      },
      maxWidth: { prose: "46rem" },
      boxShadow: {
        // Coral glow for the primary action + brand mark.
        glow: "0 0 0 1px rgba(255,92,66,.30), 0 10px 32px -8px rgba(255,92,66,.50)",
        "glow-sm": "0 0 0 1px rgba(255,92,66,.25), 0 6px 18px -8px rgba(255,92,66,.45)",
        // Soft lift for glass cards against the navy canvas.
        card: "0 16px 50px -20px rgba(0,0,0,.65)",
      },
      keyframes: {
        blink: { "0%,80%,100%": { opacity: "0.2" }, "40%": { opacity: "1" } },
        rise: { "0%": { opacity: "0", transform: "translateY(6px)" }, "100%": { opacity: "1", transform: "translateY(0)" } },
        glowpulse: {
          "0%,100%": { boxShadow: "0 0 0 1px rgba(255,92,66,.25), 0 0 22px -6px rgba(255,92,66,.45)" },
          "50%": { boxShadow: "0 0 0 1px rgba(255,92,66,.45), 0 0 34px -4px rgba(255,92,66,.70)" },
        },
      },
      animation: {
        blink: "blink 1.4s infinite both",
        rise: "rise 0.22s ease-out both",
        glowpulse: "glowpulse 2.8s ease-in-out infinite",
      },
    },
  },
  plugins: [],
};
