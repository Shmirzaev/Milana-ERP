"use client";
import { useEffect, useState } from "react";
import { usePathname, useRouter } from "next/navigation";
import { can, useMe } from "@/lib/auth";
import { api } from "@/lib/api";
import { isSewingRole, isSewingWorkspacePath, sewingWorkspaceHome } from "@/lib/access";
import { useT } from "@/lib/i18n";
import { isAbbosbekPricingUser, isAccessoryPricingUser } from "@/lib/priceCalculationRequests";

const SUPER_ADMIN_PERMISSION = "admin.super";

type RouteGuard = {
  prefix: string;
  perms?: string[];
  exact?: boolean;
  superOnly?: boolean;
  audience?: "abbosbekPricing" | "accessoryPricing";
};

const ROUTE_GUARDS: RouteGuard[] = [
  { prefix: "/admin/data", superOnly: true },
  { prefix: "/admin/mcp", superOnly: true },
  { prefix: "/admin/users", perms: ["admin.users", "*"] },
  { prefix: "/admin/departments", perms: ["*"] },
  { prefix: "/admin/audit-logs", perms: ["admin.audit", "*"] },
  { prefix: "/admin/employees", perms: ["hr.employees", "*"] },
  { prefix: "/hr", perms: ["hr.employees", "*"] },
  { prefix: "/customers", perms: ["sales.customers", "sales.orders", "finance.view", "*"] },
  { prefix: "/sales/price-requests", perms: ["sales.orders", "*"] },
  { prefix: "/sales-orders", perms: ["sales.orders", "*"] },
  { prefix: "/order-history", perms: ["sales.orders", "*"] },
  { prefix: "/models", perms: ["modeling.models", "*"] },
  { prefix: "/brands", perms: ["modeling.brands", "*"] },
  { prefix: "/collections", perms: ["modeling.collections", "*"] },
  { prefix: "/planning", perms: ["planning.view", "planning.production", "*"] },
  { prefix: "/forecasting", perms: ["forecasting.view", "*"] },
  { prefix: "/production-orders", perms: ["planning.view", "planning.production", "processes.view", "*"] },
  { prefix: "/traceability", perms: ["traceability.view", "*"] },
  { prefix: "/purchasing/price-calculation", audience: "abbosbekPricing" },
  { prefix: "/purchasing/receiving", perms: ["purchasing.receive", "*"] },
  { prefix: "/purchasing", perms: ["purchasing.view", "purchasing.request", "purchasing.approve", "purchasing.order", "*"] },
  { prefix: "/inventory/master-data", perms: ["storage.items", "storage.suppliers", "*"] },
  { prefix: "/inventory/receive", perms: ["storage.receive", "*"] },
  { prefix: "/inventory/batches", perms: ["storage.items", "*"] },
  { prefix: "/inventory/accessory-pricing", audience: "accessoryPricing" },
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
  { prefix: "/cutting/price-calculation", perms: ["cutting.records", "cutting.bundles", "price_calculation.cutting", "admin.super", "*"] },
  { prefix: "/sewing/flows", perms: ["sewing.workspace", "sewing.flows"] },
  { prefix: "/sewing/daily-report", perms: ["sewing.workspace", "sewing.daily_reports.view"] },
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
  { prefix: "/payroll/reports/order-qr-status", perms: ["payroll.view", "payroll.manage", "payroll.pay", "*"] },
  { prefix: "/payroll/reports/sewing-production", perms: ["payroll.view", "payroll.manage", "payroll.pay", "*"] },
  { prefix: "/payroll/scan", perms: ["payroll.scan", "payroll.manage", "*"] },
  { prefix: "/payroll", perms: ["payroll.view", "payroll.manage", "payroll.pay", "*"] },
  { prefix: "/attendance", perms: ["attendance.view", "attendance.manage", "*"] },
  { prefix: "/usluga", perms: ["usluga.view", "usluga.manage", "usluga.handover", "*"] },
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
  if (guard.audience === "abbosbekPricing") return isAbbosbekPricingUser(me);
  if (guard.audience === "accessoryPricing") return isAccessoryPricingUser(me);
  return !guard.perms || can(me, ...guard.perms);
}

export default function AuthGate({ children }: { children: React.ReactNode }) {
  const router = useRouter();
  const pathname = usePathname() || "/";
  const searchParams = new URLSearchParams(typeof window === "undefined" ? "" : window.location.search);
  const { me, error, loading, hasToken, refresh } = useMe();
  const { t } = useT();
  const [factorySwitchError, setFactorySwitchError] = useState("");
  const redirectRestrictedSewingRole = Boolean(me && isSewingRole(me) && !isSewingWorkspacePath(pathname));
  const restrictedSewingHome = sewingWorkspaceHome(me);
  const factoryHome = isSewingRole(me)
    ? restrictedSewingHome
    : me?.factory_code === "BST"
      ? "/departments/BST"
      : me?.factory_code === "ECO"
        ? "/departments/ECT"
        : "/";
  const redirectNonMilanaHome = Boolean(me && pathname === "/" && me.factory_code !== "MIL");
  const operationalFactory = (() => {
    if (pathname === "/usluga" || pathname.startsWith("/usluga/")) return "ECO";
    const department = pathname.match(/^\/departments\/(CUT|PRT|SEW|MIL|PKG|BST|BPK|ECT|ECO|ECP)(?:\/|$)/)?.[1];
    if (department) {
      if (department === "BST" || department === "BPK") return "BST";
      if (department === "ECT" || department === "ECO" || department === "ECP") return "ECO";
      return "MIL";
    }
    if (pathname.startsWith("/sewing/") || pathname.startsWith("/bundles/scan/sewing")) {
      return (searchParams.get("factory") || me?.factory_code || "MIL").toUpperCase();
    }
    if (pathname === "/packages/scan") return null;
    if (pathname === "/packages" || pathname.startsWith("/packaging/")) {
      const code = (searchParams.get("packaging_department") || "PKG").toUpperCase();
      return code === "BPK" ? "BST" : code === "ECP" ? "ECO" : "MIL";
    }
    if (pathname === "/bundles" || pathname.startsWith("/cutting-") || pathname.startsWith("/bundles/scan/cutting")) {
      return (searchParams.get("cutting_department") || "CUT").toUpperCase() === "ECT" ? "ECO" : "MIL";
    }
    if (pathname.startsWith("/bundles/scan/printing")) return "MIL";
    return null;
  })();
  const canSwitchOperationalFactory = Boolean(
    me
    && operationalFactory
    && operationalFactory !== me.factory_code
    && me.available_factories.includes(operationalFactory as "MIL" | "BST" | "ECO"),
  );

  useEffect(() => {
    if (!canSwitchOperationalFactory || !operationalFactory) return;
    let cancelled = false;
    setFactorySwitchError("");
    api.post("/api/auth/switch-factory", { factory_code: operationalFactory })
      .then(() => refresh())
      .catch((switchError: unknown) => {
        if (!cancelled) setFactorySwitchError(String((switchError as Error)?.message || switchError));
      });
    return () => {
      cancelled = true;
    };
  }, [canSwitchOperationalFactory, operationalFactory, refresh]);

  useEffect(() => {
    // Only redirect once /me definitively rejects the auth cookie.
    if (hasToken === false) router.replace("/login");
    if (error) {
      // Session rejected by the API (expired/invalid) -> clear it and bounce to login.
      api.logout().finally(() => router.replace("/login"));
    }
  }, [hasToken, error, router]);

  useEffect(() => {
    if (redirectRestrictedSewingRole) router.replace(restrictedSewingHome);
  }, [redirectRestrictedSewingRole, restrictedSewingHome, router]);

  useEffect(() => {
    if (redirectNonMilanaHome) router.replace(factoryHome);
  }, [factoryHome, redirectNonMilanaHome, router]);

  // Still detecting the cookie-backed session, or /me hasn't responded yet -> spinner.
  if (hasToken === undefined || (hasToken && (loading || !me))) {
    return <div className="p-6 text-slate-500">{t("common.loading")}</div>;
  }
  if (!hasToken) return null;
  if (redirectRestrictedSewingRole) return null;
  if (redirectNonMilanaHome) return null;
  if (canSwitchOperationalFactory && !factorySwitchError) {
    return <div className="p-6 text-slate-500">{t("common.loading")}</div>;
  }
  if (!hasRouteAccess(me, pathname) || (operationalFactory && operationalFactory !== me?.factory_code)) {
    return <div className="p-6 text-slate-600">{t("auth.accessDenied")}</div>;
  }
  return <>{children}</>;
}
