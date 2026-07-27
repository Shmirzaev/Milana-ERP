"use client";
import { useEffect } from "react";
import { usePathname, useRouter } from "next/navigation";
import { can, useMe } from "@/lib/auth";
import { api } from "@/lib/api";
import { isSewingRole, isSewingWorkspacePath, SEWING_WORKSPACE_HOME } from "@/lib/access";
import { useT } from "@/lib/i18n";

const SUPER_ADMIN_PERMISSION = "admin.super";

type RouteGuard = {
  prefix: string;
  perms?: string[];
  exact?: boolean;
  superOnly?: boolean;
};

const ROUTE_GUARDS: RouteGuard[] = [
  { prefix: "/admin/data", superOnly: true },
  { prefix: "/admin/mcp", superOnly: true },
  { prefix: "/admin/users", perms: ["admin.users", "*"] },
  { prefix: "/admin/departments", perms: ["*"] },
  { prefix: "/admin/audit-logs", perms: ["admin.audit", "*"] },
  { prefix: "/admin/employees", perms: ["hr.employees", "*"] },
  { prefix: "/customers", perms: ["sales.customers", "sales.orders", "finance.view", "*"] },
  { prefix: "/sales-orders", perms: ["sales.orders", "*"] },
  { prefix: "/order-history", perms: ["sales.orders", "*"] },
  { prefix: "/models", perms: ["modeling.models", "*"] },
  { prefix: "/brands", perms: ["modeling.brands", "*"] },
  { prefix: "/collections", perms: ["modeling.collections", "*"] },
  { prefix: "/planning", perms: ["planning.view", "planning.production", "*"] },
  { prefix: "/forecasting", perms: ["forecasting.view", "*"] },
  { prefix: "/production-orders", perms: ["planning.view", "planning.production", "processes.view", "*"] },
  { prefix: "/traceability", perms: ["traceability.view", "*"] },
  { prefix: "/purchasing/receiving", perms: ["purchasing.receive", "*"] },
  { prefix: "/purchasing", perms: ["purchasing.view", "purchasing.request", "purchasing.approve", "purchasing.order", "*"] },
  { prefix: "/inventory/master-data", perms: ["storage.items", "storage.suppliers", "*"] },
  { prefix: "/inventory/receive", perms: ["storage.receive", "*"] },
  { prefix: "/inventory/batches", perms: ["storage.items", "*"] },
  { prefix: "/inventory", perms: ["storage.items", "storage.receive", "inventory.reservations.view", "*"] },
  { prefix: "/warehouse-stock", perms: ["storage.packages", "storage.shipment", "*"] },
  { prefix: "/warehouse-map", perms: ["storage.packages", "storage.shipment", "*"] },
  { prefix: "/shipments", perms: ["storage.shipment", "*"] },
  { prefix: "/packages/scan", perms: ["packaging.packages", "storage.packages", "*"] },
  { prefix: "/packages", perms: ["packaging.packages", "storage.packages", "storage.shipment", "*"] },
  { prefix: "/bundles/scan/cutting", perms: ["cutting.bundles", "cutting.records", "*"] },
  { prefix: "/bundles/scan/printing", perms: ["printing.bundles", "printing.records", "*"] },
  { prefix: "/bundles/scan/sewing", perms: ["sewing.bundles", "sewing.records", "*"] },
  { prefix: "/bundles", perms: ["cutting.bundles", "cutting.records", "planning.production", "*"] },
  { prefix: "/cutting-inventory", perms: ["cutting.bundles", "cutting.records", "planning.production", "*"] },
  { prefix: "/cutting-passports", perms: ["cutting.records", "cutting.bundles", "planning.production", "*"] },
  { prefix: "/sewing/flows", perms: ["sewing.workspace"] },
  { prefix: "/sewing/daily-report", perms: ["sewing.workspace"] },
  { prefix: "/departments/CUT", perms: ["cutting.records", "cutting.bundles", "planning.production", "*"] },
  { prefix: "/departments/ECT", perms: ["cutting.records", "cutting.bundles", "planning.production", "*"] },
  { prefix: "/departments/PRT", perms: ["printing.records", "printing.bundles", "planning.production", "*"] },
  { prefix: "/departments/SEW", perms: ["sewing.workspace"] },
  { prefix: "/departments/MIL", perms: ["sewing.records", "sewing.bundles", "planning.production", "*"] },
  { prefix: "/departments/BST", perms: ["sewing.records", "sewing.bundles", "planning.production", "*"] },
  { prefix: "/departments/ECO", perms: ["sewing.records", "sewing.bundles", "planning.production", "*"] },
  { prefix: "/departments/PKG", perms: ["packaging.records", "packaging.packages", "planning.production", "*"] },
  { prefix: "/departments/BPK", perms: ["packaging.records", "packaging.packages", "planning.production", "*"] },
  { prefix: "/departments/ECP", perms: ["packaging.records", "packaging.packages", "planning.production", "*"] },
  { prefix: "/payroll/scan", perms: ["payroll.scan", "payroll.manage", "*"] },
  { prefix: "/payroll", perms: ["payroll.view", "payroll.manage", "payroll.pay", "*"] },
  { prefix: "/process-qr", perms: ["payroll.scan", "*"] },
  { prefix: "/finance", perms: ["finance.view", "*"] },
];

function isSuperAdmin(me: ReturnType<typeof useMe>["me"]) {
  return Boolean(
    me?.permissions.includes(SUPER_ADMIN_PERMISSION) ||
    (me?.role ?? "").trim().toLowerCase() === "super admin",
  );
}

function routeMatches(pathname: string, guard: RouteGuard) {
  return guard.exact ? pathname === guard.prefix : pathname === guard.prefix || pathname.startsWith(`${guard.prefix}/`);
}

function hasRouteAccess(me: ReturnType<typeof useMe>["me"], pathname: string) {
  if (isSewingRole(me)) return isSewingWorkspacePath(pathname);
  const guard = ROUTE_GUARDS.find((entry) => routeMatches(pathname, entry));
  if (!guard) return true;
  if (guard.superOnly) return isSuperAdmin(me);
  return !guard.perms || can(me, ...guard.perms);
}

export default function AuthGate({ children }: { children: React.ReactNode }) {
  const router = useRouter();
  const pathname = usePathname() || "/";
  const { me, error, loading, hasToken } = useMe();
  const { t } = useT();
  const redirectRestrictedSewingRole = Boolean(me && isSewingRole(me) && !isSewingWorkspacePath(pathname));

  useEffect(() => {
    // Only redirect once /me definitively rejects the auth cookie.
    if (hasToken === false) router.replace("/login");
    if (error) {
      // Session rejected by the API (expired/invalid) -> clear it and bounce to login.
      api.logout().finally(() => router.replace("/login"));
    }
  }, [hasToken, error, router]);

  useEffect(() => {
    if (redirectRestrictedSewingRole) router.replace(SEWING_WORKSPACE_HOME);
  }, [redirectRestrictedSewingRole, router]);

  // Still detecting the cookie-backed session, or /me hasn't responded yet -> spinner.
  if (hasToken === undefined || (hasToken && (loading || !me))) {
    return <div className="p-6 text-slate-500">{t("common.loading")}</div>;
  }
  if (!hasToken) return null;
  if (redirectRestrictedSewingRole) return null;
  if (!hasRouteAccess(me, pathname)) {
    return <div className="p-6 text-slate-600">{t("auth.accessDenied")}</div>;
  }
  return <>{children}</>;
}
