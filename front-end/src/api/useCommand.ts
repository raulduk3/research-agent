import { useRef, useState } from "react";
import { newIdempotencyKey } from "./client.ts";
import { useApi } from "./context.tsx";

export type CommandState<T> =
  | { state: "idle" }
  | { state: "sending" }
  | { state: "done"; data: T }
  | { state: "failed"; error: unknown };

/**
 * One owner command. A retry of the same body reuses its Idempotency-Key, so a lost answer is
 * replayed rather than repeated; a changed body is a new intended action with a new key.
 */
export function useCommand<T>(path: string) {
  const api = useApi();
  const [result, setResult] = useState<CommandState<T>>({ state: "idle" });
  const last = useRef<{ body: string; key: string } | null>(null);

  async function send(body: Record<string, string>) {
    const canonical = JSON.stringify(body);
    if (last.current?.body !== canonical) last.current = { body: canonical, key: newIdempotencyKey() };
    setResult({ state: "sending" });
    try {
      setResult({ state: "done", data: await api.post<T>(path, body, last.current.key) });
    } catch (error) {
      setResult({ state: "failed", error });
    }
  }

  return { result, send };
}
