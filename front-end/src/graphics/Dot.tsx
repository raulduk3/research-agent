/**
 * The mock's `span.dot` mark. `hue` colours an identity mark (the mock steps agents by 30
 * degrees); `kind` and `hidden` are the replay lanes' reader, baseline and hidden states.
 */
export function Dot({
  hue,
  kind,
  hidden = false,
  title,
}: {
  hue?: number;
  kind?: "you" | "base";
  hidden?: boolean;
  title?: string;
}) {
  const className = ["dot", kind, hidden ? "hid" : undefined].filter(Boolean).join(" ");
  const style = hue === undefined ? undefined : { background: `hsl(${hue}, 70%, 50%)` };
  return <span className={className} style={style} title={title} />;
}
