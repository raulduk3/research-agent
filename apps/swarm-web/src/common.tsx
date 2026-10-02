import type { ReactNode } from "react";
import { refusal } from "./api/client.ts";
import type { Loaded } from "./api/useGet.ts";
import type { Paper, RunEvent } from "./api/types.ts";

/** A stored time (seconds since 1970) in the visitor's own clock. */
export function when(seconds: number): string {
  return new Date(seconds * 1000).toLocaleString(undefined, { dateStyle: "medium", timeStyle: "short" });
}

/** A link target taken from stored data, kept only when it is a plain web address. */
export function webUrl(url: string | null | undefined): string | null {
  return typeof url === "string" && /^https?:\/\//i.test(url) ? url : null;
}

/** The paper's PDF: the address the server names, or the one an arXiv abstract address implies. */
export function pdfUrl(paper: Paper): string | null {
  const named = webUrl(paper.pdf_url);
  if (named !== null) return named;
  const arxiv = /^https?:\/\/(?:www\.)?arxiv\.org\/abs\/(.+)$/i.exec(paper.url);
  return arxiv ? `https://arxiv.org/pdf/${arxiv[1]}` : null;
}

/** The tools the harness offers an agent; a step named after one of them is a tool call. */
export const TOOLS: ReadonlySet<string> = new Set(["paper_text", "related_papers", "capture_note", "feedback_context", "cost_state", "submit_reading"]);

export type Badge = { type: "model" | "tool" | "step"; label: string };

/** What a step was: a model call, a tool call by name, or another recorded step. */
export function badge(event: RunEvent): Badge {
  if (event.model) return { type: "model", label: event.model };
  if (event.kind === "model_call") return { type: "model", label: "model" };
  if (event.tool) return { type: "tool", label: event.tool };
  if (event.kind === "tool_call") return { type: "tool", label: "tool" };
  if (TOOLS.has(event.kind)) return { type: "tool", label: event.kind };
  return { type: "step", label: event.kind.replace(/_/g, " ") };
}

export function BadgeTag({ event }: { event: RunEvent }) {
  const b = badge(event);
  return (
    <span className={b.type === "model" ? "tag ctl" : b.type === "tool" ? "tag see" : "tag"}>
      {b.type === "step" ? b.label : `${b.type} · ${b.label}`}
    </span>
  );
}

/** A path or fragment piece decoded; one that is not valid escaping is taken as written. */
export function decoded(piece: string): string {
  try {
    return decodeURIComponent(piece);
  } catch {
    return piece;
  }
}

const LAST_KEY = { paper: "atoll.last.paper", run: "atoll.last.run" } as const;

/** The paper or run this browser opened last, so the menu can lead back to it. */
export function remember(kind: keyof typeof LAST_KEY, id: string): void {
  try {
    localStorage.setItem(LAST_KEY[kind], id);
  } catch {
    // Without storage the menu simply has no way back.
  }
}

export function recall(kind: keyof typeof LAST_KEY): string | null {
  try {
    return localStorage.getItem(LAST_KEY[kind]);
  } catch {
    return null;
  }
}

/** Leaving an island forgets the paper and run opened under it, or one stale remembered page. */
export function forget(kind?: keyof typeof LAST_KEY): void {
  try {
    if (kind) localStorage.removeItem(LAST_KEY[kind]);
    else for (const key of Object.values(LAST_KEY)) localStorage.removeItem(key);
  } catch {
    // Nothing was kept.
  }
}

/** A page section's body once its read has settled: the wait, the refusal with a retry, or the content. */
export function Settled<T>({
  read,
  what,
  children,
}: {
  read: Loaded<T> & { reload: () => void };
  what: string;
  children: (data: T) => ReactNode;
}) {
  if (read.state === "loading") return <p className="meta">Reading {what}…</p>;
  if (read.state === "failed") {
    return (
      <div className="box" role="alert">
        <b>{what} not available.</b> {refusal(read.error)}
        <div>
          <button type="button" className="quiet" onClick={read.reload}>
            try again
          </button>
        </div>
      </div>
    );
  }
  return <>{children(read.data)}</>;
}

/** The footer every page ends with. */
export function Lab() {
  return (
    <div className="lab">
      Output of an automated system, not a scientific claim authored by anyone.
      <br />
      <span className="rights">© 2026 Rick Álvarez · all rights reserved · licensing to be decided</span>
    </div>
  );
}
