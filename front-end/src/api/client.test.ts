import { describe, expect, it } from "vitest";
import { ApiError, createClient } from "./client.ts";

interface Seen {
  url: string;
  init: RequestInit;
}

/** A server that answers each request with the next canned response and records what it got. */
function server(...responses: Response[]) {
  const seen: Seen[] = [];
  const fetch = (input: RequestInfo | URL, init?: RequestInit) => {
    seen.push({ url: String(input), init: init ?? {} });
    const next = responses.shift();
    if (!next) throw new Error("unexpected request");
    return Promise.resolve(next);
  };
  return { fetch: fetch as typeof globalThis.fetch, seen };
}

const json = (status: number, body: unknown) =>
  new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });

// A Response body reads once, so each test gets a fresh one.
const session = () =>
  json(200, {
    contract: "1",
    data: { authenticated: true, expires_at: "2026-09-25T00:00:00.000000Z", csrf_token: "t0k" },
  });

describe("api client", () => {
  it("unwraps data and sends the cookie to the configured origin", async () => {
    const s = server(json(200, { contract: "1", data: { items: [], next_cursor: null } }));
    const api = createClient({ origin: "https://owner.example", fetch: s.fetch });
    await expect(api.get("/api/v1/agents", { cursor: "c/1", island: null })).resolves.toEqual({
      items: [],
      next_cursor: null,
    });
    expect(s.seen[0]?.url).toBe("https://owner.example/api/v1/agents?cursor=c%2F1");
    expect(s.seen[0]?.init.credentials).toBe("include");
  });

  it("raises the refusal envelope's code and field, not the HTTP reason", async () => {
    const s = server(
      json(409, { contract: "1", error: { code: "state_conflict", message: "retired", field: "lineage_id" } }),
    );
    const api = createClient({ origin: "", fetch: s.fetch });
    const err = await api.get("/api/v1/agents/x").catch((e: unknown) => e);
    expect(err).toBeInstanceOf(ApiError);
    expect(err).toMatchObject({ status: 409, code: "state_conflict", field: "lineage_id" });
  });

  it("maps a non-envelope refusal to the contract's code for its status", async () => {
    const s = server(new Response("<html>bad gateway</html>", { status: 502 }));
    const api = createClient({ origin: "", fetch: s.fetch });
    await expect(api.get("/api/v1/health")).rejects.toMatchObject({ code: "not_saved" });
  });

  it("rejects a 200 that is not contract 1", async () => {
    const s = server(json(200, { contract: "2", data: {} }));
    const api = createClient({ origin: "", fetch: s.fetch });
    await expect(api.get("/api/v1/health")).rejects.toThrow("not contract 1");
  });

  it("signs in without headers, then posts with the session's CSRF token and the caller's key", async () => {
    const s = server(session(), json(200, { contract: "1", data: { ok: true } }));
    const api = createClient({ origin: "", fetch: s.fetch });
    await api.login("secret");
    const loginHeaders = s.seen[0]?.init.headers as Record<string, string>;
    expect(loginHeaders["X-CSRF-Token"]).toBeUndefined();
    expect(loginHeaders["Idempotency-Key"]).toBeUndefined();
    expect(api.signedIn).toBe(true);

    await api.post("/api/v1/agents/c1/retire", {}, "key-1");
    const headers = s.seen[1]?.init.headers as Record<string, string>;
    expect(headers["X-CSRF-Token"]).toBe("t0k");
    expect(headers["Idempotency-Key"]).toBe("key-1");
  });

  it("drops the session and tells the shell on 401", async () => {
    let told = 0;
    const s = server(session(), json(401, { contract: "1", error: { code: "unauthenticated", message: "", field: null } }));
    const api = createClient({ origin: "", fetch: s.fetch, onUnauthenticated: () => (told += 1) });
    await api.login("secret");
    await expect(api.get("/api/v1/costs")).rejects.toMatchObject({ code: "unauthenticated" });
    expect(told).toBe(1);
    expect(api.signedIn).toBe(false);
  });

  it("refuses a POST before sign-in without calling the server", async () => {
    const s = server();
    const api = createClient({ origin: "", fetch: s.fetch });
    await expect(api.post("/api/v1/seed", {}, "k")).rejects.toMatchObject({ code: "unauthenticated" });
    expect(s.seen).toHaveLength(0);
  });

  it("takes the session's token from a form view, so a reload can post again", async () => {
    const s = server(
      json(200, { contract: "1", data: { emphasis_fields: {}, copied: null, csrf_token: "v13w" } }),
      json(201, { contract: "1", data: { configuration_id: "c" } }),
    );
    const api = createClient({ origin: "", fetch: s.fetch });
    await api.get("/api/v1/seed");
    expect(api.signedIn).toBe(true);
    await api.post("/api/v1/seed", {}, "k");
    expect(new Headers(s.seen[1]?.init.headers).get("X-CSRF-Token")).toBe("v13w");
  });
});
