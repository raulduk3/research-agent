// The one door to the swarm server's /api/v1 (API.md): plain JSON in and out, the island
// session's token on every request that has one.

import type { LoginAnswer } from "./types.ts";

export class ApiError extends Error {
  readonly status: number;

  constructor(status: number, message: string) {
    super(message);
    this.name = "ApiError";
    this.status = status;
  }
}

/** The island a visitor signed in to, kept in this browser until they leave it. */
export interface Session {
  island: string;
  token: string;
}

const SESSION_KEY = "atoll.session";

export function readSession(): Session | null {
  try {
    const raw = localStorage.getItem(SESSION_KEY);
    const s = raw === null ? null : (JSON.parse(raw) as Partial<Session> | null);
    return s && typeof s.island === "string" && typeof s.token === "string" ? { island: s.island, token: s.token } : null;
  } catch {
    return null;
  }
}

function writeSession(session: Session | null): void {
  try {
    if (session === null) localStorage.removeItem(SESSION_KEY);
    else localStorage.setItem(SESSION_KEY, JSON.stringify(session));
  } catch {
    // A browser that refuses storage keeps the session for this page only.
  }
}

export interface ClientOptions {
  /** Origin of the swarm server; empty means same origin. */
  origin: string;
  fetch?: typeof fetch;
  /** Called when the server refuses the session, so the shell can ask for the island again. */
  onUnauthenticated?: () => void;
}

export interface ApiClient {
  get<T>(path: string): Promise<T>;
  post<T>(path: string, body: Record<string, string>): Promise<T>;
  login(island: string, password: string): Promise<Session>;
  logout(): void;
  readonly session: Session | null;
}

export function createClient(options: ClientOptions): ApiClient {
  const doFetch = options.fetch ?? globalThis.fetch.bind(globalThis);
  let session = readSession();

  async function send<T>(method: string, path: string, body: Record<string, string> | null, signIn: boolean): Promise<T> {
    const headers: Record<string, string> = { Accept: "application/json" };
    if (body !== null) headers["Content-Type"] = "application/json";
    if (session !== null && !signIn) headers["Authorization"] = `Bearer ${session.token}`;
    const res = await doFetch(`${options.origin}${path}`, {
      method,
      headers,
      credentials: "include",
      ...(body === null ? {} : { body: JSON.stringify(body) }),
    });
    let answer: unknown = null;
    try {
      answer = await res.json();
    } catch {
      answer = null;
    }
    if (res.ok) {
      if (answer !== null && typeof answer === "object") return answer as T;
      // A write the server accepted without a body is still done; a read needs its answer.
      if (method !== "GET" && !signIn) return {} as T;
      throw new ApiError(res.status, "the server's answer was not readable");
    }
    if (res.status === 401 && !signIn) {
      session = null;
      writeSession(null);
      options.onUnauthenticated?.();
    }
    const detail = (answer as { detail?: unknown } | null)?.detail;
    throw new ApiError(res.status, typeof detail === "string" ? detail : res.statusText || `request refused (${res.status})`);
  }

  return {
    get session() {
      return session;
    },
    get<T>(path: string) {
      return send<T>("GET", path, null, false);
    },
    post<T>(path: string, body: Record<string, string>) {
      return send<T>("POST", path, body, false);
    },
    async login(island: string, password: string) {
      const answer = await send<LoginAnswer>("POST", "/api/v1/login", { island, password }, true);
      session = { island: answer.island, token: answer.token };
      writeSession(session);
      return session;
    },
    logout() {
      session = null;
      writeSession(null);
    },
  };
}

export function refusal(error: unknown): string {
  if (error instanceof ApiError) return error.message;
  return error instanceof Error ? error.message : "request failed";
}
