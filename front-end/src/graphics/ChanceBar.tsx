/** The mock's colour for a chance: one orange that deepens as the chance rises. */
export function chanceColour(p: number): string {
  return `hsl(24, ${Math.round(40 + 55 * p)}%, ${Math.round(88 - 44 * p)}%)`;
}

/**
 * A chance as the mock's bar (`span.pb > i > b`) beside its number. With no chance the frame
 * stays and the bar is absent, so the column keeps its shape without inventing a value.
 */
export function ChanceBar({ p, none = "none" }: { p: number | null | undefined; none?: string }) {
  const has = p !== null && p !== undefined;
  return (
    <span className="pb">
      <i>{has && <b style={{ width: `${Math.round(p * 100)}%`, background: chanceColour(p) }} />}</i>
      <span className="num">{has ? p.toFixed(2) : none}</span>
    </span>
  );
}
