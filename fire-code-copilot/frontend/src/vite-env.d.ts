/// <reference types="vite/client" />

// Typed environment variables exposed to the client (must be prefixed VITE_).
interface ImportMetaEnv {
  /** Base URL of the FastAPI backend. Defaults to http://localhost:8000. */
  readonly VITE_API_BASE?: string;
}

interface ImportMeta {
  readonly env: ImportMetaEnv;
}
