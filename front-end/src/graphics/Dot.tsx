/**
 * The mock's `span.dot` mark. `hue` colours an identity mark (the mock steps agents by 30
 * degrees); `kind` and `hidden` are the replay lanes' reader, baseline and hidden states; `at`
 * places the mark on a lane's chance axis, 0 to 1.
 */
export function Dot({
  hue,
  kind,
  hidden = false,
  at,
  title,
}: {
  hue?: number;
  kind?: "you" | "base";
  hidden?: boolean;
  at?: number;
  title?: string;
}) {
  const className = ["dot", kind, hidden ? "hid" : undefined].filter(Boolean).join(" ");
  const style = {
    ...(hue === undefined ? {} : { background: `hsl(${hue}, 70%, 50%)` }),
    ...(at === undefined ? {} : { left: `${Math.round(at * 10000) / 100}%` }),
  };
  return <span className={className} style={style} title={title} />;
}
