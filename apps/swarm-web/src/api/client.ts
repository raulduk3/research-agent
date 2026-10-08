// The one door to the swarm server's /api/v1 (API.md): plain JSON in and out, the island
// session's token on every request that has one.

import { z } from "zod";
import { errorSchema, loginAnswerSchema, loginRequestSchema, sessionSchema } from "./contracts.ts";
import type { Session } from "./types.ts";
export type { Session } from "./types.ts";

export class ApiError extends Error {
  readonly status: number;

  constructor(status: number, message: string) {
    super(message);
    this.name = "ApiError";
    this.status = status;
  }
}

const SESSION_KEY = "atoll.session";

export function readSession(): Session | null {
  try {
    const raw = localStorage.getItem(SESSION_KEY);
    const result = sessionSchema.safeParse(raw === null ? null : JSON.parse(raw));
    return result.success ? result.data : null;
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
  get<S extends z.ZodType>(path: string, schema: S): Promise<z.output<S>>;
  post<I extends z.ZodType, O extends z.ZodType>(path: string, body: z.input<I>, request: I, response: O): Promise<z.output<O>>;
  login(island: string, password: string): Promise<Session>;
  logout(): void;
  readonly session: Session | null;
}

export function createClient(options: ClientOptions): ApiClient {
  const doFetch = options.fetch ?? globalThis.fetch.bind(globalThis);
  let session = readSession();

  async function send<S extends z.ZodType>(method: string, path: string, body: unknown, signIn: boolean, schema: S): Promise<z.output<S>> {
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
      const result = schema.safeParse(answer);
      if (result.success) return result.data;
      throw new ApiError(res.status, "the server's answer did not match its contract");
    }
    if (res.status === 401 && !signIn) {
      session = null;
      writeSession(null);
      options.onUnauthenticated?.();
    }
    const error = errorSchema.safeParse(answer);
    const detail = error.success ? error.data.detail : null;
    throw new ApiError(res.status, typeof detail === "string" ? detail : res.statusText || `request refused (${res.status})`);
  }

  return {
    get session() {
      return session;
    },
    get<S extends z.ZodType>(path: string, schema: S) {
      return send("GET", path, null, false, schema);
    },
    post<I extends z.ZodType, O extends z.ZodType>(path: string, body: z.input<I>, request: I, response: O) {
      return send("POST", path, request.parse(body), false, response);
    },
    async login(island: string, password: string) {
      const answer = await send("POST", "/api/v1/login", loginRequestSchema.parse({ island, password }), true, loginAnswerSchema);
      // The pages are an island's; the island asked for stands when the answer names none.
      session = { island: answer.island ?? island, token: answer.token };
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
