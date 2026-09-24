import { useEffect, useState } from "react";

/**
 * One event of the owner's live run stream (docs/contracts/api-v1/owner-run-event.json, #327).
 * The generated schema does not carry it yet, so the fields this hook reads are typed here.
 */
export type LiveRunEvent = {
  id: string;
  kind: "call" | "terminal" | "ending" | "settlement";
  run_id: string;
  paper_id: string | null;
  island: string | null;
};

export const LIVE_RUNS = "/api/v1/owner/runs/live";

/**
 * Follows one run on the live stream while it is open: every event in ledger order, without
 * repeats across reconnects. The stream is closed once the run's ending arrives or the server
 * refuses the stream; with no run id nothing is opened.
 */
export function useRunStream(runId: string | null): { events: LiveRunEvent[]; open: boolean } {
  const [events, setEvents] = useState<LiveRunEvent[]>([]);
  const [open, setOpen] = useState(false);

  useEffect(() => {
    setEvents([]);
    if (!runId || typeof EventSource === "undefined") return;
    const source = new EventSource(`${LIVE_RUNS}?run_id=${encodeURIComponent(runId)}`);
    const seen = new Set<string>();
    const close = () => {
      source.close();
      setOpen(false);
    };
    const receive = (m: MessageEvent<string>) => {
      const e = JSON.parse(m.data) as LiveRunEvent;
      if (e.run_id !== runId || seen.has(e.id)) return;
      seen.add(e.id);
      setEvents((prev) => [...prev, e]);
      if (e.kind === "ending") close();
    };
    source.onopen = () => setOpen(true);
    source.onerror = () => {
      if (source.readyState === EventSource.CLOSED) close();
    };
    for (const kind of ["call", "terminal", "ending", "settlement"]) source.addEventListener(kind, receive);
    return close;
  }, [runId]);

  return { events, open };
}
