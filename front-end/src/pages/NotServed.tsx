import { useLocation } from "react-router";

/**
 * The mock's menu keeps impact, swarm and islands, but no /api/v1 route serves them yet, and a
 * page may not compute what the API does not send. It says so instead of showing mock data.
 */
export function NotServed() {
  const { pathname } = useLocation();
  return (
    <>
      <h1>{pathname.split("/")[1] || "page"}</h1>
      <p className="meta">No /api/v1 route serves this page yet. The design mock shows its intended layout.</p>
    </>
  );
}
