import { useCallback, useEffect, useState } from "react";
import { useApi } from "./context.tsx";

export type Loaded<T> =
  | { state: "loading" }
  | { state: "failed"; error: unknown }
  | { state: "ready"; data: T };

/** One GET, refetched when the path or `reload` changes; a stale answer is dropped. A null path waits. */
export function useGet<T>(path: string | null): Loaded<T> & { reload: () => void } {
  const api = useApi();
  const [loaded, setLoaded] = useState<Loaded<T>>({ state: "loading" });
  const [generation, setGeneration] = useState(0);

  useEffect(() => {
    if (path === null) return;
    let live = true;
    setLoaded({ state: "loading" });
    api.get<T>(path).then(
      (data) => live && setLoaded({ state: "ready", data }),
      (error: unknown) => live && setLoaded({ state: "failed", error }),
    );
    return () => {
      live = false;
    };
  }, [api, path, generation]);

  const reload = useCallback(() => setGeneration((g) => g + 1), []);
  return { ...loaded, reload };
}
