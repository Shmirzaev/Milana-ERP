import { createContext, PropsWithChildren, useCallback, useContext, useEffect, useMemo, useState } from "react";

import { loginWithPassword, normalizeBaseUrl, request } from "../api/client";
import type { Me } from "../types/api";
import { deleteStoredValue, getStoredValue, setStoredValue } from "./tokenStorage";

type AuthContextValue = {
  apiBaseUrl: string;
  bootstrapping: boolean;
  me: Me | null;
  token: string | null;
  signIn: (baseUrl: string, email: string, password: string) => Promise<void>;
  signOut: () => Promise<void>;
  refreshMe: () => Promise<void>;
  setApiBaseUrl: (value: string) => void;
};

const TOKEN_KEY = "milana.erp.mobile.token";
const API_URL_KEY = "milana.erp.mobile.apiUrl";
const AuthContext = createContext<AuthContextValue | null>(null);

export function AuthProvider({ children }: PropsWithChildren) {
  const [apiBaseUrl, setApiBaseUrlState] = useState(normalizeBaseUrl());
  const [bootstrapping, setBootstrapping] = useState(true);
  const [me, setMe] = useState<Me | null>(null);
  const [token, setToken] = useState<string | null>(null);

  const setApiBaseUrl = useCallback((value: string) => {
    setApiBaseUrlState(normalizeBaseUrl(value));
  }, []);

  const loadMe = useCallback(async (nextToken: string, nextBaseUrl: string) => {
    const profile = await request<Me>("/api/auth/me", {
      token: nextToken,
      baseUrl: nextBaseUrl,
      timeoutMs: 15000,
    });
    setMe(profile);
  }, []);

  const signOut = useCallback(async () => {
    setToken(null);
    setMe(null);
    await deleteStoredValue(TOKEN_KEY);
  }, []);

  const refreshMe = useCallback(async () => {
    if (!token) return;
    try {
      await loadMe(token, apiBaseUrl);
    } catch {
      await signOut();
    }
  }, [apiBaseUrl, loadMe, signOut, token]);

  const signIn = useCallback(
    async (baseUrl: string, email: string, password: string) => {
      const nextBaseUrl = normalizeBaseUrl(baseUrl);
      const result = await loginWithPassword(nextBaseUrl, email, password);
      await setStoredValue(TOKEN_KEY, result.access_token);
      await setStoredValue(API_URL_KEY, nextBaseUrl);
      setApiBaseUrlState(nextBaseUrl);
      setToken(result.access_token);
      await loadMe(result.access_token, nextBaseUrl);
    },
    [loadMe],
  );

  useEffect(() => {
    let mounted = true;
    async function restoreSession() {
      try {
        const [storedToken, storedBaseUrl] = await Promise.all([
          getStoredValue(TOKEN_KEY),
          getStoredValue(API_URL_KEY),
        ]);
        const nextBaseUrl = normalizeBaseUrl(storedBaseUrl);
        if (!mounted) return;
        setApiBaseUrlState(nextBaseUrl);
        if (storedToken) {
          setToken(storedToken);
          await loadMe(storedToken, nextBaseUrl);
        }
      } catch {
        await deleteStoredValue(TOKEN_KEY);
        if (mounted) {
          setToken(null);
          setMe(null);
        }
      } finally {
        if (mounted) setBootstrapping(false);
      }
    }
    void restoreSession();
    return () => {
      mounted = false;
    };
  }, [loadMe]);

  const value = useMemo(
    () => ({
      apiBaseUrl,
      bootstrapping,
      me,
      token,
      signIn,
      signOut,
      refreshMe,
      setApiBaseUrl,
    }),
    [apiBaseUrl, bootstrapping, me, refreshMe, setApiBaseUrl, signIn, signOut, token],
  );

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuth() {
  const context = useContext(AuthContext);
  if (!context) throw new Error("useAuth must be used inside AuthProvider");
  return context;
}
