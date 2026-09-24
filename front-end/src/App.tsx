import { useMemo } from "react";
import { BrowserRouter, Route, Routes, useNavigate } from "react-router";
import { createClient, type ApiClient } from "./api/client.ts";
import { ApiContext } from "./api/context.tsx";
import { Layout } from "./shell/Layout.tsx";
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
          <Route path="*" element={<h1>Owner home</h1>} />
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
