import { useCallback } from "react";
import { useAuth } from "../auth/AuthContext";

export interface PostResult<T> {
  ok: boolean;
  status: number;
  data: T;
}

/**
 * Auth-aware fetch helpers. Every call carries the Bearer token, and a 401
 * transparently logs the user out (mirrors the original SPA's behavior).
 */
export function useApi() {
  const { token, logout } = useAuth();

  const get = useCallback(
    async <T,>(path: string): Promise<T> => {
      const r = await fetch(path, { headers: { Authorization: `Bearer ${token}` } });
      if (r.status === 401) {
        logout();
        throw new Error("unauthorized");
      }
      if (!r.ok) throw new Error(`HTTP ${r.status}`);
      return (await r.json()) as T;
    },
    [token, logout],
  );

  const post = useCallback(
    async <T,>(path: string, body: unknown): Promise<PostResult<T>> => {
      const r = await fetch(path, {
        method: "POST",
        headers: { "Content-Type": "application/json", Authorization: `Bearer ${token}` },
        body: JSON.stringify(body),
      });
      if (r.status === 401) {
        logout();
        throw new Error("unauthorized");
      }
      const data = (await r.json().catch(() => ({}))) as T;
      return { ok: r.ok, status: r.status, data };
    },
    [token, logout],
  );

  const del = useCallback(
    async (path: string): Promise<void> => {
      await fetch(path, { method: "DELETE", headers: { Authorization: `Bearer ${token}` } });
    },
    [token],
  );

  return { get, post, del };
}
