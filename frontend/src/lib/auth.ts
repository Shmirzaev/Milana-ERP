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
  permissions: string[];
};

export function useMe() {
  // undefined = not yet detected (initial render / SSR), boolean once useEffect has run.
  const [hasToken, setHasToken] = useState<boolean | undefined>(undefined);
  useEffect(() => {
    setHasToken(typeof window !== "undefined" && !!localStorage.getItem("erp_token"));
  }, []);
  const { data, error, isLoading, mutate } = useSWR<Me>(hasToken ? "/api/auth/me" : null, fetcher);
  return { me: data, error, loading: isLoading, refresh: mutate, hasToken };
}

export function can(me: Me | undefined, ...perms: string[]): boolean {
  if (!me) return false;
  if (me.permissions.includes("*")) return true;
  return perms.some((p) => me.permissions.includes(p));
}

export function logout() {
  api.logout();
  if (typeof window !== "undefined") window.location.href = "/login";
}
