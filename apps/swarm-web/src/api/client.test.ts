import { afterEach, expect, test, vi } from "vitest";
import { fakeServer, signIn } from "../test/server.ts";
import { ApiError, createClient, readSession } from "./client.ts";

afterEach(() => localStorage.clear());

test("sign-in sends the island and its code, keeps the session and carries its token afterwards", async () => {
  const server = fakeServer({
    "POST https://api.example/api/v1/login": { island: "cs", token: "t-cs" },
    "GET https://api.example/api/v1/islands/cs": { ok: true },
  });
  const api = createClient({ origin: "https://api.example", fetch: server.fetch });
  await api.login("cs", "open sesame");
  expect(server.calls[0]).toMatchObject({ path: "https://api.example/api/v1/login", body: { island: "cs", password: "open sesame" } });
  expect(server.calls[0]?.headers["Authorization"]).toBeUndefined();
  expect(readSession()).toEqual({ island: "cs", token: "t-cs" });
  await api.get("/api/v1/islands/cs");
  expect(server.calls[1]?.headers["Authorization"]).toBe("Bearer t-cs");
});

test("a refused session is dropped and the shell is told", async () => {
  signIn();
  const server = fakeServer({ "GET /api/v1/islands/cs": new Response(JSON.stringify({ detail: "session expired" }), { status: 401 }) });
  const onUnauthenticated = vi.fn();
  const api = createClient({ origin: "", fetch: server.fetch, onUnauthenticated });
  await expect(api.get("/api/v1/islands/cs")).rejects.toMatchObject({ status: 401, message: "session expired" });
  expect(onUnauthenticated).toHaveBeenCalledOnce();
  expect(api.session).toBeNull();
  expect(readSession()).toBeNull();
});

test("a wrong access code is a refusal, not a lost session", async () => {
  const server = fakeServer({ "POST /api/v1/login": new Response(JSON.stringify({ detail: "invalid island credential" }), { status: 403 }) });
  const onUnauthenticated = vi.fn();
  const api = createClient({ origin: "", fetch: server.fetch, onUnauthenticated });
  await expect(api.login("cs", "wrong")).rejects.toBeInstanceOf(ApiError);
  expect(onUnauthenticated).not.toHaveBeenCalled();
});
