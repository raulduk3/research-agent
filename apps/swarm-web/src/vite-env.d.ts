/// <reference types="vite/client" />

interface ImportMetaEnv {
  /** Origin of the swarm server's /api/v1; empty or unset means same origin. */
  readonly VITE_API_ORIGIN?: string;
}
