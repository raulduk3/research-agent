import { Dot } from "./Dot.tsx";

/** One recorded run event on the lane: when it was recorded, its kind and its hover text. */
export type LaneEvent = { at: string; kind: string; title: string };

/** One reader's chance on the axis, 0 to 1. */
export type LaneMark = { p: number; title: string };

const SIX_HOURS = 6 * 3600 * 1000;

/**
 * The mock's reader lane (design-mock/paper-P1.html, the question replay): the time lane
 * (`div.tl`) with six-hour ticks and one `div.ev` per recorded event, then the chance axis
 * (`div.axis1`) with one `.dot` per reader's forecast. With nothing served it keeps both frames
 * and the axis labels, and draws no marks.
 */
export function ReaderLane({ events, marks, label }: { events: readonly LaneEvent[]; marks: readonly LaneMark[]; label: string }) {
  const times = events.map((e) => Date.parse(e.at));
  const t0 = Math.min(...times);
  const span = Math.max(1, Math.max(...times) - t0);
  const left = (t: number) => `${((100 * (t - t0)) / span).toFixed(2)}%`;
  const ticks: number[] = [];
  if (events.length > 0) for (let s = Math.ceil(t0 / SIX_HOURS) * SIX_HOURS; s <= t0 + span; s += SIX_HOURS) ticks.push(s);

  return (
    <div role="img" aria-label={label}>
      <div className="tl">
        {ticks.map((s) => (
          <div className="tk" key={s} style={{ left: left(s) }}>
            <span>{new Date(s).toISOString().slice(11, 16)}</span>
          </div>
        ))}
        {events.map((e, i) => (
          <div className={`ev c-${e.kind}`} key={i} style={{ left: left(Date.parse(e.at)) }} title={e.title} />
        ))}
      </div>
      <div className="axis1">
        <span className="lbl" style={{ left: "4px" }}>
          0 · unlikely
        </span>
        <span className="lbl" style={{ right: "4px" }}>
          1 · likely
        </span>
        <span className="lbl" style={{ left: "50%", marginLeft: "-14px" }}>
          0.5
        </span>
        {marks.map((m, i) => (
          <Dot key={i} at={m.p} title={m.title} />
        ))}
      </div>
    </div>
  );
}
