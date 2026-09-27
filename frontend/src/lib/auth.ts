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
  access_configured?: boolean;
  factory_code: "MIL" | "BST" | "ECO";
  assigned_factory_code: "MIL" | "BST" | "ECO";
  available_factories: ("MIL" | "BST" | "ECO")[];
};

function isSessionRejected(error: unknown): boolean {
  return error instanceof Error && /^(401|403):/.test(error.message);
}

export function useMe() {
  // undefined = not yet checked, boolean once /me has confirmed or rejected the HttpOnly cookie.
  const [hasToken, setHasToken] = useState<boolean | undefined>(undefined);
  useEffect(() => {
    setHasToken(true);
  }, []);
  const { data, error, isLoading, mutate } = useSWR<Me>(hasToken ? "/api/auth/me" : null, fetcher, {
    shouldRetryOnError: (error) => !isSessionRejected(error),
    errorRetryCount: 3,
    errorRetryInterval: 3_000,
    refreshInterval: 5 * 60 * 1000,
    refreshWhenHidden: false,
  });
  const checked = hasToken !== undefined && !isLoading;
  const rejected = isSessionRejected(error);
  return {
    me: rejected ? undefined : data,
    error,
    loading: isLoading,
    refresh: mutate,
    // Network/server failures say nothing about whether the cookie is valid.
    hasToken: rejected ? false : checked && data ? true : undefined,
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
