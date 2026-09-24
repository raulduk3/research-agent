/**
 * The tag-and-class skeleton of a page: every element as `tag.class.class`, text and
 * attributes stripped, children indented under their parent. A run of siblings with the
 * same skeleton collapses to one, so list lengths do not count; unclassed phrasing
 * elements (bold, line breaks) are text and do not count either.
 */

const PHRASING = new Set(["b", "i", "em", "strong", "br", "small", "sup", "sub", "wbr"]);
const IGNORED = new Set(["script", "style", "template", "link", "meta", "title"]);

export interface SkeletonOptions {
  /** Selectors removed before extraction: the sections documented as not served. */
  drop?: readonly string[];
}

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

/** The skeleton of `root`'s children, as text for a readable diff. */
export function skeleton(root: Element, options: SkeletonOptions = {}): string {
  const copy = root.cloneNode(true) as Element;
  for (const selector of options.drop ?? []) {
    for (const el of copy.querySelectorAll(selector)) el.remove();
  }
  return lines(copy, 0).join("\n");
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
