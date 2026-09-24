import { cleanup, render, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";
import { App } from "../App.tsx";
import { mockBody, pageSkeleton } from "../test/skeleton.ts";

/** Every read is refused, so the page renders only what it keeps without the API. */
function mount(path: string) {
  const fetch = (() => Promise.resolve(new Response("", { status: 404 }))) as typeof globalThis.fetch;
  window.history.pushState({}, "", path);
  return render(<App fetch={fetch} />);
}

afterEach(cleanup);

describe("a page whose reads are all refused keeps the mock's shape", () => {
  it.each([
    ["/", "overview.html"],
    ["/agents", "agents.html"],
  ])("%s matches %s section for section", async (path, page) => {
    const { container } = mount(path);
    await waitFor(() => expect(container.querySelector("footer.diag")?.textContent).toContain("not_found"));
    expect(pageSkeleton(container)).toBe(pageSkeleton(mockBody(page)));
  });
});
