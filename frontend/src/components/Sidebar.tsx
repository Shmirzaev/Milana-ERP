"use client";
import type { ComponentType } from "react";
import Link from "next/link";
import { usePathname } from "next/navigation";
import {
  BarChart3,
  Boxes,
  Building2,
  ClipboardList,
  Coins,
  Factory,
  Layers3,
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
} from "lucide-react";
import { useMe, can } from "@/lib/auth";
import { useT } from "@/lib/i18n";
import BrandMark from "@/components/BrandMark";

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
      { href: "/inventory", labelKey: "nav.inventory", perms: ["storage.items", "storage.receive"], icon: Warehouse },
      { href: "/inventory/receive", labelKey: "nav.receive", perms: ["storage.receive"], icon: PackageCheck },
      { href: "/inventory/batches", labelKey: "nav.batches", perms: ["storage.items"], icon: Boxes },
    ],
  },
  // Per-department production sections — each replaces the old "Production" bucket.
  {
    titleKey: "section.cutting",
    items: [
      { href: "/departments/CUT", labelKey: "nav.cuttingFloor", perms: ["cutting.records", "cutting.bundles", "planning.production"], icon: Scissors },
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
    titleKey: "section.storage",
    items: [
      { href: "/departments/FGS", labelKey: "nav.finishedGoods", icon: Building2 },
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
      { href: "/hr/employees", labelKey: "nav.employees", perms: ["hr.employees"], icon: Users },
    ],
  },
];

export default function Sidebar() {
  const { me } = useMe();
  const { t } = useT();
  const pathname = usePathname() || "";
  return (
    <aside className="sticky top-0 flex h-screen w-60 shrink-0 flex-col overflow-hidden border-r border-[#e3dfd3] bg-[#fdfcf8] text-[#2c2920]">
      <div className="flex h-20 items-center gap-3 border-b border-[#ecebe3] px-3">
        <BrandMark size={36} />
        <div className="min-w-0">
          <div className="truncate text-sm font-semibold text-[#14110b]">{t("app.name")}</div>
          <div className="text-xs leading-tight text-[#8a8472]">{t("sidebar.tagline")}</div>
        </div>
      </div>
      <div className="flex-1 overflow-y-auto px-2 py-4">
      {SECTIONS.map((sec) => {
        const visible = sec.items.filter((i) => !i.perms || can(me, ...i.perms));
        if (!visible.length) return null;
        return (
          <div key={sec.titleKey} className="mb-4">
            <div className="mb-2 px-2 text-[10px] font-bold uppercase tracking-[0.16em] text-[#8a8472]">{t(sec.titleKey)}</div>
            <ul className="space-y-0.5">
              {visible.map((it) => {
                const basePath = it.href.split("?")[0];
                const bundlesScanMismatch = basePath === "/bundles" && pathname.startsWith("/bundles/scan");
                const packagesScanMismatch = basePath === "/packages" && pathname.startsWith("/packages/scan");
                const active =
                  !bundlesScanMismatch &&
                  !packagesScanMismatch &&
                  (pathname === basePath || (basePath !== "/" && pathname?.startsWith(basePath)));
                const ItemIcon = it.icon;
                return (
                  <li key={`${sec.titleKey}-${it.href}`}>
                    <Link
                      href={it.href}
                      className={`flex h-9 items-center gap-2 rounded-md px-2 text-[13px] transition ${
                        active
                          ? "bg-[#14110b] text-[#fdfcf8] shadow-sm"
                          : "text-[#56503f] hover:bg-[#f1efe8] hover:text-[#14110b]"
                      }`}
                    >
                      <ItemIcon className="h-4 w-4 shrink-0" />
                      <span className="truncate">
                      {t(it.labelKey)}
                      </span>
                    </Link>
                  </li>
                );
              })}
            </ul>
          </div>
        );
      })}
      </div>
    </aside>
  );
}
