import { createContext, useCallback, useContext, useEffect, useState } from "react";

import { AuthAPI } from "../lib/api";
import {
  clearTokens,
  getAccessToken,
  getRefreshToken,
  setTokens,
} from "../lib/tokens";

const AuthContext = createContext(null);

export function AuthProvider({ children }) {
  const [user, setUser] = useState(null);
  const [loading, setLoading] = useState(true);

  // On mount, if we already have a token, resolve the current user.
  useEffect(() => {
    let active = true;
    async function bootstrap() {
      if (!getAccessToken()) {
        setLoading(false);
        return;
      }
      try {
        const me = await AuthAPI.me();
        if (active) setUser(me);
      } catch {
        clearTokens();
      } finally {
        if (active) setLoading(false);
      }
    }
    bootstrap();
    return () => {
      active = false;
    };
  }, []);

  const login = useCallback(async (email, password) => {
    const tokens = await AuthAPI.login(email, password);
    setTokens(tokens);
    const me = await AuthAPI.me();
    setUser(me);
    return me;
  }, []);

  const register = useCallback(
    async (data) => {
      await AuthAPI.register(data);
      return login(data.email, data.password);
    },
    [login],
  );

  const logout = useCallback(async () => {
    const refresh_token = getRefreshToken();
    if (refresh_token) {
      try {
        await AuthAPI.logout(refresh_token);
      } catch {
        /* ignore */
      }
    }
    clearTokens();
    setUser(null);
  }, []);

  return (
    <AuthContext.Provider value={{ user, loading, login, register, logout }}>
      {children}
    </AuthContext.Provider>
  );
}

export function useAuth() {
  const ctx = useContext(AuthContext);
  if (!ctx) throw new Error("useAuth must be used within AuthProvider");
  return ctx;
}
