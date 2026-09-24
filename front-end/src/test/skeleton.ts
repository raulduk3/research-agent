/**
 * The tag-and-class skeleton of a page: every element as `tag.class.class`, text and
 * attributes stripped, children indented under their parent. A run of siblings with the
 * same skeleton collapses to one, so list lengths do not count; unclassed phrasing
 * elements (bold, line breaks) are text and do not count either.
 */

const PHRASING = new Set(["b", "i", "em", "strong", "br", "small", "sup", "sub", "wbr"]);
const IGNORED = new Set(["script", "style", "template", "link", "meta", "title"]);

/**
 * The items of a page's lists: a table's data rows, a chart's marks and the repeated entries of
 * the mock's boards. A page whose reads are refused renders each list empty, so a comparison with the
 * mock drops these on both sides; everything else must be there, in order. A replay's stage is
 * drawn by the mock's script, so the static mock holds it empty.
 */
export const LIST_ITEMS: readonly string[] = [
  "tr:has(> td)",
  "svg > *",
  ".board > .lane",
  ".tiles > .trow",
  ".secs > .chp",
  ".pgs > .pg",
  ".thread > .turn",
  ".reads > .readtile",
  ".life > .lifeday",
  ".stage > *",
];

function line(el: Element): string {
  const classes = [...el.classList].sort();
  return [el.tagName.toLowerCase(), ...classes].join(".");
}

function lines(el: Element, depth: number): string[] {
  const out: string[] = [];
  let previous: string | null = null;
  for (const child of el.children) {
    const tag = child.tagName.toLowerCase();
    if (IGNORED.has(tag)) continue;
    if (PHRASING.has(tag) && child.classList.length === 0) continue;
    const block = [`${"  ".repeat(depth)}${line(child)}`, ...lines(child, depth + 1)].join("\n");
    if (block === previous) continue;
    out.push(block);
    previous = block;
  }
  return out;
}

/** The shell `Layout` owns on every page: the menu, the health line and the lab line. */
const SHELL: readonly string[] = ["body > nav:first-child", "body > footer.diag", "body > .lab"];

/** The skeleton of `root`'s children, as text for a readable diff. */
export function skeleton(root: Element): string {
  return lines(root, 0).join("\n");
}

/** A copy of `root` without the elements `selectors` match. */
function without(root: Element, selectors: readonly string[]): Element {
  const copy = root.cloneNode(true) as Element;
  for (const el of selectors.flatMap((selector) => [...copy.querySelectorAll(selector)])) el.remove();
  return copy;
}

const MOCK: Record<string, string> = import.meta.glob("../../design-mock/*.html", {
  query: "?raw",
  import: "default",
  eager: true,
});

/** The body of a design-mock page, parsed. */
export function mockBody(page: string): HTMLElement {
  const html = MOCK[`../../design-mock/${page}`];
  if (html === undefined) throw new Error(`no mock page ${page}`);
  return new DOMParser().parseFromString(html, "text/html").body;
}

/** A page's skeleton with its lists emptied: the shape a page keeps whatever the API says. */
export function pageSkeleton(root: Element): string {
  return skeleton(without(root, LIST_ITEMS));
}

/** A mock page's shape without the shell: what a page component renders alone. */
export function mockShape(page: string): string {
  return pageSkeleton(without(mockBody(page), SHELL));
}
