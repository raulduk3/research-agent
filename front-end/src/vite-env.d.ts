/// <reference types="vite/client" />

interface ImportMetaEnv {
  /** Origin of the owner app's /api/v1; empty or unset means same origin. */
  readonly VITE_API_ORIGIN?: string;
}
