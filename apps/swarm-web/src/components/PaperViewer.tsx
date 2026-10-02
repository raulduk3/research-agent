import { useEffect, useRef, useState, type ReactNode } from "react";
import type { Locator, Paper, PaperSection } from "../api/types.ts";
import { pdfUrl, webUrl } from "../common.tsx";

/** `text` cut around the first place `quote` occurs, allowing any run of white space between its words. */
export function splitQuote(text: string, quote: string | null | undefined): [before: string, hit: string, after: string] | null {
  const words = (quote ?? "").trim().split(/\s+/).filter((w) => w !== "");
  if (words.length === 0) return null;
  const pattern = words.map((w) => w.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")).join("\\s+");
  const found = new RegExp(pattern).exec(text);
  if (!found) return null;
  return [text.slice(0, found.index), found[0], text.slice(found.index + found[0].length)];
}

/** The section a locator points at: by its name, else by its page, else the one holding the quote. */
export function findSection(sections: readonly PaperSection[], locator: Locator): number {
  const name = locator.section?.trim().toLowerCase();
  if (name) {
    const byName = sections.findIndex((s) => s.id?.toLowerCase() === name || s.title.trim().toLowerCase() === name);
    if (byName !== -1) return byName;
  }
  if (locator.quote) {
    const byQuote = sections.findIndex((s) => splitQuote(s.text, locator.quote) !== null);
    if (byQuote !== -1) return byQuote;
  }
  if (typeof locator.page === "number") return sections.findIndex((s) => s.page === locator.page);
  return -1;
}

function Quoted({ text, quote }: { text: string; quote: string | null | undefined }): ReactNode {
  const cut = splitQuote(text, quote);
  if (cut === null) return text;
  return (
    <>
      {cut[0]}
      <mark>{cut[1]}</mark>
      {cut[2]}
    </>
  );
}

type Tab = "pdf" | "text" | "about";

/**
 * The paper beside a run's replay. It follows the step being replayed: a step that read a place in
 * the paper moves the viewer there, to the section and the quoted passage when the stored text has
 * them, otherwise to the PDF's page. A paper with no stored text and no PDF shows what is stored:
 * its record and abstract. A visitor can switch views; the next located step takes over again.
 */
export function PaperViewer({ paper, locator, step }: { paper: Paper; locator: Locator | null; step?: number }) {
  const pdf = pdfUrl(paper);
  const sections = paper.sections ?? [];
  const [tab, setTab] = useState<Tab>("about");
  const [page, setPage] = useState(1);
  const target = useRef<HTMLElement | null>(null);

  const at = locator === null ? -1 : findSection(sections, locator);
  const locPage = locator?.page ?? null;
  const quote = locator?.quote ?? null;
  const inAbstract = splitQuote(paper.summary, quote) !== null;
  const located = locator !== null;

  useEffect(() => {
    if (!located) return;
    if (typeof locPage === "number") setPage(locPage);
    if (at !== -1) setTab("text");
    else if (typeof locPage === "number" && pdf !== null) setTab("pdf");
    else if (inAbstract) setTab("about");
  }, [located, at, locPage, quote, inAbstract, pdf, step]);

  useEffect(() => {
    if (tab === "text") target.current?.scrollIntoView?.({ block: "nearest" });
  }, [tab, at, quote]);

  const tabs: [Tab, string][] = [];
  if (pdf !== null) tabs.push(["pdf", "PDF"]);
  if (sections.length > 0) tabs.push(["text", "text"]);
  tabs.push(["about", "abstract"]);
  const source = webUrl(paper.url);

  return (
    <div className="rp-pdf">
      <div className="rp-cap">
        <b>{paper.title}</b>
        {located && typeof locPage === "number" && <span className="pgpill">page {locPage}</span>}
        {located && locator.section && <span className="why">{locator.section}</span>}
        <span className="open tabs">
          {tabs.map(([key, label]) => (
            <button key={key} type="button" aria-pressed={tab === key} onClick={() => setTab(key)}>
              {label}
            </button>
          ))}
        </span>
      </div>
      {quote !== null && (tab === "pdf" || (tab === "text" && at === -1) || (tab === "about" && !inAbstract)) && (
        <div className="quote">
          the step quoted: <mark>{quote}</mark>
        </div>
      )}
      {tab === "pdf" && pdf !== null && (
        <>
          <iframe key={page} title="the paper's PDF" src={`${pdf}#page=${page}`} />
          <div className="meta">
            PDF at page {page} ·{" "}
            <a href={`${pdf}#page=${page}`} target="_blank" rel="noreferrer">
              open in a new tab
            </a>
          </div>
        </>
      )}
      {tab === "text" && (
        <div className="rp-parts" data-testid="paper-text">
          {sections.map((s, i) => (
            <section
              key={i}
              ref={i === at ? target : undefined}
              className={i === at ? "sect on" : "sect"}
              aria-current={i === at ? "location" : undefined}
            >
              <h3>
                {s.title}
                {typeof s.page === "number" && <span className="meta"> · page {s.page}</span>}
              </h3>
              <p>{i === at ? <Quoted text={s.text} quote={quote} /> : s.text}</p>
            </section>
          ))}
        </div>
      )}
      {tab === "about" && (
        <div className="rp-parts" data-testid="paper-about">
          <div className="meta">
            {paper.primary_category} · stored text: {paper.text_status}
            {source !== null && (
              <>
                {" · "}
                <a href={source} target="_blank" rel="noreferrer">
                  source
                </a>
              </>
            )}
          </div>
          <p>{paper.summary === "" ? <span className="na">No abstract is stored for this paper.</span> : <Quoted text={paper.summary} quote={quote} />}</p>
        </div>
      )}
    </div>
  );
}
