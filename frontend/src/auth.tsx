import { createContext, useCallback, useContext, useEffect, useMemo, useState, type ReactNode } from "react";
import { get, post, session, setUnauthorizedHandler, type User } from "./api";

interface AuthState {
  user: User | null;
  ready: boolean;
  login: (username: string, password: string) => Promise<void>;
  logout: () => void;
}

const Ctx = createContext<AuthState | null>(null);

export function AuthProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<User | null>(null);
  const [ready, setReady] = useState(false);

  const logout = useCallback(() => {
    session.set(null);
    setUser(null);
  }, []);

  useEffect(() => {
    setUnauthorizedHandler(logout);
    if (!session.get()) {
      setReady(true);
      return;
    }
    get<User>("/auth/me")
      .then(setUser)
      .catch(() => session.set(null))
      .finally(() => setReady(true));
  }, [logout]);

  const login = useCallback(async (username: string, password: string) => {
    const r = await post<{ token: string; user: User }>("/auth/login", { username, password });
    session.set(r.token);
    setUser(r.user);
  }, []);

  const value = useMemo(() => ({ user, ready, login, logout }), [user, ready, login, logout]);
  return <Ctx.Provider value={value}>{children}</Ctx.Provider>;
}

export function useAuth(): AuthState {
  const v = useContext(Ctx);
  if (!v) throw new Error("useAuth outside AuthProvider");
  return v;
}
