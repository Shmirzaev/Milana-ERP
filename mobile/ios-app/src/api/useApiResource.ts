import { useCallback, useEffect, useState } from "react";

import { useAuth } from "../auth/AuthContext";
import { request } from "./client";

type ResourceState<T> = {
  data: T | null;
  loading: boolean;
  refreshing: boolean;
  error: string | null;
  reload: () => Promise<void>;
};

export function useApiResource<T>(path: string | null, immediate = true): ResourceState<T> {
  const { token, apiBaseUrl, signOut } = useAuth();
  const [data, setData] = useState<T | null>(null);
  const [loading, setLoading] = useState(Boolean(path && immediate));
  const [refreshing, setRefreshing] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const reload = useCallback(async () => {
    if (!path || !token) return;
    setError(null);
    setRefreshing(true);
    try {
      const next = await request<T>(path, { token, baseUrl: apiBaseUrl });
      setData(next);
    } catch (err) {
      const message = err instanceof Error ? err.message : "Could not load data";
      if (message.includes("401")) {
        await signOut();
      }
      setError(message);
    } finally {
      setRefreshing(false);
      setLoading(false);
    }
  }, [apiBaseUrl, path, signOut, token]);

  useEffect(() => {
    if (!immediate || !path) return;
    setLoading(true);
    void reload();
  }, [immediate, path, reload]);

  return { data, loading, refreshing, error, reload };
}
