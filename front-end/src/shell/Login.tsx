import { useState, type FormEvent } from "react";
import { useNavigate } from "react-router";
import { ApiError } from "../api/client.ts";
import { useApi } from "../api/context.tsx";

/** One field, no username (design-mock/owner-login.html). */
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
    <main>
      <h1>Owner sign-in</h1>
      <form onSubmit={(e) => void submit(e)}>
        <label>
          Credential{" "}
          <input
            type="password"
            autoComplete="current-password"
            value={credential}
            onChange={(e) => setCredential(e.target.value)}
          />
        </label>
        <button type="submit" disabled={credential === ""}>
          Sign in
        </button>
      </form>
      {refusal && <p role="alert">{refusal}</p>}
    </main>
  );
}
