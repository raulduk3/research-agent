import { fireEvent, render, screen } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router";
import { describe, expect, it } from "vitest";
import { createClient } from "../api/client.ts";
import { ApiContext } from "../api/context.tsx";
import { mockBody, skeleton } from "../test/skeleton.ts";
import { Login } from "./Login.tsx";

function shell(fetch: typeof globalThis.fetch) {
  const api = createClient({ origin: "", fetch });
  return render(
    <ApiContext.Provider value={api}>
      <MemoryRouter initialEntries={["/login"]}>
        <Routes>
          <Route path="/login" element={<Login />} />
          <Route path="/" element={<h1>home</h1>} />
        </Routes>
      </MemoryRouter>
    </ApiContext.Provider>,
  );
}

function mount(response: Response) {
  const bodies: unknown[] = [];
  const fetch = ((_: RequestInfo | URL, init?: RequestInit) => {
    bodies.push(JSON.parse(String(init?.body)));
    return Promise.resolve(response);
  }) as typeof globalThis.fetch;
  shell(fetch);
  fireEvent.change(screen.getByLabelText(/credential/i), { target: { value: "s3cret" } });
  fireEvent.click(screen.getByRole("button", { name: /sign in/i }));
  return bodies;
}

const reply = (status: number, body: unknown) => new Response(JSON.stringify(body), { status });

describe("owner sign-in", () => {
  it("sends the one credential field and goes home", async () => {
    const bodies = mount(
      reply(200, { contract: "1", data: { authenticated: true, expires_at: "x", csrf_token: "t" } }),
    );
    expect(await screen.findByRole("heading", { name: "home" })).toBeTruthy();
    expect(bodies).toEqual([{ credential: "s3cret" }]);
  });

  it("stays and shows the refusal", async () => {
    mount(reply(403, { contract: "1", error: { code: "forbidden", message: "not the owner", field: null } }));
    expect((await screen.findByRole("alert")).textContent).toBe("not the owner");
  });
});

describe("owner sign-in skeleton", () => {
  it("matches the mock page tag for tag and class for class", () => {
    const { container } = shell(globalThis.fetch);
    expect(skeleton(container)).toBe(skeleton(mockBody("owner-login.html")));
  });
});
