import { describe, expect, it } from "vitest";
import { mockBody, pageSkeleton, skeleton } from "./skeleton.ts";

const body = (html: string) => new DOMParser().parseFromString(html, "text/html").body;

describe("page skeleton", () => {
  it("keeps tags, classes and nesting and strips text and attributes", () => {
    expect(skeleton(body('<div class="b a" id="x">t<p class="meta">u</p></div>'))).toBe("div.a.b\n  p.meta");
  });

  it("collapses a run of like siblings so list length does not count", () => {
    const three = body("<ul><li class=r>1</li><li class=r>2</li><li class=r>3</li></ul>");
    const one = body("<ul><li class=r>1</li></ul>");
    expect(skeleton(three)).toBe(skeleton(one));
  });

  it("tells a different class, tag or nesting apart", () => {
    const base = skeleton(body('<div class="card"><h3>t</h3></div>'));
    expect(skeleton(body('<div class="box"><h3>t</h3></div>'))).not.toBe(base);
    expect(skeleton(body('<section class="card"><h3>t</h3></section>'))).not.toBe(base);
    expect(skeleton(body('<div class="card"></div><h3>t</h3>'))).not.toBe(base);
  });

  it("ignores unclassed bold and breaks but keeps classed spans", () => {
    expect(skeleton(body("<p>a<b>b</b><br>c</p>"))).toBe("p");
    expect(skeleton(body('<p>a<span class="rights">c</span></p>'))).toBe("p\n  span.rights");
  });

  it("lets a list be empty but not a section be missing", () => {
    const full = body('<h1>t</h1><div class="board"><div class="lane">x</div></div><table><tr><th>a</th></tr><tr><td>1</td></tr></table>');
    const empty = body('<h1>t</h1><div class="board"></div><table><tr><th>a</th></tr></table>');
    const missing = body("<h1>t</h1><table><tr><th>a</th></tr></table>");
    expect(pageSkeleton(empty)).toBe(pageSkeleton(full));
    expect(pageSkeleton(missing)).not.toBe(pageSkeleton(full));
  });

  it("reads a mock page from the repository", () => {
    expect(skeleton(mockBody("owner-login.html"))).toContain("form.box");
  });
});
