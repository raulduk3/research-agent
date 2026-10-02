import type { Reading } from "../api/types.ts";
import { MathText } from "./MathText.tsx";

function Items({ label, items }: { label: string; items: readonly string[] }) {
  if (items.length === 0) return null;
  return (
    <>
      <div className="meta">{label}</div>
      <ul className="facts">
        {items.map((item, i) => (
          <li key={i}><MathText text={item} /></li>
        ))}
      </ul>
    </>
  );
}

/**
 * A submitted reading: the summary, each claim with the words it quotes, the objections, the
 * related papers and the idea seeds. A quote the stored text does not contain is marked as such.
 */
export function ReadingView({ reading }: { reading: Reading }) {
  return (
    <div className="reading">
      <div className="said"><MathText text={reading.summary} /></div>
      {reading.claims.length > 0 && (
        <>
          <div className="meta">claims</div>
          <ul className="facts">
            {reading.claims.map((claim, i) => (
              <li key={i}>
                <MathText text={claim.text} />
                {(claim.evidence ?? []).map((e, k) => (
                  <div key={k} className="meta">
                    <mark><MathText text={e.quote} /></mark> {e.verified === false ? "· not found in the stored text" : e.verified === true ? "· quoted from the paper" : ""}
                  </div>
                ))}
                {(claim.evidence ?? []).length === 0 && <div className="meta">no quote given</div>}
              </li>
            ))}
          </ul>
        </>
      )}
      <Items label="objections" items={reading.objections} />
      <Items label="related papers" items={reading.related_papers} />
      <Items label="idea seeds" items={reading.idea_seeds} />
    </div>
  );
}
