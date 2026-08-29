"use client";
import { useEffect, useState } from "react";
import useSWR from "swr";
import { fetcher, api } from "./api";

export type Me = {
  id: number;
  name: string;
  email: string;
  role?: string;
  department?: string;
  department_code?: string;
  permissions: string[];
  factory_code: "MIL" | "BST" | "ECO";
  assigned_factory_code: "MIL" | "BST" | "ECO";
  available_factories: ("MIL" | "BST" | "ECO")[];
};

export function useMe() {
  // undefined = not yet checked, boolean once /me has confirmed or rejected the HttpOnly cookie.
  const [hasToken, setHasToken] = useState<boolean | undefined>(undefined);
  useEffect(() => {
    setHasToken(true);
  }, []);
  const { data, error, isLoading, mutate } = useSWR<Me>(hasToken ? "/api/auth/me" : null, fetcher, {
    shouldRetryOnError: false,
    refreshInterval: 5 * 60 * 1000,
    refreshWhenHidden: false,
  });
  const checked = hasToken !== undefined && !isLoading;
  return {
    me: data,
    error,
    loading: isLoading,
    refresh: mutate,
    hasToken: checked ? Boolean(data && !error) : undefined,
  };
}

export function can(me: Me | undefined, ...perms: string[]): boolean {
  if (!me) return false;
  if (me.permissions.includes("*")) return true;
  return perms.some((p) => me.permissions.includes(p));
}

export function logout() {
  api.logout().finally(() => {
    if (typeof window !== "undefined") window.location.href = "/login";
  });
}
