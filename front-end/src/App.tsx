import { useMemo } from "react";
import { BrowserRouter, Route, Routes, useNavigate } from "react-router";
import { createClient, type ApiClient } from "./api/client.ts";
import { ApiContext } from "./api/context.tsx";
import { Layout } from "./shell/Layout.tsx";
import { Agent } from "./pages/Agent.tsx";
import { Agents } from "./pages/Agents.tsx";
import { Overview } from "./pages/Overview.tsx";
import { Paper } from "./pages/Paper.tsx";
import { Run, Runs } from "./pages/Run.tsx";
import { Trace } from "./pages/Trace.tsx";
import { Login } from "./shell/Login.tsx";

function Routed({ fetch }: { fetch?: typeof globalThis.fetch }) {
  const navigate = useNavigate();
  const api: ApiClient = useMemo(
    () =>
      createClient({
        origin: import.meta.env.VITE_API_ORIGIN ?? "",
        ...(fetch ? { fetch } : {}),
        onUnauthenticated: () => void navigate("/login", { replace: true }),
      }),
    [fetch, navigate],
  );
  const logout = () => void api.logout().finally(() => navigate("/login", { replace: true }));

  return (
    <ApiContext.Provider value={api}>
      <Routes>
        <Route path="/login" element={<Login />} />
        <Route element={<Layout onLogout={logout} />}>
          <Route index element={<Overview />} />
          <Route path="agents" element={<Agents />} />
          <Route path="agents/:configurationId" element={<Agent />} />
          <Route path="runs" element={<Runs />} />
          <Route path="runs/:runId" element={<Run />} />
          <Route path="runs/:runId/trace" element={<Trace />} />
          <Route path="papers/:paperId" element={<Paper />} />
          <Route path="*" element={<h1>Not built yet</h1>} />
        </Route>
      </Routes>
    </ApiContext.Provider>
  );
}

export function App({ fetch }: { fetch?: typeof globalThis.fetch } = {}) {
  return (
    <BrowserRouter>
      <Routed {...(fetch ? { fetch } : {})} />
    </BrowserRouter>
  );
}
