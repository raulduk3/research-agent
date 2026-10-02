import { useCallback, useEffect, useRef, useState } from "react";
import { useApi } from "./context.tsx";

export type Loaded<T> =
  | { state: "loading" }
  | { state: "failed"; error: unknown }
  | { state: "ready"; data: T };

/**
 * One GET, refetched when the path or `reload` changes; a stale answer is dropped. A null path
 * waits. A reload of the same path keeps the answer on screen until the new one arrives.
 */
export function useGet<T>(path: string | null): Loaded<T> & { reload: () => void } {
  const api = useApi();
  const [loaded, setLoaded] = useState<Loaded<T>>({ state: "loading" });
  const [generation, setGeneration] = useState(0);

  const shown = useRef<string | null>(null);

  useEffect(() => {
    if (path === null) return;
    let live = true;
    if (shown.current !== path) setLoaded({ state: "loading" });
    shown.current = path;
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
