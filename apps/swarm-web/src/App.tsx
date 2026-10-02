import { useMemo, type ReactElement } from "react";
import { BrowserRouter, Route, Routes, useNavigate } from "react-router";
import { createClient, type ApiClient } from "./api/client.ts";
import { ApiContext } from "./api/context.tsx";
import { ChatPage } from "./pages/Chat.tsx";
import { IslandPage } from "./pages/Island.tsx";
import { PaperPage } from "./pages/Paper.tsx";
import { RunPage } from "./pages/Run.tsx";
import { Splash } from "./pages/Splash.tsx";
import { Layout } from "./shell/Layout.tsx";
import { Login } from "./shell/Login.tsx";

export type Page = { family: string; path: string; open: boolean; element: ReactElement };

/**
 * Every page the app serves. `open` pages need no session: the public splash and the sign-in.
 * The rest sit behind the island session in the shell.
 */
export const PAGES: readonly Page[] = [
  { family: "splash", path: "/", open: true, element: <Splash /> },
  { family: "login", path: "/login", open: true, element: <Login /> },
  { family: "island", path: "/islands/:island", open: false, element: <IslandPage /> },
  { family: "paper", path: "/papers/:paperId", open: false, element: <PaperPage /> },
  { family: "run", path: "/runs/:runId", open: false, element: <RunPage /> },
  { family: "chat", path: "/chat", open: false, element: <ChatPage /> },
];

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
  const leave = () => {
    api.logout();
    void navigate("/", { replace: true });
  };

  return (
    <ApiContext.Provider value={api}>
      <Routes>
        {PAGES.filter((p) => p.open).map((p) => (
          <Route key={p.path} path={p.path} element={p.element} />
        ))}
        <Route element={<Layout onLeave={leave} />}>
          {PAGES.filter((p) => !p.open).map((p) => (
            <Route key={p.path} path={p.path} element={p.element} />
          ))}
        </Route>
        <Route path="*" element={<Splash />} />
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
