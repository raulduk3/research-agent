import { useState } from "react";
import { refusal } from "../api/client.ts";
import { useApi } from "../api/context.tsx";
import type { IslandPaper } from "../api/types.ts";
import { MathText } from "./MathText.tsx";

export function LetGo({ papers, onChanged }: { papers: readonly IslandPaper[]; onChanged: () => void }) {
  const api = useApi();
  const [busy, setBusy] = useState<string | null>(null);
  const [failed, setFailed] = useState<string | null>(null);
  if (papers.length === 0) return null;

  async function flip(paper: IslandPaper) {
    setBusy(paper.id);
    setFailed(null);
    try {
      await api.post(`/api/v1/papers/${encodeURIComponent(paper.id)}/${paper.released || paper.kept !== true ? "select" : "deselect"}`, {});
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
            {p.released || p.kept !== true ? "select" : "deselect"}
          </button>{" "}
          <MathText text={p.title} />
          <span className="meta">
            {p.released ? " · deselected" : p.kept === true ? ` · selected by ${p.selected_by?.startsWith("island:") || p.selected_by === "operator" ? "a person" : "readers"}` : p.kept === false ? " · turned down by its readers" : " · still being read"}
          </span>
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
