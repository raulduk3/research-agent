import { settingsRequestSchema, revisionAnswerSchema } from "./contracts.ts";
import { z } from "zod";
import { afterEach, expect, test, vi } from "vitest";
import { fakeServer, signIn } from "../test/server.ts";
import { ApiError, createClient, readSession } from "./client.ts";

const okSchema = z.object({ ok: z.boolean() });

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
  await api.get("/api/v1/islands/cs", okSchema);
  expect(server.calls[1]?.headers["Authorization"]).toBe("Bearer t-cs");
});

test("a refused session is dropped and the shell is told", async () => {
  signIn();
  const server = fakeServer({ "GET /api/v1/islands/cs": new Response(JSON.stringify({ detail: "session expired" }), { status: 401 }) });
  const onUnauthenticated = vi.fn();
  const api = createClient({ origin: "", fetch: server.fetch, onUnauthenticated });
  await expect(api.get("/api/v1/islands/cs", okSchema)).rejects.toMatchObject({ status: 401, message: "session expired" });
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

test.each([{}, { island: "cs", token: 42 }, { island: "cs", token: "" }, []])("malformed persisted session is ignored", (value) => {
  localStorage.setItem("atoll.session", JSON.stringify(value));
  expect(readSession()).toBeNull();
});

test.each([{ island: "cs" }, { island: "cs", token: 42 }, { island: "cs", token: "" }, { island: "", token: "t-cs" }])("malformed login cannot establish a session", async (answer) => {
  const server = fakeServer({ "POST /api/v1/login": answer });
  const api = createClient({ origin: "", fetch: server.fetch });
  await expect(api.login("cs", "code")).rejects.toMatchObject({ status: 200, message: "the server's answer did not match its contract" });
  expect(api.session).toBeNull();
  expect(readSession()).toBeNull();
});

test.each([{ ok: "true" }, {}, null, []])("malformed successful read is rejected at the client boundary", async (answer) => {
  const server = fakeServer({ "GET /data": answer });
  const api = createClient({ origin: "", fetch: server.fetch });
  await expect(api.get("/data", okSchema)).rejects.toBeInstanceOf(ApiError);
});

test.each([new Response(null, { status: 204 }), { ok: "true" }])("a successful write must return its contracted response", async (answer) => {
  const server = fakeServer({ "POST /write": answer });
  const api = createClient({ origin: "", fetch: server.fetch });
  await expect(api.post("/write", {}, z.object({}), okSchema)).rejects.toMatchObject({ message: "the server's answer did not match its contract" });
});

test("an invalid write is rejected before it reaches the server", () => {
  const server = fakeServer({});
  const api = createClient({ origin: "", fetch: server.fetch });
  expect(() => api.post("/write", { value: "" }, z.object({ value: z.string().min(1) }), okSchema)).toThrow();
  expect(server.calls).toEqual([]);
});

test.each([null, ["error"], { detail: 42 }])("a malformed refusal retains its HTTP status", async (answer) => {
  const server = fakeServer({ "POST /write": new Response(JSON.stringify(answer), { status: 403 }) });
  const api = createClient({ origin: "", fetch: server.fetch });
  await expect(api.post("/write", {}, z.object({}), okSchema)).rejects.toMatchObject({ status: 403, message: "request refused (403)" });
});


test("changing two island switches is refused before sending", () => {
  const server = fakeServer({});
  const api = createClient({ origin: "", fetch: server.fetch });
  expect(() => api.post("/api/v1/islands/cs/settings", { evolution_enabled: false, mutation_enabled: true }, settingsRequestSchema, revisionAnswerSchema)).toThrow();
  expect(server.calls).toEqual([]);
});
