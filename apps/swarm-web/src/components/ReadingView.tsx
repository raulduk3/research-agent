import type { Reading } from "../api/types.ts";
import { MathText } from "./MathText.tsx";

function Items({ label, items }: { label: string; items: readonly string[] }) {
  if (items.length === 0) return null;
  return (
    <section className="reading-section">
      <h3>{label}</h3>
      <ul className="reading-list">
        {items.map((item, i) => (
          <li key={i}><MathText text={item} /></li>
        ))}
      </ul>
    </section>
  );
}

/**
 * A submitted reading: the summary, each claim with the words it quotes, the objections, the
 * related papers and the idea seeds. A quote the stored text does not contain is marked as such.
 */
export function ReadingView({ reading }: { reading: Reading }) {
  return (
    <div className="reading">
      <section className="reading-section summary">
        <h3>summary</h3>
        <p><MathText text={reading.summary} /></p>
      </section>
      {reading.claims.length > 0 && (
        <section className="reading-section">
          <h3>claims</h3>
          <ol className="reading-claims">
            {reading.claims.map((claim, i) => (
              <li key={i}>
                <p className="claim-text"><MathText text={claim.text} /></p>
                {(claim.evidence ?? []).length > 0 ? (
                  <div className="quotes">
                    {(claim.evidence ?? []).map((e, k) => (
                      <blockquote key={k} className={e.verified === false ? "missing" : ""}>
                        <MathText text={e.quote} />
                        <footer>{e.verified === false ? "not found in stored text" : e.verified === true ? "quoted from the paper" : "quote"}</footer>
                      </blockquote>
                    ))}
                  </div>
                ) : (
                  <div className="meta">no quote given</div>
                )}
              </li>
            ))}
          </ol>
        </section>
      )}
      <Items label="objections" items={reading.objections} />
      <Items label="related papers" items={reading.related_papers} />
      <Items label="idea seeds" items={reading.idea_seeds} />
    </div>
  );
}
