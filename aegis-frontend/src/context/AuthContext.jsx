import { createContext, useCallback, useContext, useEffect, useMemo, useState } from "react";
import api, { tokenStore } from "../lib/api.js";

const AuthContext = createContext(null);

function decodeToken(token) {
  try {
    const payload = token.split(".")[1];
    return JSON.parse(atob(payload.replace(/-/g, "+").replace(/_/g, "/")));
  } catch {
    return null;
  }
}

function normalizeUser(profile, token) {
  const decoded = token ? decodeToken(token) : null;
  return {
    email: profile?.email || decoded?.sub || decoded?.email || "operator@aegis.ai",
    role: profile?.role || decoded?.role || "operator",
    name: profile?.name || profile?.email?.split("@")[0] || decoded?.sub?.split("@")[0] || "Aegis Operator"
  };
}

export function AuthProvider({ children }) {
  const [token, setToken] = useState(() => tokenStore.get());
  const [user, setUser] = useState(() => (tokenStore.get() ? normalizeUser(null, tokenStore.get()) : null));
  const [loading, setLoading] = useState(Boolean(tokenStore.get()));

  const loadProfile = useCallback(async (activeToken = tokenStore.get()) => {
    if (!activeToken) {
      setLoading(false);
      return;
    }
    try {
      const { data } = await api.get("/auth/me");
      setUser(normalizeUser(data, activeToken));
    } catch {
      setUser(normalizeUser(null, activeToken));
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { loadProfile(); }, [loadProfile]);

  const login = async (credentials) => {
    const { data } = await api.post("/auth/login", credentials);
    const nextToken = data.access_token || data.token || data.jwt_token;
    if (!nextToken) throw new Error("Login succeeded but no token was returned.");
    tokenStore.set(nextToken);
    setToken(nextToken);
    await loadProfile(nextToken);
  };

  const register = async (payload) => api.post("/auth/register", payload).then((res) => res.data);
  const logout = () => { tokenStore.clear(); setToken(null); setUser(null); };

  const value = useMemo(() => ({
    token,
    user,
    loading,
    login,
    register,
    logout,
    isAuthenticated: Boolean(token),
    isAdmin: user?.role === "admin"
  }), [token, user, loading]);

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuthContext() {
  const context = useContext(AuthContext);
  if (!context) throw new Error("useAuthContext must be used inside AuthProvider");
  return context;
}
