import type { ReactNode } from "react";
import { Dot } from "./Dot.tsx";

/** One agent tile: its name, its identity hue and the note under it. */
export type Tile = { key: string; name: ReactNode; hue: number; note: ReactNode };

/** One island's row of tiles. */
export type TileRow = { island: string; tiles: readonly Tile[] };

/**
 * The mock's agent tiles (`div.tiles`): one `div.trow` per island, its name beside a grid of
 * `div.tile`s, each with the agent's `span.dot`. With no rows it shows `empty` in the frame.
 */
export function Tiles({ rows, empty }: { rows: readonly TileRow[]; empty: ReactNode }) {
  return (
    <div className="tiles">
      {rows.length === 0
        ? empty
        : rows.map((row) => (
            <div className="trow" key={row.island}>
              <span className="isl">{row.island}</span>
              <div className="tgrid">
                {row.tiles.map((tile) => (
                  <div className="tile" key={tile.key}>
                    <Dot hue={tile.hue} />
                    {tile.name}
                    <small>{tile.note}</small>
                  </div>
                ))}
              </div>
            </div>
          ))}
    </div>
  );
}
