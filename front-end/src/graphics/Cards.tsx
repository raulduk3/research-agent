import type { ReactNode } from "react";

/** The mock's card grid (`div.cards`). */
export function Cards({ children }: { children: ReactNode }) {
  return <div className="cards">{children}</div>;
}

/** One mock card (`div.card`): its title, its value, and an optional note under it. */
export function Card({ title, value, meta }: { title: string; value: ReactNode; meta?: ReactNode }) {
  return (
    <div className="card">
      <b>{title}</b>
      <div className="v">{value}</div>
      {meta !== undefined && <span className="meta">{meta}</span>}
    </div>
  );
}
