import katex from "katex";
import "katex/dist/katex.min.css";

const MATH = /(\$\$[\s\S]+?\$\$|\\\[[\s\S]+?\\\]|\\\([\s\S]+?\\\)|(?<!\$)\$(?!\s|\$)[\s\S]+?(?<!\s)\$(?!\$))/g;

type Piece =
  | { kind: "text"; text: string }
  | { kind: "math"; text: string; display: boolean };

export function splitMath(text: string): Piece[] {
  const pieces: Piece[] = [];
  let at = 0;
  for (const found of text.matchAll(MATH)) {
    const raw = found[0];
    const index = found.index ?? 0;
    if (index > at) pieces.push({ kind: "text", text: text.slice(at, index) });
    if (raw.startsWith("$$")) pieces.push({ kind: "math", text: raw.slice(2, -2), display: true });
    else if (raw.startsWith("\\[")) pieces.push({ kind: "math", text: raw.slice(2, -2), display: true });
    else if (raw.startsWith("\\(")) pieces.push({ kind: "math", text: raw.slice(2, -2), display: false });
    else pieces.push({ kind: "math", text: raw.slice(1, -1), display: false });
    at = index + raw.length;
  }
  if (at < text.length) pieces.push({ kind: "text", text: text.slice(at) });
  return pieces;
}

function render(tex: string, displayMode: boolean): string {
  return katex.renderToString(tex, {
    displayMode,
    throwOnError: false,
    strict: false,
    trust: false,
    output: "html",
  });
}

export function MathText({ text }: { text: string }) {
  return splitMath(text).map((piece, i) =>
    piece.kind === "text" ? (
      piece.text
    ) : (
      <span
        key={i}
        className={piece.display ? "math display" : "math inline"}
        dangerouslySetInnerHTML={{ __html: render(piece.text, piece.display) }}
      />
    ),
  );
}
