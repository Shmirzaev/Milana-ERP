"use client";
import type { ComponentType } from "react";
import Link from "next/link";
import { usePathname, useSearchParams } from "next/navigation";
import {
  BarChart3,
  Boxes,
  Building2,
  ClipboardList,
  Coins,
  Factory,
  FileText,
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

export default function Sidebar() {
  const { me } = useMe();
  const { t } = useT();
  const pathname = usePathname() || "";
  const searchParams = useSearchParams();
  const inventoryGroup = searchParams.get("group") || "materials";
  return (
    <aside className="sticky top-0 z-30 flex max-h-[42vh] w-full shrink-0 flex-col overflow-hidden border-b border-[#e3dfd3] bg-[#fdfcf8] text-[#2c2920] lg:h-screen lg:max-h-none lg:w-60 lg:border-b-0 lg:border-r">
      <div className="flex h-16 shrink-0 items-center border-b border-[#ecebe3] px-3 lg:h-28">
        <BrandLogo
          alt={t("app.name")}
          className="h-10 w-auto max-w-[180px] lg:h-16 lg:w-full lg:max-w-[220px]"
        />
      </div>
      <div className="flex flex-1 gap-3 overflow-x-auto overflow-y-hidden px-2 py-3 lg:block lg:overflow-x-hidden lg:overflow-y-auto lg:py-4">
      {SECTIONS.map((sec) => {
        const visible = sec.items.filter((i) => !i.perms || can(me, ...i.perms));
        if (!visible.length) return null;
        return (
          <div key={sec.titleKey} className="min-w-[150px] shrink-0 lg:mb-4 lg:min-w-0 lg:shrink">
            <div className="mb-2 px-2 text-[10px] font-bold uppercase tracking-[0.16em] text-[#8a8472]">{t(sec.titleKey)}</div>
            <ul className="flex gap-1 lg:block lg:space-y-0.5">
              {visible.map((it) => {
                const basePath = it.href.split("?")[0];
                const itemGroup = new URLSearchParams(it.href.split("?")[1] || "").get("group") || "";
                const bundlesScanMismatch = basePath === "/bundles" && pathname.startsWith("/bundles/scan");
                const packagesScanMismatch = basePath === "/packages" && pathname.startsWith("/packages/scan");
                const inventoryGroupMismatch = basePath === "/inventory" && (pathname !== "/inventory" || itemGroup !== inventoryGroup);
                const active =
                  !bundlesScanMismatch &&
                  !packagesScanMismatch &&
                  !inventoryGroupMismatch &&
                  (pathname === basePath || (basePath !== "/" && pathname?.startsWith(basePath)));
                const ItemIcon = it.icon;
                return (
                  <li key={`${sec.titleKey}-${it.href}`}>
                    <Link
                      href={it.href}
                      className={`flex h-9 min-w-[42px] items-center justify-center gap-2 rounded-md px-2 text-[13px] transition lg:justify-start ${
                        active
                          ? "bg-[#14110b] text-[#fdfcf8] shadow-sm"
                          : "text-[#56503f] hover:bg-[#f1efe8] hover:text-[#14110b]"
                      }`}
                      title={t(it.labelKey)}
                    >
                      <ItemIcon className="h-4 w-4 shrink-0" />
                      <span className="hidden truncate sm:inline">
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
