"use client";
import { useMemo } from "react";
import { useSearchParams } from "next/navigation";
import useSWR from "swr";
import { fetcher } from "@/lib/api";
import PageHeader from "@/components/PageHeader";
import { useT } from "@/lib/i18n";

export default function InventoryPage() {
  const searchParams = useSearchParams();
  const q = (searchParams.get("q") ?? "").trim().toLowerCase();
  const { t } = useT();
  const { data: stock } = useSWR<any[]>("/api/inventory/stock", fetcher);
  const { data: items } = useSWR<any[]>("/api/inventory/items", fetcher);

  const rows = useMemo(() => {
    if (!stock) return [];
    if (!q) return stock;
    return stock.filter((s) => {
      const sku = String(s.item_sku ?? "").toLowerCase();
      const name = String(s.item_name ?? "").toLowerCase();
      const unit = String(s.unit ?? "").toLowerCase();
      return sku.includes(q) || name.includes(q) || unit.includes(q);
    });
  }, [stock, q]);

  return (
    <div>
      <PageHeader title={t("page.inventory.title")} subtitle={t("page.inventory.subtitle")} />
      <div className="grid grid-cols-3 gap-4 mb-6">
        <div className="card p-4"><div className="text-xs text-slate-500">{t("page.inventory.itemTypes")}</div><div className="text-2xl font-semibold">{items?.length ?? 0}</div></div>
        <div className="card p-4"><div className="text-xs text-slate-500">{t("page.inventory.linesTracked")}</div><div className="text-2xl font-semibold">{stock?.length ?? 0}</div></div>
      </div>
      <div className="card overflow-x-auto">
        <table className="table">
          <thead>
            <tr>
              <th>{t("field.sku")}</th>
              <th>{t("common.name")}</th>
              <th>{t("field.quantity")}</th>
              <th>{t("field.unit")}</th>
            </tr>
          </thead>
          <tbody>{rows.map((s) => <tr key={s.item_id}><td>{s.item_sku}</td><td>{s.item_name}</td><td>{Number(s.quantity).toFixed(2)}</td><td>{s.unit}</td></tr>)}</tbody>
        </table>
      </div>
    </div>
  );
}
