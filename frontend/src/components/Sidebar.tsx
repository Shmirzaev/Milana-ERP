"use client";
import { useEffect, useMemo, useState } from "react";
import type { ComponentType } from "react";
import Link from "next/link";
import { usePathname, useSearchParams } from "next/navigation";
import {
  BarChart3,
  Bot,
  Boxes,
  Building2,
  Calculator,
  ClipboardList,
  Coins,
  Database,
  Factory,
  FileSearch,
  FileText,
  Layers3,
  LineChart,
  Menu,
  PackageCheck,
  PackageSearch,
  Palette,
  PanelLeftClose,
  PanelLeftOpen,
  QrCode,
  Scissors,
  Settings,
  Shirt,
  ShoppingBag,
  ShoppingCart,
  ShieldCheck,
  Truck,
  UserRoundCog,
  Users,
  Warehouse,
  X,
} from "lucide-react";
import { useMe, can } from "@/lib/auth";
import { isSewingRole, isSewingWorkspaceNavItem } from "@/lib/access";
import { useT } from "@/lib/i18n";
import BrandLogo from "@/components/BrandLogo";

type NavItem = { href: string; labelKey: string; perms?: string[]; superOnly?: boolean; icon: ComponentType<{ className?: string }> };
type Section = { titleKey: string; items: NavItem[] };

const SUPER_ADMIN_PERMISSION = "admin.super";
const SIDEBAR_COLLAPSED_STORAGE_KEY = "erp_sidebar_collapsed";

function isSuperAdmin(me: ReturnType<typeof useMe>["me"]) {
  return Boolean(
    me?.permissions.includes(SUPER_ADMIN_PERMISSION) ||
    (me?.role ?? "").trim().toLowerCase() === "super admin",
  );
}

const SECTIONS: Section[] = [
  {
    titleKey: "section.overview",
    items: [
      { href: "/", labelKey: "nav.dashboard", icon: BarChart3 },
      { href: "/processes", labelKey: "nav.processes", icon: ClipboardList },
      { href: "/traceability", labelKey: "nav.traceability", perms: ["traceability.view", "*"], icon: FileSearch },
    ],
  },
  {
    titleKey: "section.sales",
    items: [
      { href: "/sales-orders", labelKey: "nav.salesOrders", perms: ["sales.orders"], icon: ShoppingCart },
      { href: "/order-history", labelKey: "nav.orderHistory", perms: ["sales.orders"], icon: ClipboardList },
      { href: "/customers", labelKey: "nav.customers", perms: ["sales.customers"], icon: Users },
    ],
  },
  {
    titleKey: "section.plm",
    items: [
      { href: "/models", labelKey: "nav.models", perms: ["modeling.models"], icon: Shirt },
      { href: "/brands", labelKey: "nav.brands", perms: ["modeling.brands"], icon: Palette },
      { href: "/collections", labelKey: "nav.collections", perms: ["modeling.collections"], icon: Layers3 },
    ],
  },
  {
    titleKey: "section.planning",
    items: [
      { href: "/planning", labelKey: "nav.planningDash", perms: ["planning.view", "planning.production"], icon: ClipboardList },
      { href: "/planning/branded-stock", labelKey: "nav.brandedStockOrders", perms: ["planning.production"], icon: Boxes },
      { href: "/forecasting", labelKey: "nav.forecasting", perms: ["forecasting.view", "*"], icon: LineChart },
      { href: "/production-orders", labelKey: "nav.productionOrders", perms: ["planning.production"], icon: Factory },
    ],
  },
  {
    titleKey: "section.purchasing",
    items: [
      { href: "/purchasing", labelKey: "nav.purchaseRequests", perms: ["purchasing.view", "purchasing.request", "purchasing.approve", "purchasing.order", "*"], icon: ShoppingBag },
      { href: "/purchasing/receiving", labelKey: "nav.purchaseReceiving", perms: ["purchasing.receive", "*"], icon: PackageCheck },
    ],
  },
  {
    titleKey: "section.inventory",
    items: [
      { href: "/inventory?group=materials", labelKey: "nav.materialInventory", perms: ["storage.items", "storage.receive"], icon: Warehouse },
      { href: "/inventory?group=accessories", labelKey: "nav.accessoryInventory", perms: ["storage.items", "storage.receive"], icon: PackageSearch },
      { href: "/inventory/master-data", labelKey: "nav.masterData", perms: ["storage.items", "storage.suppliers", "*"], icon: Database },
      { href: "/inventory/receive", labelKey: "nav.receive", perms: ["storage.receive"], icon: PackageCheck },
      { href: "/inventory/batches", labelKey: "nav.batches", perms: ["storage.items"], icon: Boxes },
    ],
  },
  // Per-department production sections — each replaces the old "Production" bucket.
  {
    titleKey: "section.cutting",
    items: [
      { href: "/departments/CUT", labelKey: "nav.cuttingFloor", perms: ["cutting.records", "cutting.bundles", "planning.production"], icon: Scissors },
      { href: "/cutting-passports", labelKey: "nav.cuttingPassports", perms: ["cutting.records", "cutting.bundles", "planning.production"], icon: FileText },
      { href: "/cutting-inventory", labelKey: "nav.bundleInventory", perms: ["cutting.records", "cutting.bundles", "planning.production"], icon: Boxes },
      { href: "/bundles", labelKey: "nav.bundles", perms: ["cutting.bundles", "cutting.records", "planning.production"], icon: PackageSearch },
      { href: "/bundles/scan/cutting", labelKey: "nav.scanBundle", perms: ["cutting.bundles", "cutting.records"], icon: QrCode },
    ],
  },
  {
    titleKey: "section.printing",
    items: [
      { href: "/departments/PRT", labelKey: "nav.printingFloor", perms: ["printing.records", "printing.bundles", "planning.production"], icon: Palette },
      { href: "/bundles/scan/printing", labelKey: "nav.scanBundle", perms: ["printing.bundles", "printing.records"], icon: QrCode },
    ],
  },
  {
    titleKey: "section.sewing",
    items: [
      { href: "/sewing/flows", labelKey: "nav.sewingFlows", perms: ["sewing.workspace"], icon: Layers3 },
      { href: "/sewing/daily-report", labelKey: "nav.sewingDailyReport", perms: ["sewing.workspace"], icon: ClipboardList },
      { href: "/departments/SEW", labelKey: "nav.sewingFloor", perms: ["sewing.workspace"], icon: Shirt },
      { href: "/departments/MIL", labelKey: "nav.milanaSewing", perms: ["sewing.records", "sewing.bundles", "planning.production"], icon: Factory },
      { href: "/bundles/scan/sewing", labelKey: "nav.scanBundle", perms: ["sewing.bundles", "sewing.records"], icon: QrCode },
    ],
  },
  {
    titleKey: "section.besttexTextile",
    items: [
      { href: "/departments/BST", labelKey: "nav.besttexSewing", perms: ["sewing.records", "sewing.bundles", "planning.production"], icon: Factory },
      { href: "/departments/BPK", labelKey: "nav.besttexPackaging", perms: ["packaging.records", "packaging.packages", "planning.production"], icon: PackageCheck },
    ],
  },
  {
    titleKey: "section.ecoCotton",
    items: [
      { href: "/departments/ECT", labelKey: "nav.ecoCottonCutting", perms: ["cutting.records", "cutting.bundles", "planning.production"], icon: Scissors },
      { href: "/cutting-passports", labelKey: "nav.cuttingPassports", perms: ["cutting.records", "cutting.bundles", "planning.production"], icon: FileText },
      { href: "/cutting-inventory", labelKey: "nav.bundleInventory", perms: ["cutting.records", "cutting.bundles", "planning.production"], icon: Boxes },
      { href: "/bundles", labelKey: "nav.bundles", perms: ["cutting.bundles", "cutting.records", "planning.production"], icon: PackageSearch },
      { href: "/bundles/scan/cutting", labelKey: "nav.scanBundle", perms: ["cutting.bundles", "cutting.records"], icon: QrCode },
      { href: "/departments/ECO", labelKey: "nav.ecoCottonSewing", perms: ["sewing.records", "sewing.bundles", "planning.production"], icon: Factory },
      { href: "/departments/ECP", labelKey: "nav.ecoCottonPackaging", perms: ["packaging.records", "packaging.packages", "planning.production"], icon: PackageCheck },
    ],
  },
  {
    titleKey: "section.packaging",
    items: [
      { href: "/departments/PKG", labelKey: "nav.packagingFloor", perms: ["packaging.records", "packaging.packages", "planning.production"], icon: PackageCheck },
      { href: "/packages", labelKey: "nav.packages", perms: ["packaging.packages", "packaging.records"], icon: Boxes },
      { href: "/packaging/queue", labelKey: "nav.packingQueue", perms: ["packaging.records", "planning.production"], icon: PackageSearch },
      { href: "/packaging/receive", labelKey: "nav.receiveFromSewing", perms: ["packaging.records", "planning.production"], icon: QrCode },
    ],
  },
  {
    titleKey: "section.payroll",
    items: [
      { href: "/payroll", labelKey: "nav.payrollSummary", perms: ["payroll.view", "payroll.manage", "payroll.pay"], icon: ClipboardList },
      { href: "/process-qr", labelKey: "nav.processQr", perms: ["payroll.scan", "*"], icon: QrCode },
      { href: "/payroll/scan", labelKey: "nav.payrollScan", perms: ["payroll.scan", "*"], icon: Calculator },
      { href: "/payroll/qr-control", labelKey: "nav.payrollQrControl", perms: ["payroll.view", "payroll.manage", "*"], icon: FileSearch },
    ],
  },
  {
    titleKey: "section.storage",
    items: [
      { href: "/departments/FGS", labelKey: "nav.finishedGoods", icon: Building2 },
      { href: "/warehouse-stock", labelKey: "nav.warehouseStock", perms: ["storage.packages", "storage.shipment"], icon: PackageSearch },
      { href: "/packages/scan", labelKey: "nav.scanPackage", perms: ["storage.packages"], icon: QrCode },
      { href: "/warehouse-map", labelKey: "nav.warehouseMap", perms: ["storage.packages", "storage.shipment"], icon: Warehouse },
      { href: "/shipments", labelKey: "nav.shipments", perms: ["storage.shipment"], icon: Truck },
    ],
  },
  {
    titleKey: "section.waste",
    items: [
      { href: "/waste", labelKey: "nav.wasteDash", icon: ClipboardList },
    ],
  },
  {
    titleKey: "section.finance",
    items: [
      { href: "/finance", labelKey: "nav.financeDash", perms: ["finance.view"], icon: Coins },
    ],
  },
  {
    titleKey: "section.admin",
    items: [
      { href: "/admin/users", labelKey: "nav.users", perms: ["admin.users"], icon: UserRoundCog },
      { href: "/admin/departments", labelKey: "nav.departments", perms: ["*"], icon: Building2 },
      { href: "/admin/audit-logs", labelKey: "nav.auditLogs", perms: ["admin.audit"], icon: Settings },
      { href: "/admin/employees", labelKey: "nav.employees", perms: ["hr.employees"], icon: Users },
      { href: "/admin/mcp", labelKey: "nav.mcp", superOnly: true, icon: Bot },
      { href: "/admin/data", labelKey: "nav.superData", superOnly: true, icon: ShieldCheck },
    ],
  },
];

function SidebarNavSections({
  sections,
  t,
  isActive,
  onNavigate,
  mobile = false,
  collapsed = false,
}: {
  sections: Section[];
  t: (key: string) => string;
  isActive: (href: string) => boolean;
  onNavigate?: () => void;
  mobile?: boolean;
  collapsed?: boolean;
}) {
  return (
    <>
      {sections.map((sec) => (
        <div key={sec.titleKey} className={mobile ? "mb-5" : "mb-4"}>
          <div className={collapsed ? "sr-only" : "mb-2 px-2 text-[10px] font-bold uppercase tracking-wider text-[#8a8472]"}>{t(sec.titleKey)}</div>
          <ul className={mobile ? "grid grid-cols-1 gap-1" : "space-y-0.5"}>
            {sec.items.map((it) => {
              const active = isActive(it.href);
              const ItemIcon = it.icon;
              return (
                <li key={`${sec.titleKey}-${it.href}`}>
                  <Link
                    href={it.href}
                    onClick={onNavigate}
                    className={`flex h-10 min-w-0 items-center rounded-md text-[13px] transition ${collapsed ? "justify-center px-0" : "gap-2 px-3"} ${
                      active
                        ? "bg-[#14110b] text-[#fdfcf8] shadow-sm"
                        : "text-[#56503f] hover:bg-[#f1efe8] hover:text-[#14110b]"
                    }`}
                    title={t(it.labelKey)}
                  >
                    <ItemIcon className="h-4 w-4 shrink-0" />
                    <span className={collapsed ? "sr-only" : "truncate"}>{t(it.labelKey)}</span>
                  </Link>
                </li>
              );
            })}
          </ul>
        </div>
      ))}
    </>
  );
}

export default function Sidebar() {
  const { me } = useMe();
  const { t } = useT();
  const pathname = usePathname() || "";
  const searchParams = useSearchParams();
  const searchKey = searchParams.toString();
  const inventoryGroup = searchParams.get("group") || "materials";
  const [mobileOpen, setMobileOpen] = useState(false);
  const [desktopCollapsed, setDesktopCollapsed] = useState(false);
  const visibleSections = useMemo(
    () =>
      SECTIONS.map((sec) => ({
        ...sec,
        items: sec.items.filter((i) => {
          if (isSewingRole(me) && !isSewingWorkspaceNavItem(i.href)) return false;
          if (i.superOnly) return isSuperAdmin(me);
          return !i.perms || can(me, ...i.perms);
        }),
      })).filter((sec) => sec.items.length > 0),
    [me],
  );

  useEffect(() => {
    setMobileOpen(false);
  }, [pathname, searchKey]);

  useEffect(() => {
    try {
      setDesktopCollapsed(window.localStorage.getItem(SIDEBAR_COLLAPSED_STORAGE_KEY) === "true");
    } catch {
      setDesktopCollapsed(false);
    }
  }, []);

  useEffect(() => {
    if (!mobileOpen) return;
    const onKey = (event: KeyboardEvent) => {
      if (event.key === "Escape") setMobileOpen(false);
    };
    window.addEventListener("keydown", onKey);
    document.body.style.overflow = "hidden";
    return () => {
      window.removeEventListener("keydown", onKey);
      document.body.style.overflow = "";
    };
  }, [mobileOpen]);

  function isActive(href: string) {
    const basePath = href.split("?")[0];
    const itemGroup = new URLSearchParams(href.split("?")[1] || "").get("group") || "";
    const bundlesScanMismatch = basePath === "/bundles" && pathname.startsWith("/bundles/scan");
    const packagesScanMismatch = basePath === "/packages" && pathname.startsWith("/packages/scan");
    const inventoryGroupMismatch = basePath === "/inventory" && (pathname !== "/inventory" || itemGroup !== inventoryGroup);
    const purchasingChildMismatch = basePath === "/purchasing" && pathname.startsWith("/purchasing/");
    const planningChildMismatch = basePath === "/planning" && pathname.startsWith("/planning/");
    return (
      !bundlesScanMismatch &&
      !packagesScanMismatch &&
      !inventoryGroupMismatch &&
      !purchasingChildMismatch &&
      !planningChildMismatch &&
      (pathname === basePath || (basePath !== "/" && pathname?.startsWith(basePath)))
    );
  }

  function toggleDesktopSidebar() {
    setDesktopCollapsed((current) => {
      const next = !current;
      try {
        window.localStorage.setItem(SIDEBAR_COLLAPSED_STORAGE_KEY, String(next));
      } catch {
        // The sidebar still works when browser storage is unavailable.
      }
      return next;
    });
  }

  return (
    <>
      <div className="sticky top-0 z-40 flex h-14 items-center justify-between border-b border-[#e3dfd3] bg-[#fdfcf8] px-3 text-[#2c2920] lg:hidden">
        <BrandLogo alt={t("app.name")} className="h-9 w-auto max-w-[160px]" />
        <button
          type="button"
          className="btn h-9 px-3"
          onClick={() => setMobileOpen(true)}
          aria-expanded={mobileOpen}
          aria-controls="mobile-navigation"
        >
          <Menu className="h-4 w-4" />
          {t("nav.menu")}
        </button>
      </div>

      {mobileOpen && (
        <div className="fixed inset-0 z-50 lg:hidden" role="dialog" aria-modal="true" aria-label={t("nav.menu")}>
          <button
            type="button"
            className="absolute inset-0 h-full w-full cursor-default bg-[#14110b]/40"
            onClick={() => setMobileOpen(false)}
            aria-label={t("nav.closeMenu")}
          />
          <aside
            id="mobile-navigation"
            className="absolute left-0 top-0 flex h-full w-[88vw] max-w-[360px] flex-col border-r border-[#e3dfd3] bg-[#fdfcf8] text-[#2c2920] shadow-lg sm:max-w-[460px]"
          >
            <div className="flex h-16 shrink-0 items-center justify-between border-b border-[#ecebe3] px-4">
              <BrandLogo alt={t("app.name")} className="h-10 w-auto max-w-[180px]" />
              <button type="button" className="icon-btn" onClick={() => setMobileOpen(false)} aria-label={t("nav.closeMenu")}>
                <X />
              </button>
            </div>
            <nav className="flex-1 overflow-y-auto px-3 py-4">
              <SidebarNavSections
                sections={visibleSections}
                t={t}
                isActive={isActive}
                onNavigate={() => setMobileOpen(false)}
                mobile
              />
            </nav>
          </aside>
        </div>
      )}

      <aside
        className={`sticky top-0 z-30 hidden h-screen shrink-0 flex-col overflow-hidden border-r border-[#e3dfd3] bg-[#fdfcf8] text-[#2c2920] transition-[width] duration-150 lg:flex ${desktopCollapsed ? "w-[72px]" : "w-60"}`}
        data-collapsed={desktopCollapsed}
      >
        <div className={`flex h-28 shrink-0 border-b border-[#ecebe3] ${desktopCollapsed ? "flex-col items-center justify-center gap-2 px-2" : "items-center gap-2 px-3"}`}>
          <BrandLogo
            alt={t("app.name")}
            markOnly={desktopCollapsed}
            className={desktopCollapsed ? "h-12 w-12 object-center" : "h-16 min-w-0 flex-1"}
          />
          <button
            type="button"
            className="icon-btn h-8 w-8 shrink-0"
            onClick={toggleDesktopSidebar}
            title={desktopCollapsed ? t("nav.expandMenu") : t("nav.collapseMenu")}
            aria-label={desktopCollapsed ? t("nav.expandMenu") : t("nav.collapseMenu")}
            aria-expanded={!desktopCollapsed}
          >
            {desktopCollapsed ? <PanelLeftOpen /> : <PanelLeftClose />}
          </button>
        </div>
        <nav className="flex-1 overflow-y-auto px-2 py-4">
          <SidebarNavSections sections={visibleSections} t={t} isActive={isActive} collapsed={desktopCollapsed} />
        </nav>
      </aside>
    </>
  );
}
