import { useState } from "react";
import { refusal } from "../api/client.ts";
import { useApi } from "../api/context.tsx";
import type { Likes } from "../api/types.ts";

/**
 * The one signal a person gives: a like on a paper, a run, a reading, a claim, an idea or an
 * agent. One per island per thing; a second press takes it back. The count is every island's.
 * Likes become the agent's points, which the breeder sees. Without a session it only counts.
 */
export function Like({ kind, id, likes }: { kind: string; id: string; likes?: Likes | null | undefined }) {
  const api = useApi();
  const island = api.session?.island ?? null;
  const key = `${kind}:${id}`;
  const stored = likes?.[key];
  const [state, setState] = useState<{ count: number; liked: boolean; refused: string | null } | null>(null);
  const count = state?.count ?? stored?.count ?? 0;
  const liked = state?.liked ?? (island !== null && (stored?.islands ?? []).includes(island));

  async function press() {
    if (island === null) return;
    try {
      const answer = await api.post<{ like: { liked: boolean; count: number } }>("/api/v1/likes", { target_kind: kind, target_id: id });
      setState({ count: answer.like.count, liked: answer.like.liked, refused: null });
    } catch (err) {
      setState({ count, liked, refused: refusal(err) });
    }
  }

  return (
    <span className="like">
      <button
        type="button"
        className={liked ? "like-btn on" : "like-btn"}
        disabled={island === null}
        onClick={() => void press()}
        aria-label={liked ? `take back the like on this ${kind}` : `like this ${kind}`}
        aria-pressed={liked}
      >
        ▲ {count}
      </button>
      {state?.refused && (
        <span className="meta" role="alert">
          {state.refused}
        </span>
      )}
    </span>
  );
}
