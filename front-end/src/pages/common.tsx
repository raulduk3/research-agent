import type { ReactNode } from "react";
import { ApiError } from "../api/client.ts";
import type { Loaded } from "../api/useGet.ts";
import { Card } from "../graphics/Cards.tsx";

/** Renders a read's body once it is ready; otherwise the wait or the refusal. */
export function Show<T>({ loaded, children }: { loaded: Loaded<T>; children: (data: T) => ReactNode }) {
  if (loaded.state === "loading") return <div className="meta">loading…</div>;
  if (loaded.state === "failed") return <Refusal error={loaded.error} />;
  return <>{children(loaded.data)}</>;
}

/** A read's body once it is ready; null while it waits or when it is refused. */
export function ready<T>(loaded: Loaded<T>): T | null {
  return loaded.state === "ready" ? loaded.data : null;
}

/** A refusal as one line of text: what went wrong, then its code and field. */
export function refusalText(error: unknown): string {
  if (error instanceof ApiError) {
    const what = error.code === "not_found" ? "Nothing stored for this id." : error.message;
    return `${what} · ${error.code}${error.field ? ` · ${error.field}` : ""}`;
  }
  return error instanceof Error ? error.message : "request failed";
}

/**
 * The page's lead once its reads are in. While one waits the lead says so, and when one is
 * refused the lead carries the refusal, so the sections below keep their place either way. `tail`
 * follows the lead in every state.
 */
export function Lead({
  reads,
  children,
  tail,
}: {
  reads: readonly Loaded<unknown>[];
  children: () => ReactNode;
  tail?: ReactNode;
}) {
  const failed = reads.find((r) => r.state === "failed");
  if (failed?.state === "failed") {
    return (
      <p className="lead" role="alert">
        {refusalText(failed.error)}
        {tail}
      </p>
    );
  }
  return (
    <p className="lead">
      {reads.some((r) => r.state === "loading") ? "loading…" : children()}
      {tail}
    </p>
  );
}

export function Refusal({ error }: { error: unknown }) {
  if (error instanceof ApiError) {
    return (
      <p role="alert">
        {error.code === "not_found" ? "Nothing stored for this id." : error.message}{" "}
        <span className="meta">
          · {error.code}
          {error.field ? ` · ${error.field}` : ""}
        </span>
      </p>
    );
  }
  return <p role="alert">{error instanceof Error ? error.message : "request failed"}</p>;
}

/** What a mock section says when no /api/v1 route fills it (docs/implementation/front-end.md). */
export const UNSERVED = "not served yet";

/**
 * The mock's replay panel (`div.rplay`). Replay has no /api/v1 route until #208 is decided, so
 * the controls are there but disabled; the stage holds what a page can draw from its reads.
 */
export function Replay({ children, cue = true }: { children?: ReactNode; cue?: boolean }) {
  return (
    <div className="rplay">
      <div className="bar">
        <button className="play" type="button" aria-label="play" disabled>
          play
        </button>
        <input className="cur" type="range" min="0" max="1" defaultValue="0" step="1" aria-label="timeline" disabled />
        <span className="readout" />
        <select className="speed" aria-label="speed" defaultValue="600" disabled>
          <option value="60">×60</option>
          <option value="600">×600</option>
          <option value="3600">×3600</option>
        </select>
      </div>
      {cue && <div className="cue">replay {UNSERVED}</div>}
      <div className="stage">{children}</div>
    </div>
  );
}

/** A mock card (`div.card`) with nothing served for it. */
export function EmptyCard({ title, children = UNSERVED }: { title: string; children?: ReactNode }) {
  return <Card title={title} value="none" meta={children} />;
}

/** A hash or id shortened for reading; the whole value stays in the title. */
export function Id({ value }: { value: string | null | undefined }) {
  if (!value) return <span className="meta">none</span>;
  return (
    <span className="id" title={value}>
      {value.length > 12 ? value.slice(0, 12) : value}
    </span>
  );
}

/** The mock's fold for identifiers: kept, but out of the way. */
export function Ids({ rows }: { rows: readonly (readonly [string, string | null | undefined])[] }) {
  return (
    <details className="ids">
      <summary>Identifiers: hashes and record ids kept out of the way</summary>
      <div className="tw">
        <table className="kv">
          <tbody>
            <tr>
              <th>what</th>
              <th>id</th>
            </tr>
            {rows.map(([what, id]) => (
              <tr key={what}>
                <td>{what}</td>
                <td>{id ? <span className="id">{id}</span> : <span className="na">none</span>}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </details>
  );
}

/** `2026-09-24T01:03:00.000000Z` as `2026-09-24 01:03 UTC`. */
export function when(instant: string | null | undefined): string {
  if (!instant) return "none";
  return `${instant.slice(0, 10)} ${instant.slice(11, 16)} UTC`;
}

export function usd(micros: number): string {
  return `USD ${(micros / 1_000_000).toFixed(2)}`;
}

/** The next page of a list whose `next_cursor` is not null; the cursor goes back verbatim. */
export function More({ cursor, onMore }: { cursor: string | null; onMore: (cursor: string) => void }) {
  if (cursor === null) return null;
  return (
    <button type="button" className="more" onClick={() => onMore(cursor)}>
      next page
    </button>
  );
}
