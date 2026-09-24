import { useMemo } from "react";
import { BrowserRouter, Route, Routes, useNavigate } from "react-router";
import { createClient, type ApiClient } from "./api/client.ts";
import { ApiContext } from "./api/context.tsx";
import { Layout } from "./shell/Layout.tsx";
import { Agent } from "./pages/Agent.tsx";
import { Agents } from "./pages/Agents.tsx";
import { Costs } from "./pages/Costs.tsx";
import { Digest } from "./pages/Digest.tsx";
import { Island } from "./pages/Island.tsx";
import { Islands } from "./pages/Islands.tsx";
import { Model, Models } from "./pages/Model.tsx";
import { NotServed } from "./pages/NotServed.tsx";
import { Overview } from "./pages/Overview.tsx";
import { Paper, PaperRecord } from "./pages/Paper.tsx";
import { Question } from "./pages/Question.tsx";
import { Questions } from "./pages/Questions.tsx";
import { Report } from "./pages/Report.tsx";
import { Reports } from "./pages/Reports.tsx";
import { Run, Runs } from "./pages/Run.tsx";
import { Seed } from "./pages/Seed.tsx";
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
          <Route path="islands" element={<Islands />} />
          <Route path="islands/:island" element={<Island />} />
          <Route path="runs" element={<Runs />} />
          <Route path="runs/:runId" element={<Run />} />
          <Route path="runs/:runId/trace" element={<Trace />} />
          <Route path="papers/:paperId" element={<Paper />} />
          <Route path="papers/:paperId/record" element={<PaperRecord />} />
          <Route path="questions" element={<Questions />} />
          <Route path="questions/:questionId" element={<Question />} />
          <Route path="reports" element={<Reports />} />
          <Route path="reports/:island/:isoWeek" element={<Report />} />
          <Route path="models" element={<Models />} />
          <Route path="models/:manifestHash" element={<Model />} />
          <Route path="costs" element={<Costs />} />
          <Route path="digests/:digestHash" element={<Digest />} />
          <Route path="seed" element={<Seed />} />
          <Route path="*" element={<NotServed />} />
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
