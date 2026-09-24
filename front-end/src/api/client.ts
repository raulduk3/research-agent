// The one door to /api/v1 (docs/contracts/api-v1/README.md): the envelope, the refusal
// envelope, the session cookie, X-CSRF-Token and Idempotency-Key on every POST.

export type ErrorCode =
  | "invalid_request"
  | "unauthenticated"
  | "forbidden"
  | "not_found"
  | "state_conflict"
  | "not_saved"
  | "unavailable";

/** The code the contract fixes for each refusal status, for a body that is not the envelope. */
const CODE_BY_STATUS: Record<number, ErrorCode> = {
  400: "invalid_request",
  401: "unauthenticated",
  403: "forbidden",
  404: "not_found",
  409: "state_conflict",
  422: "invalid_request",
  502: "not_saved",
  503: "unavailable",
};

export class ApiError extends Error {
  readonly status: number;
  readonly code: ErrorCode;
  readonly field: string | null;

  constructor(status: number, code: ErrorCode, message: string, field: string | null) {
    super(message);
    this.name = "ApiError";
    this.status = status;
    this.code = code;
    this.field = field;
  }
}

/** A list directly under `data`; `next_cursor` goes back verbatim. */
export interface Page<T> {
  items: T[];
  next_cursor: string | null;
}

export interface ClientOptions {
  /** Origin of the owner app; empty means same origin. */
  origin: string;
  fetch?: typeof fetch;
  /** Called on every 401, so the shell can send the owner to sign in. */
  onUnauthenticated?: () => void;
}

export type Query = Record<string, string | null | undefined>;

export interface ApiClient {
  get<T>(path: string, query?: Query): Promise<T>;
  post<T>(path: string, body: Record<string, string>, idempotencyKey: string): Promise<T>;
  login(credential: string): Promise<void>;
  logout(): Promise<void>;
  readonly signedIn: boolean;
}

/** A key per intended action; a retry of the same action reuses it. */
export function newIdempotencyKey(): string {
  return crypto.randomUUID();
}

export function createClient(options: ClientOptions): ApiClient {
  const doFetch = options.fetch ?? globalThis.fetch.bind(globalThis);
  let csrf: string | null = null;

  function url(path: string, query?: Query): string {
    const params = new URLSearchParams();
    for (const [k, v] of Object.entries(query ?? {})) if (v != null) params.set(k, v);
    const qs = params.toString();
    return `${options.origin}${path}${qs ? `?${qs}` : ""}`;
  }

  async function send<T>(method: string, target: string, init: RequestInit): Promise<T> {
    const res = await doFetch(target, { ...init, method, credentials: "include" });
    let body: unknown = null;
    try {
      body = await res.json();
    } catch {
      body = null;
    }
    if (res.ok && isEnvelope(body) && "data" in body) {
      // Every view that renders a form carries the session's token, so a reload can POST again.
      const token = (body.data as { csrf_token?: unknown } | null)?.csrf_token;
      if (typeof token === "string") csrf = token;
      return body.data as T;
    }
    if (res.status === 401) {
      csrf = null;
      options.onUnauthenticated?.();
    }
    if (isEnvelope(body) && "error" in body) {
      const e = body.error as { code: ErrorCode; message: string; field: string | null };
      throw new ApiError(res.status, e.code, e.message, e.field);
    }
    if (res.ok) throw new Error(`${method} ${target}: response is not contract 1`);
    const code = CODE_BY_STATUS[res.status] ?? "unavailable";
    throw new ApiError(res.status, code, res.statusText || code, null);
  }

  function jsonPost(headers: Record<string, string>, body: Record<string, string>): RequestInit {
    return {
      headers: { "Content-Type": "application/json", Accept: "application/json", ...headers },
      body: JSON.stringify(body),
    };
  }

  return {
    get signedIn() {
      return csrf !== null;
    },
    get<T>(path: string, query?: Query) {
      return send<T>("GET", url(path, query), { headers: { Accept: "application/json" } });
    },
    post<T>(path: string, body: Record<string, string>, idempotencyKey: string) {
      if (csrf === null) {
        return Promise.reject(new ApiError(401, "unauthenticated", "not signed in", null));
      }
      return send<T>(
        "POST",
        url(path),
        jsonPost({ "X-CSRF-Token": csrf, "Idempotency-Key": idempotencyKey }, body),
      );
    },
    async login(credential: string) {
      // The one POST without a session: no CSRF token, no idempotency key.
      const session = await send<{ csrf_token: string }>(
        "POST",
        url("/api/v1/login"),
        jsonPost({}, { credential }),
      );
      csrf = session.csrf_token;
    },
    async logout() {
      if (csrf !== null) await this.post("/api/v1/logout", {}, newIdempotencyKey());
      csrf = null;
    },
  };
}

function isEnvelope(body: unknown): body is { contract: "1" } & Record<string, unknown> {
  return typeof body === "object" && body !== null && (body as { contract?: unknown }).contract === "1";
}
