import { useState, type FormEvent } from "react";
import { Link, useNavigate, useSearchParams } from "react-router";
import { refusal } from "../api/client.ts";
import { useApi } from "../api/context.tsx";
import type { Storm } from "../api/types.ts";
import { useGet } from "../api/useGet.ts";
import { Lab, Settled, decoded } from "../common.tsx";

/** A page of this app to return to after sign-in; anything else is ignored. */
function localPath(next: string | null): string | null {
  if (next === null || !next.startsWith("/")) return null;
  try {
    const url = new URL(next, window.location.origin);
    return url.origin === window.location.origin ? url.pathname + url.search + url.hash : null;
  } catch {
    return null;
  }
}

/** Island sign-in: pick the island, give its access code. No menu before a session. */
export function Login() {
  const api = useApi();
  const navigate = useNavigate();
  const [params] = useSearchParams();
  const storm = useGet<Storm>("/api/v1/public/storm");
  const [picked, setPicked] = useState<string | null>(params.get("island"));
  const [code, setCode] = useState("");
  const [refused, setRefused] = useState<string | null>(null);
  const [sending, setSending] = useState(false);

  const islands = storm.state === "ready" ? storm.data.islands : [];
  // An island named in the address is used only if it exists; otherwise the first one is offered.
  const island = islands.find((i) => i.id === picked)?.id ?? islands[0]?.id ?? null;

  async function submit(e: FormEvent) {
    e.preventDefault();
    if (island === null) return;
    setRefused(null);
    setSending(true);
    try {
      const session = await api.login(island, code);
      const next = localPath(params.get("next"));
      // A page of another island is not this session's to open; the island's own page is.
      const asked = next === null ? null : (/^\/islands\/([^/?#]+)/i.exec(next)?.[1] ?? null);
      const other = asked !== null && decoded(asked) !== session.island;
      void navigate(next !== null && !other ? next : `/islands/${encodeURIComponent(session.island)}`, { replace: true });
    } catch (err) {
      setRefused(refusal(err));
    } finally {
      setSending(false);
    }
  }

  return (
    <>
      <nav>
        <Link className="brand" to="/">
          <span className="mark">🏝️</span>Atoll
        </Link>
      </nav>
      <h1>Enter an island</h1>
      <p className="lead">Pick an island and give its access code. The session is casual; what the swarm read and what it cost is the record.</p>
      <Settled read={storm} what="The islands">
        {(data) =>
          data.islands.length === 0 ? (
            <p className="meta">No island exists yet.</p>
          ) : (
            <form className="box" style={{ maxWidth: 420 }} onSubmit={(e) => void submit(e)}>
              <label htmlFor="island">Island</label>
              <select id="island" value={island ?? ""} onChange={(e) => setPicked(e.target.value)}>
                {data.islands.map((i) => (
                  <option key={i.id} value={i.id}>
                    {i.name} · {i.focus}
                  </option>
                ))}
              </select>
              <label htmlFor="code">Access code</label>
              <input
                type="password"
                id="code"
                name="code"
                autoComplete="current-password"
                autoCapitalize="off"
                spellCheck={false}
                value={code}
                onChange={(e) => setCode(e.target.value)}
              />
              <div className="meta" role="alert" hidden={refused === null} style={{ color: "var(--red)" }}>
                {refused}
              </div>
              <input type="submit" value={sending ? "entering…" : "enter"} disabled={sending || island === null} />
            </form>
          )
        }
      </Settled>
      <Lab />
    </>
  );
}
