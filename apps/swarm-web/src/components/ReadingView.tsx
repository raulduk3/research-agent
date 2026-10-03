import type { Likes, Reading } from "../api/types.ts";
import { Like } from "./Like.tsx";
import { MathText } from "./MathText.tsx";

function Items({ label, items, kind, readingId, likes }: { label: string; items: readonly string[]; kind?: string; readingId?: string; likes?: Likes | null | undefined }) {
  if (items.length === 0) return null;
  return (
    <section className="reading-section">
      <h3>{label}</h3>
      <ul className="reading-list">
        {items.map((item, i) => (
          <li key={i}>
            <MathText text={item} />
            {kind && readingId ? <Like kind={kind} id={`${readingId}#${i}`} likes={likes} /> : null}
          </li>
        ))}
      </ul>
    </section>
  );
}

/**
 * A submitted reading: the summary, each claim with the words it quotes, the objections, the
 * related papers and the idea seeds. A quote the stored text does not contain is marked as such.
 */
export function ReadingView({ reading, likes }: { reading: Reading; likes?: Likes | null | undefined }) {
  return (
    <div className="reading">
      <div className="meta">
        {typeof reading.keep === "boolean" ? (reading.keep ? "voted to keep the paper" : "voted to let the paper go") : "this reading"}{" "}
        <Like kind="reading" id={reading.id} likes={likes} />
      </div>
      {reading.thesis_quote && (
        <section className="reading-section thesis">
          <h3>thesis sentence</h3>
          <blockquote><MathText text={reading.thesis_quote} /></blockquote>
        </section>
      )}
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
                <p className="claim-text">
                  <MathText text={claim.text} /> <Like kind="claim" id={`${reading.id}#${i}`} likes={likes} />
                </p>
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
      <Items label="idea seeds" items={reading.idea_seeds} kind="idea" readingId={reading.id} likes={likes} />
    </div>
  );
}
