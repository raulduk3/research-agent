import { useState } from "react";
import { refusal } from "../api/client.ts";
import { useApi } from "../api/context.tsx";

type Sent = { state: "idle" } | { state: "sending" } | { state: "done"; signal: string } | { state: "failed"; why: string };

/**
 * The one feedback control, used wherever a paper, run, island or chat answer can be judged. The
 * signal goes to the server under the session's island; if the server does not take it, the page
 * says so and shows no vote.
 */
export function Feedback({ targetType, targetId }: { targetType: string; targetId: string }) {
  const api = useApi();
  const [sent, setSent] = useState<Sent>({ state: "idle" });
  const [note, setNote] = useState("");
  const island = api.session?.island ?? null;
  if (island === null) return null;

  async function send(signal: string) {
    if (island === null) return;
    setSent({ state: "sending" });
    try {
      await api.post("/api/v1/feedback", { island_id: island, target_type: targetType, target_id: targetId, signal, note });
      setSent({ state: "done", signal });
    } catch (err) {
      setSent({ state: "failed", why: refusal(err) });
    }
  }

  if (sent.state === "done") return <div className="meta fb">Recorded: {sent.signal.replace("_", " ")}. The island's next evolution reads it.</div>;
  return (
    <div className="fb">
      <span className="meta">Was this useful?</span>
      <button type="button" className="quiet ctl" disabled={sent.state === "sending"} onClick={() => void send("useful")}>
        useful
      </button>
      <button type="button" className="quiet ctl" disabled={sent.state === "sending"} onClick={() => void send("not_useful")}>
        not useful
      </button>
      <input type="text" aria-label="note" placeholder="a note, if you like" value={note} onChange={(e) => setNote(e.target.value)} />
      {sent.state === "failed" && (
        <span className="meta" role="alert" style={{ color: "var(--red)" }}>
          Feedback unavailable, nothing was recorded. {sent.why}
        </span>
      )}
    </div>
  );
}
