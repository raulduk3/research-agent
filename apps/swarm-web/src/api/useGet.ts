import { useCallback, useEffect, useRef, useState } from "react";
import { ApiError } from "./client.ts";
import { useApi } from "./context.tsx";

export type Loaded<T> =
  | { state: "loading" }
  | { state: "failed"; error: unknown }
  | { state: "ready"; data: T };

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
      (error: unknown) => {
        const temporary = !(error instanceof ApiError) || error.status >= 500 || error.status === 408 || error.status === 429 || (error.status >= 200 && error.status < 300);
        if (live) setLoaded((previous) => temporary && previous.state === "ready" ? previous : { state: "failed", error });
      },
    );
    return () => {
      live = false;
    };
  }, [api, path, generation]);

  const reload = useCallback(() => setGeneration((g) => g + 1), []);
  return { ...loaded, reload };
}
