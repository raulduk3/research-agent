import { useState, type FormEvent } from "react";
import { Link, useNavigate } from "react-router";
import { ApiError } from "../api/client.ts";
import { useApi } from "../api/context.tsx";
import { Lab } from "./Lab.tsx";

/** One field, no username; no menu before a session (design-mock/owner-login.html). */
export function Login() {
  const api = useApi();
  const navigate = useNavigate();
  const [credential, setCredential] = useState("");
  const [refusal, setRefusal] = useState<string | null>(null);

  async function submit(e: FormEvent) {
    e.preventDefault();
    setRefusal(null);
    try {
      await api.login(credential);
      void navigate("/", { replace: true });
    } catch (err) {
      setRefusal(err instanceof ApiError ? err.message || err.code : "sign-in failed");
    }
  }

  return (
    <>
      <nav>
        <Link className="brand" to="/login">
          <span className="mark">🏝️</span>Atoll
        </Link>
      </nav>
      <h1>Owner sign in</h1>
      <p className="lead">
        The owner's credential: it opens the population, the runs, the reports and the costs, and the
        actions that change an agent.
      </p>
      <form className="box" style={{ maxWidth: 420 }} onSubmit={(e) => void submit(e)}>
        <label htmlFor="credential">Credential</label>
        <input
          type="password"
          id="credential"
          name="credential"
          autoComplete="current-password"
          autoCapitalize="off"
          spellCheck={false}
          required
          value={credential}
          onChange={(e) => setCredential(e.target.value)}
        />
        <div className="err meta" role="alert" hidden={refusal === null} style={{ color: "var(--red)" }}>
          {refusal}
        </div>
        <p className="meta">
          A rater's credential does not open this page, and the owner's does not open a rater's digest:
          they are different principals.
        </p>
        <input type="submit" value="sign in" disabled={credential === ""} />
      </form>
      <div className="meta" style={{ marginTop: 22 }}>
        Sessions last 24 hours. Closing the tab keeps you signed in; <b>log out</b> in the menu ends it.
      </div>
      <Lab />
    </>
  );
}
