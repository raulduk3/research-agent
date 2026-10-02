import { useState } from "react";
import { refusal } from "../api/client.ts";
import { useApi } from "../api/context.tsx";
import type { IslandPaper } from "../api/types.ts";
import { MathText } from "./MathText.tsx";

/**
 * The island's papers with a control each: let it go, so the island's agents no longer queue or
 * find it, or hold it again. Runs and readings of a paper let go stay where they are. After each
 * change the island is read again, so the list shows what the server stored.
 */
export function LetGo({ papers, onChanged }: { papers: readonly IslandPaper[]; onChanged: () => void }) {
  const api = useApi();
  const [busy, setBusy] = useState<string | null>(null);
  const [failed, setFailed] = useState<string | null>(null);
  if (papers.length === 0) return null;

  async function flip(paper: IslandPaper) {
    setBusy(paper.id);
    setFailed(null);
    try {
      await api.post(`/api/v1/papers/${encodeURIComponent(paper.id)}/${paper.released ? "hold" : "release"}`, {});
      onChanged();
    } catch (err) {
      setFailed(refusal(err));
    } finally {
      setBusy(null);
    }
  }

  return (
    <ul className="letgo">
      {papers.map((p) => (
        <li key={p.id} data-released={p.released ? "" : undefined}>
          <button type="button" className="quiet ctl" disabled={busy !== null} onClick={() => void flip(p)}>
            {p.released ? "hold again" : "let go"}
          </button>{" "}
          <MathText text={p.title} />
          {p.released && <span className="meta"> · let go</span>}
        </li>
      ))}
      {failed !== null && (
        <li className="meta" role="alert" style={{ color: "var(--red)" }}>
          Nothing changed. {failed}
        </li>
      )}
    </ul>
  );
}
