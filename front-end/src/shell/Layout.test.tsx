import { render } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router";
import { describe, expect, it, vi } from "vitest";
import { createClient } from "../api/client.ts";
import { ApiContext } from "../api/context.tsx";
import { mockBody, skeleton } from "../test/skeleton.ts";
import { Layout } from "./Layout.tsx";

function nav(path: string, onLogout = () => {}) {
  const fetch = (() => Promise.resolve(new Response("", { status: 404 }))) as typeof globalThis.fetch;
  const { container } = render(
    <ApiContext.Provider value={createClient({ origin: "", fetch })}>
      <MemoryRouter initialEntries={[path]}>
        <Routes>
          <Route element={<Layout onLogout={onLogout} />}>
            <Route path="*" element={null} />
          </Route>
        </Routes>
      </MemoryRouter>
    </ApiContext.Provider>,
  );
  return container.querySelector("nav") as HTMLElement;
}

/** The skeleton with the bold marks kept: the mock marks the current page inside the dropdown. */
const shape = (el: Element) =>
  skeleton(el) + "\n" + [...el.querySelectorAll("b")].map((b) => `${b.className}:${b.textContent}`).join(" ");

describe("owner menu", () => {
  it("matches the mock's nav element for element", () => {
    const mock = mockBody("overview.html").querySelector("nav") as HTMLElement;
    const wrap = (el: Element) => {
      const holder = document.createElement("div");
      holder.append(el.cloneNode(true));
      return holder;
    };
    expect(shape(wrap(nav("/")))).toBe(shape(wrap(mock)));
    expect(nav("/").textContent).toBe(mock.textContent);
  });

  it("names the list page above a detail page as current", () => {
    expect(nav("/agents/abc").querySelector("b.here")?.textContent).toBe("agents");
  });

  it("logs out from the dropdown's last link", () => {
    const onLogout = vi.fn();
    const links = nav("/costs", onLogout).querySelectorAll(".more div a");
    const last = links[links.length - 1] as HTMLAnchorElement;
    expect(last.textContent).toBe("log out");
    last.click();
    expect(onLogout).toHaveBeenCalledOnce();
  });
});
