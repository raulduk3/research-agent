/** One run on a lane: its minutes after midnight UTC, its agent's hue, or null when it ended without answering. */
export type BoardRun = { start: number; end: number; hue: number | null; title: string };

/** One worker container across the day. */
export type BoardLane = { name: string; runs: readonly BoardRun[] };

/** The mock's colour for a run that ended without answering. */
export const NO_ANSWER = "#d9d4c7";

const HOURS = ["00", "06", "12", "18", "24"] as const;

/**
 * The mock's day board (`div.board`): the hour axis, then one `div.lane` per container with an
 * svg over the day's 1440 minutes and one block per run. With no lanes it keeps the axis alone.
 */
export function Board({ lanes, label }: { lanes: readonly BoardLane[]; label: string }) {
  return (
    <div className="board" role="img" aria-label={label}>
      <div className="axis">
        <span className="ln" />
        <div>
          {HOURS.map((hour) => (
            <span key={hour}>{hour}</span>
          ))}
        </div>
      </div>
      {lanes.map((lane) => (
        <div className="lane" key={lane.name}>
          <span className="ln">{lane.name}</span>
          <svg viewBox="0 0 1440 24" preserveAspectRatio="none" aria-hidden="true">
            {lane.runs.map((run) => (
              <rect
                key={`${run.start}-${run.title}`}
                x={run.start}
                y={1}
                width={Math.max(run.end - run.start, 0)}
                height={22}
                rx={3}
                fill={run.hue === null ? NO_ANSWER : `hsl(${run.hue}, 70%, 55%)`}
              >
                <title>{run.title}</title>
              </rect>
            ))}
          </svg>
        </div>
      ))}
    </div>
  );
}
