import { useState, type FormEvent } from "react";
import { Link } from "react-router";
import { refusal } from "../api/client.ts";
import { useApi } from "../api/context.tsx";
import type { ChatAnswer, ChatLink } from "../api/types.ts";
import { usd } from "../money.ts";
import { Feedback } from "./Feedback.tsx";

type Turn = { key: number; who: "you"; text: string } | { key: number; who: "swarm"; answer: ChatAnswer } | { key: number; who: "refused"; why: string };

function linkPath(link: ChatLink): string {
  const id = encodeURIComponent(link.id);
  return link.kind === "run" ? `/runs/${id}` : link.kind === "island" ? `/islands/${id}` : `/papers/${id}`;
}

/** What an answer cost: its own amount, or that it came from stored data alone. */
export function answerCost(answer: ChatAnswer): string {
  return typeof answer.cost_micros === "number" && answer.cost_micros > 0 ? `${usd(answer.cost_micros)} this answer` : "stored-data only";
}

/**
 * Casual chat with the island's swarm. The conversation lives in this page only and is gone on
 * reload; every answer links into the tree, where the record is.
 */
export function ChatPanel() {
  const api = useApi();
  const [turns, setTurns] = useState<Turn[]>([]);
  const [message, setMessage] = useState("");
  const [sending, setSending] = useState(false);
  const island = api.session?.island ?? null;

  async function ask(e: FormEvent) {
    e.preventDefault();
    const text = message.trim();
    if (text === "" || island === null) return;
    const key = Date.now();
    setTurns((t) => [...t, { key, who: "you", text }]);
    setMessage("");
    setSending(true);
    try {
      const answer = await api.post<ChatAnswer>("/api/v1/chat", { island_id: island, message: text });
      setTurns((t) => [...t, { key: key + 1, who: "swarm", answer }]);
    } catch (err) {
      setTurns((t) => [...t, { key: key + 1, who: "refused", why: refusal(err) }]);
    } finally {
      setSending(false);
    }
  }

  return (
    <>
      <div className="thread" aria-live="polite">
        {turns.length === 0 && <p className="meta">Ask what changed, what a paper claims, or what a run cost. Nothing here is kept after you leave.</p>}
        {turns.map((turn) =>
          turn.who === "you" ? (
            <div className="turn" key={turn.key}>
              <div className="who">you</div>
              <div className="say">{turn.text}</div>
              <div />
            </div>
          ) : turn.who === "refused" ? (
            <div className="turn final" key={turn.key} role="alert">
              <div className="say">The swarm did not answer. {turn.why} Ask again when you like.</div>
            </div>
          ) : (
            <div className="turn final" key={turn.key}>
              <div className="say">
                <div className="said">{turn.answer.answer}</div>
                {(turn.answer.links ?? []).length > 0 && (
                  <div className="explore">
                    {(turn.answer.links ?? []).map((l) => (
                      <Link key={`${l.kind ?? "paper"}-${l.id}`} to={linkPath(l)}>
                        {l.title || l.id}
                      </Link>
                    ))}
                  </div>
                )}
                <div className="meta">{answerCost(turn.answer)}</div>
                {turn.answer.answer_id ? <Feedback targetType="chat" targetId={turn.answer.answer_id} /> : null}
              </div>
            </div>
          ),
        )}
      </div>
      <form className="box" onSubmit={(e) => void ask(e)}>
        <label htmlFor="q">Message</label>
        <textarea id="q" placeholder="ask the swarm what matters" value={message} onChange={(e) => setMessage(e.target.value)} />
        <button type="submit" disabled={sending || message.trim() === ""}>
          {sending ? "asking…" : "send"}
        </button>
      </form>
    </>
  );
}
