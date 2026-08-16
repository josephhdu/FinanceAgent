import { createContext, useCallback, useContext, useState, type ReactNode } from "react";

interface AuthCtx {
  token: string | null;
  username: string;
  login: (token: string, username: string) => void;
  logout: () => void;
}

const Ctx = createContext<AuthCtx | null>(null);

export function AuthProvider({ children }: { children: ReactNode }) {
  const [token, setToken] = useState<string | null>(() => localStorage.getItem("financeai_token"));
  const [username, setUsername] = useState<string>(() => localStorage.getItem("financeai_user") || "");

  const login = useCallback((t: string, u: string) => {
    localStorage.setItem("financeai_token", t);
    localStorage.setItem("financeai_user", u);
    setToken(t);
    setUsername(u);
  }, []);

  const logout = useCallback(() => {
    localStorage.removeItem("financeai_token");
    localStorage.removeItem("financeai_user");
    localStorage.removeItem("financeai_sid"); // don't carry a chat into the next login
    setToken(null);
    setUsername("");
  }, []);

  return <Ctx.Provider value={{ token, username, login, logout }}>{children}</Ctx.Provider>;
}

export function useAuth(): AuthCtx {
  const c = useContext(Ctx);
  if (!c) throw new Error("useAuth must be used within an AuthProvider");
  return c;
}
