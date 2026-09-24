import { Link, Outlet, useLocation } from "react-router";
import { Diag } from "./Diag.tsx";
import { Lab } from "./Lab.tsx";

/** The rating app's pages the mock's menu leads with (design-mock/overview.html). */
export const PRIMARY_PAGES: readonly string[] = ["today", "accepted", "about"];

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

/**
 * The menu entry the current path belongs to: its own page, or the list page above a detail page.
 * A page under no entry (a paper, a digest) has none, and the dropdown is only "more", as in
 * design-mock/paper-P1.html.
 */
function here(pathname: string): string | null {
  const exact = OWNER_PAGES.find(([path]) => path === pathname);
  if (exact) return exact[1];
  const section = OWNER_PAGES.find(([path]) => path !== "/" && pathname.startsWith(`${path}/`));
  return section ? section[1] : null;
}

/**
 * The mock's menu, element for element: brand, the rating app's primary links, then the owner
 * pages and log out in the `more` dropdown whose summary names the current page. The rating app
 * is not served from this origin, so its links render without a target.
 */
export function Layout({ onLogout }: { onLogout: () => void }) {
  const current = here(useLocation().pathname);
  return (
    <>
      <nav>
        <Link className="brand" to="/">
          <span className="mark">🏝️</span>Atoll
        </Link>
        {PRIMARY_PAGES.map((label) => (
          <a key={label}>{label}</a>
        ))}
        <details className="more">
          {current === null ? (
            <summary>more ▾</summary>
          ) : (
            <summary>
              <b className="here">{current}</b>
              <span className="mo">more</span> ▾
            </summary>
          )}
          <div>
            {OWNER_PAGES.map(([path, label]) => (
              <Link key={path} to={path}>
                {label === current ? <b>{label}</b> : label}
              </Link>
            ))}
            <a
              href="/login"
              onClick={(e) => {
                e.preventDefault();
                onLogout();
              }}
            >
              log out
            </a>
          </div>
        </details>
      </nav>
      <Outlet />
      <Diag />
      <Lab />
    </>
  );
}
