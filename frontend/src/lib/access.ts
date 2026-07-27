import type { Me } from "@/lib/auth";

export const SEWING_WORKSPACE_HOME = "/sewing/flows";

const SEWING_WORKSPACE_NAV_ITEMS = [
  "/sewing/flows",
  "/sewing/daily-report",
  "/departments/SEW",
] as const;

const SEWING_WORK_ORDER_PATH = /^\/work-orders\/\d+\/sewing(?:\/|$)/;

export function isSewingRole(me: Me | undefined): boolean {
  return (me?.role ?? "").trim().toLowerCase() === "sewing";
}

export function isSewingWorkspacePath(pathname: string): boolean {
  return SEWING_WORK_ORDER_PATH.test(pathname) || SEWING_WORKSPACE_NAV_ITEMS.some(
    (route) => pathname === route || pathname.startsWith(`${route}/`),
  );
}

export function isSewingWorkspaceNavItem(href: string): boolean {
  return SEWING_WORKSPACE_NAV_ITEMS.some((route) => href === route);
}
