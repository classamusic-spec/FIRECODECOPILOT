/// <reference types="vite/client" />

// Self-hosted font packages ship CSS with no type declarations; declare it so
// `import "@fontsource-variable/inter"` type-checks (Vite bundles the CSS).
declare module "@fontsource-variable/inter";

// Typed environment variables exposed to the client (must be prefixed VITE_).
interface ImportMetaEnv {
  /** Base URL of the FastAPI backend. Defaults to http://localhost:8000. */
  readonly VITE_API_BASE?: string;
  /** "1" forces demo/showcase mode (also enabled by a ?demo query param). */
  readonly VITE_DEMO?: string;
}

interface ImportMeta {
  readonly env: ImportMetaEnv;
}
