import type { Health } from "../api/schema.gen.ts";
import { useGet } from "../api/useGet.ts";
import { Show, when } from "../pages/common.tsx";

const state = (s: Health["state"]) => s.replace("_", " ");

/** The health line every owner mock page ends its content with (design-mock/*.html, `footer.diag`). */
export function Diag() {
  const health = useGet<Health>("/api/v1/health");
  return (
    <Show loaded={health}>
      {(h) => (
        <footer className="diag">
          <details>
            <summary>
              <span className="ok" style={h.state === "healthy" ? undefined : { background: "var(--red)" }} />
              {h.state === "healthy" ? "All systems normal" : `Platform ${state(h.state)}`}
              <span className="meta">· checked {when(h.checked_at)}</span>
            </summary>
            <div className="g">
              {h.checks.map((c) => (
                <div key={c.name}>
                  {c.name}:{" "}
                  <b>
                    {state(c.state)} · {c.detail}
                  </b>
                </div>
              ))}
            </div>
          </details>
        </footer>
      )}
    </Show>
  );
}
