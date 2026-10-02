import { useEffect, useRef } from "react";
import { Link, Navigate, Outlet, useLocation } from "react-router";
import { useApi } from "../api/context.tsx";
import type { Storm } from "../api/types.ts";
import { useGet } from "../api/useGet.ts";
import { Lab, decoded, recall } from "../common.tsx";
import { BudgetStrip } from "./BudgetStrip.tsx";

function currentLabel(path: string): string {
  const pathname = path.toLowerCase();
  if (pathname.startsWith("/islands/")) return "island";
  if (pathname.startsWith("/papers/")) return "paper";
  if (pathname.startsWith("/runs/")) return "run";
  if (pathname === "/chat") return "chat";
  return "storm";
}

/** Where a visitor without the island's session is sent: sign in, then back to the page asked for. */
function signInPath(next: string, island: string | null): string {
  const query = new URLSearchParams({ next });
  if (island !== null) query.set("island", island);
  return `/login?${query.toString()}`;
}

/**
 * The shell of every page behind an island sign-in: the menu down the cascade (storm, island,
 * paper, run, chat), the budget strip, the page, the footer. Without a session it sends the
 * visitor to sign in and shows nothing. A session reads every island; it edits only its own.
 */
export function Layout({ onLeave }: { onLeave: () => void }) {
  const api = useApi();
  const location = useLocation();
  const storm = useGet<Storm>("/api/v1/public/storm");
  const reloadStorm = storm.reload;
  const seen = useRef(location.pathname);
  // The strip follows the visitor: each page change reads the month's cost again.
  useEffect(() => {
    if (seen.current === location.pathname) return;
    seen.current = location.pathname;
    reloadStorm();
  }, [location.pathname, reloadStorm]);

  const session = api.session;
  if (session === null) {
    // Sign-in offers the island the address names, when it names one.
    const asked = /^\/islands\/([^/]+)/i.exec(location.pathname)?.[1] ?? null;
    return <Navigate to={signInPath(location.pathname + location.search + location.hash, asked === null ? null : decoded(asked))} replace />;
  }

  const current = currentLabel(location.pathname);
  const paper = recall("paper");
  const run = recall("run");
  const item = (label: string, to: string | null) =>
    to === null ? (
      <span key={label}>{label}</span>
    ) : (
      <Link key={label} to={to}>
        {label === current ? <b>{label}</b> : label}
      </Link>
    );

  return (
    <>
      <nav>
        <Link className="brand" to="/">
          <span className="mark">🏝️</span>Atoll <span className="app-version">v1.1.0</span>
        </Link>
        {item("storm", "/")}
        {item("island", `/islands/${encodeURIComponent(session.island)}`)}
        {item("paper", paper === null ? null : `/papers/${encodeURIComponent(paper)}`)}
        {item("run", run === null ? null : `/runs/${encodeURIComponent(run)}`)}
        {item("chat", "/chat")}
        <a
          href="/"
          className="leave"
          onClick={(event) => {
            event.preventDefault();
            onLeave();
          }}
        >
          leave
        </a>
      </nav>
      <BudgetStrip storm={storm} />
      <Outlet />
      <Lab />
    </>
  );
}
