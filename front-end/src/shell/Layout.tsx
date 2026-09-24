import { NavLink, Outlet } from "react-router";
import { Lab } from "./Lab.tsx";

/** The owner pages of the mock's menu, in the mock's order (design-mock/overview.html). */
export const OWNER_PAGES: readonly (readonly [path: string, label: string])[] = [
  ["/impact", "impact"],
  ["/swarm", "swarm"],
  ["/agents", "agents"],
  ["/runs", "runs"],
  ["/islands", "islands"],
  ["/reports", "reports"],
  ["/models", "models"],
  ["/", "owner home"],
  ["/costs", "costs"],
];

export function Layout({ onLogout }: { onLogout: () => void }) {
  return (
    <>
      <nav>
        <NavLink className="brand" to="/">
          <span className="mark">🏝️</span>Atoll
        </NavLink>
        {OWNER_PAGES.map(([path, label]) => (
          <NavLink key={path} to={path} end>
            {({ isActive }) => (isActive ? <b className="here">{label}</b> : label)}
          </NavLink>
        ))}
        <button type="button" className="linkish" onClick={onLogout}>
          log out
        </button>
      </nav>
      <main>
        <Outlet />
      </main>
      <Lab />
    </>
  );
}
