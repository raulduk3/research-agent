import { useEffect, useState, type FormEvent } from "react";
import { Link } from "react-router";
import { refusal } from "../api/client.ts";
import { useApi } from "../api/context.tsx";
import type { ChatAnswer, ChatLink } from "../api/types.ts";
import { usd } from "../money.ts";
import { MathText } from "./MathText.tsx";

type Turn = { key: number; who: "you"; text: string } | { key: number; who: "swarm"; answer: ChatAnswer } | { key: number; who: "refused"; why: string };

function linkPath(link: ChatLink): string {
  const id = encodeURIComponent(link.id);
  return link.kind === "run" ? `/runs/${id}` : link.kind === "island" ? `/islands/${id}` : `/papers/${id}`;
}

/**
 * What an answer cost. The server sends the cost of that one answer: zero when it came from
 * stored data alone, an amount when a model wrote it. Without the figure the page says so.
 */
export function answerCost(answer: ChatAnswer): string {
  if (typeof answer.cost_micros !== "number") return "answer cost not reported";
  return answer.cost_micros > 0 ? `${usd(answer.cost_micros)} this answer` : "from stored records";
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

  useEffect(() => {
    if (!sending) return;
    const beforeUnload = (event: BeforeUnloadEvent) => {
      event.preventDefault();
      event.returnValue = "";
    };
    const blockLink = (event: MouseEvent) => {
      const target = event.target instanceof Element ? event.target.closest("a") : null;
      if (target === null) return;
      if (!window.confirm("The swarm is still answering. Leave this chat anyway?")) {
        event.preventDefault();
        event.stopPropagation();
      }
    };
    window.addEventListener("beforeunload", beforeUnload);
    document.addEventListener("click", blockLink, true);
    return () => {
      window.removeEventListener("beforeunload", beforeUnload);
      document.removeEventListener("click", blockLink, true);
    };
  }, [sending]);

  async function ask(e: FormEvent) {
    e.preventDefault();
    const text = message.trim();
    if (text === "" || island === null) return;
    const key = Date.now();
    setTurns((t) => [...t, { key, who: "you", text }]);
    setMessage("");
    setSending(true);
    try {
      const answer = await api.post<ChatAnswer>("/api/v1/chat", { message: text });
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
        {island === null ? (
          <p className="meta" role="note">
            Chat answers for one island. Sign in with an island&apos;s code to ask it.
          </p>
        ) : (
          turns.length === 0 && <p className="meta">Ask what changed, what a paper claims, or what a run cost. Nothing here is kept after you leave.</p>
        )}
        {turns.map((turn) =>
          turn.who === "you" ? (
            <div className="turn" key={turn.key}>
              <div className="who">you</div>
              <div className="say"><MathText text={turn.text} /></div>
              <div />
            </div>
          ) : turn.who === "refused" ? (
            <div className="turn final" key={turn.key} role="alert">
              <div className="say">The swarm did not answer. <MathText text={turn.why} /> Ask again when you like.</div>
            </div>
          ) : (
            <div className="turn final" key={turn.key}>
              <div className="say">
                <div className="said"><MathText text={turn.answer.answer} /></div>
                {turn.answer.supported === false && <p className="meta">This answer is not verified by stored records.</p>}
                {(turn.answer.links ?? []).length > 0 && (
                  <div className="explore">
                    {(turn.answer.links ?? []).map((l) => (
                      <Link key={`${l.kind ?? "paper"}-${l.id}`} to={linkPath(l)}>
                        {l.title || l.id}
                        {l.snippet ? <span className="meta"> · <MathText text={l.snippet} /></span> : null}
                      </Link>
                    ))}
                  </div>
                )}
                <div className="meta">{answerCost(turn.answer)}</div>
              </div>
            </div>
          ),
        )}
        {sending ? (
          <div className="turn final wait" role="status">
            <div className="say">
              <div className="dots" aria-hidden="true"><i></i><i></i><i></i></div>
              The swarm is reading its papers, runs and patterns… stay on this page for the answer.
            </div>
          </div>
        ) : null}
      </div>
      <form className="box" onSubmit={(e) => void ask(e)}>
        <label htmlFor="q">Message</label>
        <textarea id="q" placeholder="ask about the swarm, papers, readings, or patterns" value={message} disabled={island === null || sending} onChange={(e) => setMessage(e.target.value)} />
        <button type="submit" disabled={sending || island === null || message.trim() === ""}>
          {sending ? "asking…" : "send"}
        </button>
      </form>
    </>
  );
}
