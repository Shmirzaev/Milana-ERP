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
  Clock3,
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
import { isAbbosbekPricingUser, isAccessoryPricingUser } from "@/lib/priceCalculationRequests";
import BrandLogo from "@/components/BrandLogo";

type NavAudience = "abbosbekPricing" | "accessoryPricing";
type NavItem = { href: string; labelKey: string; perms?: string[]; superOnly?: boolean; audience?: NavAudience; icon: ComponentType<{ className?: string }> };
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
    titleKey: "section.hr",
    items: [
      { href: "/hr", labelKey: "nav.hrDashboard", perms: ["hr.employees", "*"], icon: Users },
    ],
  },
  {
    titleKey: "section.sales",
    items: [
      { href: "/sales/price-requests", labelKey: "nav.salesPriceRequests", perms: ["sales.orders"], icon: Calculator },
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
      { href: "/purchasing/price-calculation", labelKey: "nav.purchasingPriceRequests", audience: "abbosbekPricing", icon: Calculator },
      { href: "/purchasing", labelKey: "nav.purchaseRequests", perms: ["purchasing.view", "purchasing.request", "purchasing.approve", "purchasing.order", "*"], icon: ShoppingBag },
      { href: "/purchasing/receiving", labelKey: "nav.purchaseReceiving", perms: ["purchasing.receive", "*"], icon: PackageCheck },
    ],
  },
  {
    titleKey: "section.inventory",
    items: [
      { href: "/inventory/accessory-pricing", labelKey: "nav.accessoryPriceRequests", audience: "accessoryPricing", icon: Calculator },
      { href: "/inventory?group=materials", labelKey: "nav.materialInventory", perms: ["storage.items", "storage.receive"], icon: Warehouse },
      { href: "/inventory?group=accessories", labelKey: "nav.accessoryInventory", perms: ["storage.items", "storage.receive"], icon: PackageSearch },
      { href: "/inventory/master-data", labelKey: "nav.masterData", perms: ["storage.items", "storage.suppliers", "*"], icon: Database },
      { href: "/inventory/receive?group=materials", labelKey: "nav.receiveFabric", perms: ["storage.receive"], icon: PackageCheck },
      { href: "/inventory/receive?group=accessories", labelKey: "nav.receiveAccessories", perms: ["storage.receive"], icon: PackageCheck },
      { href: "/inventory/batches", labelKey: "nav.batches", perms: ["storage.items"], icon: Boxes },
    ],
  },
  // Per-department production sections — each replaces the old "Production" bucket.
  {
    titleKey: "section.cutting",
    items: [
      { href: "/cutting/price-calculation", labelKey: "nav.cuttingPriceRequests", perms: ["cutting.records", "cutting.bundles", "admin.super"], icon: Calculator },
      { href: "/departments/CUT", labelKey: "nav.cuttingFloor", perms: ["cutting.records", "cutting.bundles", "planning.production"], icon: Scissors },
      { href: "/cutting-passports?cutting_department=CUT", labelKey: "nav.cuttingPassports", perms: ["cutting.records", "cutting.bundles", "planning.production"], icon: FileText },
      { href: "/cutting-inventory?cutting_department=CUT", labelKey: "nav.bundleInventory", perms: ["cutting.records", "cutting.bundles", "planning.production"], icon: Boxes },
      { href: "/bundles?cutting_department=CUT", labelKey: "nav.bundles", perms: ["cutting.bundles", "cutting.records", "planning.production"], icon: PackageSearch },
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
      { href: "/sewing/flows?factory=MIL", labelKey: "nav.sewingFlows", perms: ["sewing.workspace", "sewing.flows"], icon: Layers3 },
      { href: "/sewing/daily-report?factory=MIL", labelKey: "nav.sewingDailyReport", perms: ["sewing.workspace", "sewing.daily_reports.view"], icon: ClipboardList },
      { href: "/departments/SEW", labelKey: "nav.sewingFloor", perms: ["sewing.workspace"], icon: Shirt },
      { href: "/departments/MIL", labelKey: "nav.milanaSewing", perms: ["sewing.records", "sewing.bundles", "planning.production"], icon: Factory },
      { href: "/bundles/scan/sewing?factory=MIL", labelKey: "nav.scanBundle", perms: ["sewing.bundles", "sewing.records"], icon: QrCode },
    ],
  },
  {
    titleKey: "section.besttexTextile",
    items: [
      { href: "/departments/BST", labelKey: "nav.besttexSewing", perms: ["sewing.records", "sewing.bundles", "planning.production"], icon: Factory },
      { href: "/sewing/flows?factory=BST", labelKey: "nav.sewingFlows", perms: ["sewing.workspace", "sewing.flows"], icon: Layers3 },
      { href: "/sewing/daily-report?factory=BST", labelKey: "nav.sewingDailyReport", perms: ["sewing.workspace", "sewing.daily_reports.view"], icon: ClipboardList },
      { href: "/bundles/scan/sewing?factory=BST", labelKey: "nav.scanBundle", perms: ["sewing.bundles", "sewing.records"], icon: QrCode },
      { href: "/departments/BPK", labelKey: "nav.besttexPackaging", perms: ["packaging.records", "packaging.packages", "planning.production"], icon: PackageCheck },
      { href: "/packages?packaging_department=BPK", labelKey: "nav.packages", perms: ["packaging.packages", "packaging.records"], icon: Boxes },
      { href: "/packaging/queue?packaging_department=BPK", labelKey: "nav.packingQueue", perms: ["packaging.records", "planning.production"], icon: PackageSearch },
      { href: "/packaging/receive?packaging_department=BPK", labelKey: "nav.receiveFromSewing", perms: ["packaging.records", "planning.production"], icon: QrCode },
    ],
  },
  {
    titleKey: "section.ecoCottonCutting",
    items: [
      { href: "/departments/ECT", labelKey: "nav.ecoCottonCutting", perms: ["cutting.records", "cutting.bundles", "planning.production"], icon: Scissors },
      { href: "/cutting-passports?cutting_department=ECT", labelKey: "nav.cuttingPassports", perms: ["cutting.records", "cutting.bundles", "planning.production"], icon: FileText },
      { href: "/cutting-inventory?cutting_department=ECT", labelKey: "nav.bundleInventory", perms: ["cutting.records", "cutting.bundles", "planning.production"], icon: Boxes },
      { href: "/bundles?cutting_department=ECT", labelKey: "nav.bundles", perms: ["cutting.bundles", "cutting.records", "planning.production"], icon: PackageSearch },
      { href: "/bundles/scan/cutting?cutting_department=ECT", labelKey: "nav.scanBundle", perms: ["cutting.bundles", "cutting.records"], icon: QrCode },
    ],
  },
  {
    titleKey: "section.ecoCottonSewing",
    items: [
      { href: "/departments/ECO", labelKey: "nav.ecoCottonSewing", perms: ["sewing.records", "sewing.bundles", "planning.production"], icon: Factory },
      { href: "/sewing/flows?factory=ECO", labelKey: "nav.sewingFlows", perms: ["sewing.workspace", "sewing.flows"], icon: Layers3 },
      { href: "/sewing/daily-report?factory=ECO", labelKey: "nav.sewingDailyReport", perms: ["sewing.workspace", "sewing.daily_reports.view"], icon: ClipboardList },
      { href: "/bundles/scan/sewing?factory=ECO", labelKey: "nav.scanBundle", perms: ["sewing.bundles", "sewing.records"], icon: QrCode },
    ],
  },
  {
    titleKey: "section.ecoCottonPackaging",
    items: [
      { href: "/departments/ECP", labelKey: "nav.ecoCottonPackaging", perms: ["packaging.records", "packaging.packages", "planning.production"], icon: PackageCheck },
      { href: "/packages?packaging_department=ECP", labelKey: "nav.packages", perms: ["packaging.packages", "packaging.records"], icon: Boxes },
      { href: "/packaging/queue?packaging_department=ECP", labelKey: "nav.packingQueue", perms: ["packaging.records", "planning.production"], icon: PackageSearch },
      { href: "/packaging/receive?packaging_department=ECP", labelKey: "nav.receiveFromSewing", perms: ["packaging.records", "planning.production"], icon: QrCode },
    ],
  },
  {
    titleKey: "section.ecoCottonTracking",
    items: [
      { href: "/processes?factory=ECO", labelKey: "nav.processes", icon: ClipboardList },
    ],
  },
  {
    titleKey: "section.usluga",
    items: [
      { href: "/usluga", labelKey: "nav.uslugaPlanning", perms: ["usluga.view", "usluga.manage", "usluga.handover", "*"], icon: ClipboardList },
      { href: "/usluga/models", labelKey: "nav.uslugaModels", perms: ["usluga.view", "usluga.manage", "*"], icon: Shirt },
    ],
  },
  {
    titleKey: "section.packaging",
    items: [
      { href: "/departments/PKG", labelKey: "nav.packagingFloor", perms: ["packaging.records", "packaging.packages", "planning.production"], icon: PackageCheck },
      { href: "/packages?packaging_department=PKG", labelKey: "nav.packages", perms: ["packaging.packages", "packaging.records"], icon: Boxes },
      { href: "/packaging/queue?packaging_department=PKG", labelKey: "nav.packingQueue", perms: ["packaging.records", "planning.production"], icon: PackageSearch },
      { href: "/packaging/receive?packaging_department=PKG", labelKey: "nav.receiveFromSewing", perms: ["packaging.records", "planning.production"], icon: QrCode },
    ],
  },
  {
    titleKey: "section.payroll",
    items: [
      { href: "/payroll", labelKey: "nav.payrollSummary", perms: ["payroll.view", "payroll.manage", "payroll.pay"], icon: ClipboardList },
      { href: "/payroll/reports/sewing-production", labelKey: "nav.sewingProductionReport", perms: ["payroll.view", "payroll.manage", "payroll.pay", "*"], icon: FileText },
      { href: "/payroll/reports/order-qr-status", labelKey: "nav.orderQrStatus", perms: ["payroll.view", "payroll.manage", "payroll.pay", "*"], icon: FileSearch },
      { href: "/process-qr", labelKey: "nav.processQr", perms: ["payroll.scan", "*"], icon: QrCode },
      { href: "/payroll/scan", labelKey: "nav.payrollScan", perms: ["payroll.scan", "*"], icon: Calculator },
      { href: "/payroll/qr-control", labelKey: "nav.payrollQrControl", perms: ["payroll.view", "payroll.manage", "*"], icon: FileSearch },
    ],
  },
  {
    titleKey: "section.attendance",
    items: [
      { href: "/attendance", labelKey: "nav.attendance", perms: ["attendance.view", "attendance.manage", "*"], icon: Clock3 },
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
      { href: "/finance/price-calculation", labelKey: "nav.priceCalculation", perms: ["finance.view"], icon: Calculator },
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
                    className={`flex min-h-10 min-w-0 items-center rounded-md text-[13px] transition ${collapsed ? "h-10 justify-center px-0" : "gap-2 px-3 py-2"} ${
                      active
                        ? "bg-[#14110b] text-[#fdfcf8] shadow-sm"
                        : "text-[#56503f] hover:bg-[#f1efe8] hover:text-[#14110b]"
                    }`}
                    title={t(it.labelKey)}
                  >
                    <ItemIcon className="h-4 w-4 shrink-0" />
                    <span className={collapsed ? "sr-only" : "break-words leading-tight"}>{t(it.labelKey)}</span>
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
      SECTIONS.filter((sec) => {
        const factory = me?.factory_code || "MIL";
        if (factory === "BST") return sec.titleKey === "section.besttexTextile" || sec.titleKey === "section.hr";
        const ecoSections = new Set([
          "section.ecoCottonCutting",
          "section.ecoCottonSewing",
          "section.ecoCottonPackaging",
          "section.ecoCottonTracking",
          "section.usluga",
          "section.attendance",
        ]);
        if (factory === "ECO") return sec.titleKey === "section.hr" || ecoSections.has(sec.titleKey);
        return sec.titleKey === "section.hr"
          || sec.titleKey === "section.attendance"
          || (sec.titleKey !== "section.besttexTextile" && !ecoSections.has(sec.titleKey));
      }).map((sec) => ({
        ...sec,
        items: sec.items.filter((i) => {
          if (isSewingRole(me) && !isSewingWorkspaceNavItem(i.href)) return false;
          if (i.superOnly) return isSuperAdmin(me);
          if (i.audience === "abbosbekPricing" && !isAbbosbekPricingUser(me)) return false;
          if (i.audience === "accessoryPricing" && !isAccessoryPricingUser(me)) return false;
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
    const itemParams = new URLSearchParams(href.split("?")[1] || "");
    const itemGroup = itemParams.get("group") || "";
    const itemCuttingDepartment = itemParams.get("cutting_department") || "";
    const itemFactory = itemParams.get("factory") || "";
    const itemPackagingDepartment = itemParams.get("packaging_department") || "";
    const currentFactory = searchParams.get("factory") || me?.factory_code || "MIL";
    const currentCuttingDepartment = searchParams.get("cutting_department") || "CUT";
    const currentPackagingDepartment = searchParams.get("packaging_department") || "PKG";
    const bundlesScanMismatch = basePath === "/bundles" && pathname.startsWith("/bundles/scan");
    const packagesScanMismatch = basePath === "/packages" && pathname.startsWith("/packages/scan");
    const inventoryGroupMismatch = basePath === "/inventory" && (pathname !== "/inventory" || itemGroup !== inventoryGroup);
    const inventoryReceiveGroupMismatch = basePath === "/inventory/receive" && itemGroup !== inventoryGroup;
    const cuttingDepartmentMismatch = ["/cutting-passports", "/cutting-inventory", "/bundles"].includes(basePath)
      && itemCuttingDepartment !== currentCuttingDepartment;
    const sewingFactoryMismatch = ["/sewing/flows", "/sewing/daily-report", "/bundles/scan/sewing"].includes(basePath)
      && itemFactory !== currentFactory;
    const packagingDepartmentMismatch = ["/packages", "/packaging/queue", "/packaging/receive"].includes(basePath)
      && itemPackagingDepartment !== currentPackagingDepartment;
    const purchasingChildMismatch = basePath === "/purchasing" && pathname.startsWith("/purchasing/");
    const planningChildMismatch = basePath === "/planning" && pathname.startsWith("/planning/");
    const payrollChildMismatch = basePath === "/payroll" && pathname.startsWith("/payroll/");
    const uslugaChildMismatch = basePath === "/usluga" && pathname.startsWith("/usluga/");
    const financeChildMismatch = basePath === "/finance" && pathname.startsWith("/finance/");
    return (
      !bundlesScanMismatch &&
      !packagesScanMismatch &&
      !inventoryGroupMismatch &&
      !inventoryReceiveGroupMismatch &&
      !cuttingDepartmentMismatch &&
      !sewingFactoryMismatch &&
      !packagingDepartmentMismatch &&
      !purchasingChildMismatch &&
      !planningChildMismatch &&
      !payrollChildMismatch &&
      !uslugaChildMismatch &&
      !financeChildMismatch &&
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
      <div className="sticky top-0 z-40 flex h-14 items-center justify-between border-b border-[#e3dfd3] bg-[#fdfcf8] px-3 text-[#2c2920] min-[1440px]:hidden">
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
        <div className="fixed inset-0 z-50 min-[1440px]:hidden" role="dialog" aria-modal="true" aria-label={t("nav.menu")}>
          <button
            type="button"
            className="absolute inset-0 h-full w-full cursor-default bg-[#14110b]/40"
            onClick={() => setMobileOpen(false)}
            aria-label={t("nav.closeMenu")}
          />
          <aside
            id="mobile-navigation"
            className="absolute left-0 top-0 flex h-[100dvh] w-[88vw] max-w-[360px] flex-col border-r border-[#e3dfd3] bg-[#fdfcf8] pb-[env(safe-area-inset-bottom)] text-[#2c2920] shadow-lg sm:max-w-[460px]"
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
        className={`sticky top-0 z-30 hidden h-screen shrink-0 flex-col overflow-hidden border-r border-[#e3dfd3] bg-[#fdfcf8] text-[#2c2920] transition-[width] duration-150 min-[1440px]:flex ${desktopCollapsed ? "w-[72px]" : "w-60"}`}
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
