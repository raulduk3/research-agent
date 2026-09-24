import { createContext, useContext } from "react";
import type { ApiClient } from "./client.ts";

export const ApiContext = createContext<ApiClient | null>(null);

export function useApi(): ApiClient {
  const api = useContext(ApiContext);
  if (!api) throw new Error("useApi outside ApiContext");
  return api;
}
