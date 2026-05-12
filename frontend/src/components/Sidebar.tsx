"use client";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { useMe, can } from "@/lib/auth";
import { useT } from "@/lib/i18n";

type NavItem = { href: string; labelKey: string; perms?: string[] };
type Section = { titleKey: string; items: NavItem[] };

const SECTIONS: Section[] = [
  {
    titleKey: "section.overview",
    items: [
      { href: "/", labelKey: "nav.dashboard" },
    ],
  },
  {
    titleKey: "section.sales",
    items: [
      { href: "/sales-orders", labelKey: "nav.salesOrders", perms: ["sales.orders"] },
      { href: "/customers", labelKey: "nav.customers", perms: ["sales.customers"] },
    ],
  },
  {
    titleKey: "section.plm",
    items: [
      { href: "/models", labelKey: "nav.models", perms: ["modeling.models"] },
      { href: "/brands", labelKey: "nav.brands", perms: ["modeling.brands"] },
      { href: "/collections", labelKey: "nav.collections", perms: ["modeling.collections"] },
    ],
  },
  {
    titleKey: "section.planning",
    items: [
      { href: "/planning", labelKey: "nav.planningDash", perms: ["planning.view", "planning.production"] },
      { href: "/production-orders", labelKey: "nav.productionOrders", perms: ["planning.production"] },
    ],
  },
  {
    titleKey: "section.inventory",
    items: [
      { href: "/inventory", labelKey: "nav.inventory", perms: ["storage.items", "storage.receive"] },
      { href: "/inventory/receive", labelKey: "nav.receive", perms: ["storage.receive"] },
      { href: "/inventory/batches", labelKey: "nav.batches", perms: ["storage.items"] },
    ],
  },
  {
    titleKey: "section.production",
    items: [
      { href: "/work-orders", labelKey: "nav.workOrders" },
      { href: "/bundles", labelKey: "nav.bundles" },
      { href: "/bundles/scan", labelKey: "nav.scanBundle" },
      { href: "/packages", labelKey: "nav.packages" },
      { href: "/packages/scan", labelKey: "nav.scanPackage" },
    ],
  },
  {
    titleKey: "section.storage",
    items: [
      { href: "/finished-goods", labelKey: "nav.finishedGoods" },
      { href: "/shipments", labelKey: "nav.shipments", perms: ["storage.shipment"] },
    ],
  },
  {
    titleKey: "section.waste",
    items: [
      { href: "/waste", labelKey: "nav.wasteDash" },
    ],
  },
  {
    titleKey: "section.finance",
    items: [
      { href: "/finance", labelKey: "nav.financeDash", perms: ["finance.view"] },
    ],
  },
  {
    titleKey: "section.admin",
    items: [
      { href: "/admin/users", labelKey: "nav.users", perms: ["admin.users"] },
      { href: "/admin/departments", labelKey: "nav.departments" },
      { href: "/admin/audit-logs", labelKey: "nav.auditLogs", perms: ["admin.audit"] },
      { href: "/hr/employees", labelKey: "nav.employees", perms: ["hr.employees"] },
    ],
  },
];

export default function Sidebar() {
  const { me } = useMe();
  const { t } = useT();
  const pathname = usePathname();
  return (
    <aside className="w-64 bg-slate-900 text-slate-200 min-h-screen p-4 sticky top-0 overflow-y-auto">
      <div className="text-xl font-bold mb-6 text-white">{t("app.name")}</div>
      {SECTIONS.map((sec) => {
        const visible = sec.items.filter((i) => !i.perms || can(me, ...i.perms));
        if (!visible.length) return null;
        return (
          <div key={sec.titleKey} className="mb-5">
            <div className="text-[11px] uppercase tracking-wider text-slate-400 mb-2">{t(sec.titleKey)}</div>
            <ul className="space-y-1">
              {visible.map((it) => {
                const active = pathname === it.href || (it.href !== "/" && pathname?.startsWith(it.href));
                return (
                  <li key={it.href}>
                    <Link
                      href={it.href}
                      className={`block px-3 py-1.5 rounded text-sm ${active ? "bg-brand-600 text-white" : "hover:bg-slate-800"}`}
                    >
                      {t(it.labelKey)}
                    </Link>
                  </li>
                );
              })}
            </ul>
          </div>
        );
      })}
    </aside>
  );
}
