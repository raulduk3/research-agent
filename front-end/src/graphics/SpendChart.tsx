/** One UTC day's settled spend, in micro-dollars. */
export type SpendDay = { day: string; micros: number };

/** The mock's plot box (design-mock/costs.html): 0 at the bottom, the daily cap at the top. */
const LEFT = 26;
const RIGHT = 352;
const TOP = 12;
const BOTTOM = 148;
/** The mock draws nine day slots; fewer days keep that slot width rather than stretching. */
const SLOTS = 9;
const BAR = 22.5;

const dollars = (micros: number) => micros / 1_000_000;
const fixed = (n: number) => n.toFixed(1);
/** A gridline or cap figure without trailing zeros: 2, 6.4, 0.25. */
const figure = (micros: number) => String(Number(dollars(micros).toFixed(2)));

/**
 * The mock's settled-spend chart (`svg` in costs.html): quarter gridlines of the daily cap, the
 * alert and cap lines, then one bar per UTC day with its total above and its date below. Without a
 * cap the scale is the largest day. A bar is the day's undivided total, in ink: no route splits it
 * by source, so it takes none of the legend's colours; without days it keeps the axes and lines alone.
 */
export function SpendChart({
  days,
  capMicros,
  alert,
  label,
}: {
  days: readonly SpendDay[];
  capMicros: number | null;
  alert: number;
  label: string;
}) {
  const top = capMicros ?? Math.max(0, ...days.map((d) => d.micros));
  const y = (micros: number) => (top > 0 ? BOTTOM - ((BOTTOM - TOP) * Math.min(micros, top)) / top : BOTTOM);
  const slot = (RIGHT - LEFT) / Math.max(SLOTS, days.length);
  const grid = capMicros !== null && capMicros > 0 ? [1, 2, 3].map((q) => (capMicros * q) / 4) : [];

  return (
    <svg viewBox="0 0 360 170" role="img" aria-label={label}>
      {grid.map((micros) => (
        <g key={micros}>
          <line x1={LEFT} x2={RIGHT} y1={fixed(y(micros))} y2={fixed(y(micros))} stroke="var(--line)" />
          <text x={21} y={fixed(y(micros) + 3)} textAnchor="end" fill="var(--ink2)">
            {figure(micros)}
          </text>
        </g>
      ))}
      {capMicros !== null && capMicros > 0 && (
        <>
          <line
            x1={LEFT}
            x2={RIGHT}
            y1={fixed(y(capMicros * alert))}
            y2={fixed(y(capMicros * alert))}
            stroke="var(--orange)"
            strokeDasharray="2 3"
          />
          <text x={RIGHT} y={fixed(y(capMicros * alert) - 3)} textAnchor="end" fill="var(--orange)">
            alert at USD {dollars(capMicros * alert).toFixed(2)}
          </text>
          <line x1={LEFT} x2={RIGHT} y1={TOP} y2={TOP} stroke="var(--red)" strokeDasharray="3 2" />
          <text x={RIGHT} y={TOP - 3} textAnchor="end" fill="var(--red)">
            cap USD {figure(capMicros)} a day
          </text>
        </>
      )}
      <line x1={LEFT} x2={RIGHT} y1={BOTTOM} y2={BOTTOM} stroke="var(--line)" />
      <text x={21} y={9} textAnchor="end" fill="var(--ink2)">
        USD
      </text>
      {days.map((d, i) => {
        const mid = LEFT + slot * i + slot / 2;
        return (
          <g key={d.day}>
            <rect
              x={fixed(mid - BAR / 2)}
              y={fixed(y(d.micros))}
              width={BAR}
              height={fixed(BOTTOM - y(d.micros))}
              fill="var(--ink2)"
            >
              <title>
                {d.day} · everything · USD {dollars(d.micros).toFixed(2)} settled
              </title>
            </rect>
            <text x={fixed(mid)} y={fixed(y(d.micros) - 3)} textAnchor="middle" fill="var(--ink)">
              {dollars(d.micros).toFixed(2)}
            </text>
            <text x={fixed(mid)} y={162} textAnchor="middle" fill="var(--ink2)">
              {d.day.slice(5)}
            </text>
          </g>
        );
      })}
    </svg>
  );
}
