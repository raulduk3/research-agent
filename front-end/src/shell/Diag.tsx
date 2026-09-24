import { ApiError } from "../api/client.ts";
import type { Health } from "../api/schema.gen.ts";
import { useGet } from "../api/useGet.ts";
import { when } from "../pages/common.tsx";

const state = (s: Health["state"]) => s.replace("_", " ");

/**
 * The health line every owner mock page ends its content with (design-mock/*.html, `footer.diag`).
 * It renders whatever the health read returns: while it waits or when it is refused, the same
 * footer carries empty values and the refusal, so the page keeps its shape.
 */
export function Diag() {
  const health = useGet<Health>("/api/v1/health");
  const h = health.state === "ready" ? health.data : null;
  const refusal =
    health.state === "failed"
      ? health.error instanceof ApiError
        ? health.error.code
        : health.error instanceof Error
          ? health.error.message
          : "request failed"
      : null;
  return (
    <footer className="diag">
      <details>
        <summary>
          <span className="ok" style={h?.state === "healthy" ? undefined : { background: "var(--red)" }} />
          {h === null ? "Platform health unknown" : h.state === "healthy" ? "All systems normal" : `Platform ${state(h.state)}`}
          <span className="meta">· checked {h === null ? "none" : when(h.checked_at)}</span>
        </summary>
        <div className="g">
          {h === null ? (
            <div>
              Health: <b>{refusal ?? "loading…"}</b>
            </div>
          ) : (
            h.checks.map((c) => (
              <div key={c.name}>
                {c.name}:{" "}
                <b>
                  {state(c.state)} · {c.detail}
                </b>
              </div>
            ))
          )}
        </div>
      </details>
    </footer>
  );
}
