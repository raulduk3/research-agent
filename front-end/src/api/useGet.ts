import { useCallback, useEffect, useState } from "react";
import type { Query } from "./client.ts";
import { useApi } from "./context.tsx";

export type Loaded<T> =
  | { state: "loading" }
  | { state: "failed"; error: unknown }
  | { state: "ready"; data: T };

/** One GET, refetched when the path, query or `reload` changes; a stale answer is dropped. */
export function useGet<T>(path: string | null, query?: Query): Loaded<T> & { reload: () => void } {
  const api = useApi();
  const [loaded, setLoaded] = useState<Loaded<T>>({ state: "loading" });
  const [generation, setGeneration] = useState(0);
  const queryKey = JSON.stringify(query ?? {});

  useEffect(() => {
    if (path === null) return;
    let live = true;
    setLoaded({ state: "loading" });
    api.get<T>(path, JSON.parse(queryKey) as Query).then(
      (data) => live && setLoaded({ state: "ready", data }),
      (error: unknown) => live && setLoaded({ state: "failed", error }),
    );
    return () => {
      live = false;
    };
  }, [api, path, queryKey, generation]);

  const reload = useCallback(() => setGeneration((g) => g + 1), []);
  return { ...loaded, reload };
}
