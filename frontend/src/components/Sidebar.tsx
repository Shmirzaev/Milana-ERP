"use client";
import { useEffect, useMemo, useState } from "react";
import type { ComponentType } from "react";
import Link from "next/link";
import { usePathname, useSearchParams } from "next/navigation";
import {
  BarChart3,
  Boxes,
  Building2,
  Calculator,
  ClipboardList,
  Coins,
  Factory,
  FileText,
  Layers3,
  Menu,
  PackageCheck,
  PackageSearch,
  Palette,
  QrCode,
  Scissors,
  Settings,
  Shirt,
  ShoppingCart,
  Truck,
  UserRoundCog,
  Users,
  Warehouse,
  X,
} from "lucide-react";
import { useMe, can } from "@/lib/auth";
import { useT } from "@/lib/i18n";
import BrandLogo from "@/components/BrandLogo";

type NavItem = { href: string; labelKey: string; perms?: string[]; icon: ComponentType<{ className?: string }> };
type Section = { titleKey: string; items: NavItem[] };

const SECTIONS: Section[] = [
  {
    titleKey: "section.overview",
    items: [
      { href: "/", labelKey: "nav.dashboard", icon: BarChart3 },
      { href: "/processes", labelKey: "nav.processes", perms: ["processes.view", "*"], icon: ClipboardList },
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
      { href: "/production-orders", labelKey: "nav.productionOrders", perms: ["planning.production"], icon: Factory },
    ],
  },
  {
    titleKey: "section.inventory",
    items: [
      { href: "/inventory?group=materials", labelKey: "nav.materialInventory", perms: ["storage.items", "storage.receive"], icon: Warehouse },
      { href: "/inventory?group=accessories", labelKey: "nav.accessoryInventory", perms: ["storage.items", "storage.receive"], icon: PackageSearch },
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
      { href: "/sewing/flows", labelKey: "nav.sewingFlows", perms: ["sewing.records", "sewing.bundles", "planning.production", "sewing.flows"], icon: Layers3 },
      { href: "/departments/SEW", labelKey: "nav.sewingFloor", perms: ["sewing.records", "sewing.bundles", "planning.production"], icon: Shirt },
      { href: "/departments/MIL", labelKey: "nav.milanaSewing", perms: ["sewing.records", "sewing.bundles", "planning.production"], icon: Factory },
      { href: "/departments/BST", labelKey: "nav.besttexSewing", perms: ["sewing.records", "sewing.bundles", "planning.production"], icon: Factory },
      { href: "/bundles/scan/sewing", labelKey: "nav.scanBundle", perms: ["sewing.bundles", "sewing.records"], icon: QrCode },
    ],
  },
  {
    titleKey: "section.packaging",
    items: [
      { href: "/departments/PKG", labelKey: "nav.packagingFloor", perms: ["packaging.records", "packaging.packages", "planning.production"], icon: PackageCheck },
      { href: "/packages", labelKey: "nav.packages", perms: ["packaging.packages", "packaging.records"], icon: Boxes },
      { href: "/packages/scan", labelKey: "nav.scanPackage", perms: ["packaging.packages", "packaging.records"], icon: QrCode },
    ],
  },
  {
    titleKey: "section.payroll",
    items: [
      { href: "/process-qr", labelKey: "nav.processQr", perms: ["planning.production", "sewing.records", "sewing.bundles", "packaging.records"], icon: QrCode },
      { href: "/payroll/scan", labelKey: "nav.payrollScan", perms: ["planning.production", "sewing.records", "sewing.bundles", "packaging.records", "hr.employees"], icon: Calculator },
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
      { href: "/admin/departments", labelKey: "nav.departments", icon: Building2 },
      { href: "/admin/audit-logs", labelKey: "nav.auditLogs", perms: ["admin.audit"], icon: Settings },
      { href: "/admin/employees", labelKey: "nav.employees", perms: ["hr.employees"], icon: Users },
    ],
  },
];

function SidebarNavSections({
  sections,
  t,
  isActive,
  onNavigate,
  mobile = false,
}: {
  sections: Section[];
  t: (key: string) => string;
  isActive: (href: string) => boolean;
  onNavigate?: () => void;
  mobile?: boolean;
}) {
  return (
    <>
      {sections.map((sec) => (
        <div key={sec.titleKey} className={mobile ? "mb-5" : "mb-4"}>
          <div className="mb-2 px-2 text-[10px] font-bold uppercase tracking-[0.16em] text-[#8a8472]">{t(sec.titleKey)}</div>
          <ul className={mobile ? "grid grid-cols-1 gap-1" : "space-y-0.5"}>
            {sec.items.map((it) => {
              const active = isActive(it.href);
              const ItemIcon = it.icon;
              return (
                <li key={`${sec.titleKey}-${it.href}`}>
                  <Link
                    href={it.href}
                    onClick={onNavigate}
                    className={`flex h-10 min-w-0 items-center gap-2 rounded-md px-3 text-[13px] transition ${
                      active
                        ? "bg-[#14110b] text-[#fdfcf8] shadow-sm"
                        : "text-[#56503f] hover:bg-[#f1efe8] hover:text-[#14110b]"
                    }`}
                    title={t(it.labelKey)}
                  >
                    <ItemIcon className="h-4 w-4 shrink-0" />
                    <span className="truncate">{t(it.labelKey)}</span>
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
  const visibleSections = useMemo(
    () =>
      SECTIONS.map((sec) => ({
        ...sec,
        items: sec.items.filter((i) => !i.perms || can(me, ...i.perms)),
      })).filter((sec) => sec.items.length > 0),
    [me],
  );

  useEffect(() => {
    setMobileOpen(false);
  }, [pathname, searchKey]);

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
    return (
      !bundlesScanMismatch &&
      !packagesScanMismatch &&
      !inventoryGroupMismatch &&
      (pathname === basePath || (basePath !== "/" && pathname?.startsWith(basePath)))
    );
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
            className="absolute left-0 top-0 flex h-full w-[86vw] max-w-[360px] flex-col border-r border-[#e3dfd3] bg-[#fdfcf8] text-[#2c2920] shadow-2xl"
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

      <aside className="sticky top-0 z-30 hidden h-screen w-60 shrink-0 flex-col overflow-hidden border-r border-[#e3dfd3] bg-[#fdfcf8] text-[#2c2920] lg:flex">
        <div className="flex h-28 shrink-0 items-center border-b border-[#ecebe3] px-3">
          <BrandLogo
            alt={t("app.name")}
            className="h-16 w-full max-w-[220px]"
          />
        </div>
        <nav className="flex-1 overflow-y-auto px-2 py-4">
          <SidebarNavSections sections={visibleSections} t={t} isActive={isActive} />
        </nav>
      </aside>
    </>
  );
}
